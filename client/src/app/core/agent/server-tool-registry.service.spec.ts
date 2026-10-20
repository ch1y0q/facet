import type { Mock } from 'vitest';
import { EnvironmentInjector, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { HttpClient } from '@angular/common/http';
import { Observable, Subject, of, throwError } from 'rxjs';
import { AuthService, AuthStatus } from '../services/auth.service';
import { AgentWebMcpService } from './agent-web-mcp.service';
import { InpageChangeNotifier } from './inpage-change-notifier.service';
import { INPAGE_OPT_IN_KEY, ServerToolRegistry, SESSION_HEADER } from './server-tool-registry.service';
import { WebMcpToolRegistry } from './webmcp-registry.service';
import { McpInpageTool } from '../api/types';

interface Registered {
  name: string;
  annotations: Record<string, boolean>;
  inputSchema: { properties: Record<string, unknown> };
  execute: (args: unknown, client: unknown) => Promise<string>;
}

function status(over: Partial<AuthStatus> = {}, features: Record<string, boolean> = {}): AuthStatus {
  return {
    authenticated: true, multi_user: false, edition_enabled: true, edition_authenticated: false,
    edition_password_required: true, login_password_required: true, user_id: null, user_role: null,
    display_name: null, features: { mcp: true, mcp_inpage: true, ...features }, download_profiles: [], ...over,
  };
}

const TOOLS: McpInpageTool[] = [
  { name: 'search_photos', description: 'd', inputSchema: { type: 'object', properties: { query: {}, tab_id: {} } }, annotations: { readOnlyHint: true }, required_level: 'readonly' },
  { name: 'set_rating', description: 'd', inputSchema: { type: 'object', properties: { target: {}, rating: {} } }, annotations: { readOnlyHint: false }, required_level: 'edition' },
];

describe('ServerToolRegistry', () => {
  let authStatus: ReturnType<typeof signal<AuthStatus | null>>;
  let session: ReturnType<typeof signal<EnvironmentInjector | null>>;
  let live: Map<string, Registered>;
  let get: Mock;
  let post: Mock;
  let notify: Mock;
  let uiExecute: Mock;
  let service: ServerToolRegistry;

  const settle = async (): Promise<void> => {
    for (let i = 0; i < 4; i += 1) {
      TestBed.tick();
      await new Promise(resolve => setTimeout(resolve, 0));
    }
  };

  const setup = (initial: AuthStatus | null, optIn = true): void => {
    if (optIn) localStorage.setItem(INPAGE_OPT_IN_KEY, '1');
    authStatus = signal(initial);
    session = signal<EnvironmentInjector | null>(null);
    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: { status: authStatus } },
        { provide: AgentWebMcpService, useValue: { sessionInjector: session } },
        { provide: HttpClient, useValue: { get, post } },
        { provide: InpageChangeNotifier, useValue: { notify } },
        { provide: WebMcpToolRegistry, useValue: { execute: uiExecute } },
      ],
    });
    service = TestBed.inject(ServerToolRegistry);
    session.set(TestBed.inject(EnvironmentInjector));
  };

  beforeEach(() => {
    localStorage.clear();
    live = new Map();
    Object.defineProperty(document, 'modelContext', {
      configurable: true,
      value: {
        registerTool: (tool: Registered, options?: { signal?: AbortSignal }) => {
          live.set(tool.name, tool);
          options?.signal?.addEventListener('abort', () => live.delete(tool.name));
          return Promise.resolve();
        },
      },
    });
    get = vi.fn(() => of({ level: 'edition', tools: TOOLS }));
    post = vi.fn(() => of({ ok: true, data: {} }));
    notify = vi.fn();
    uiExecute = vi.fn(async () => ({ ok: true as const, data: { scope: 'paths', count: 1, paths: ['/a.jpg'] } }));
  });

  afterEach(() => {
    Reflect.deleteProperty(document, 'modelContext');
    TestBed.resetTestingModule();
    localStorage.clear();
  });

  it('registers the readonly tier at readonly level, with the hints, and strips tab_id from the schema', async () => {
    setup(status());
    await settle();
    expect([...live.keys()]).toEqual(['search_photos']);
    expect(live.get('search_photos')?.annotations).toEqual({ readOnlyHint: true, untrustedContentHint: true });
    expect(live.get('search_photos')?.inputSchema.properties).not.toHaveProperty('tab_id');
  });

  it('unlock adds the edition tier, lock removes exactly it, and the writes carry consequentialHint', async () => {
    setup(status());
    await settle();
    authStatus.set(status({ edition_authenticated: true }));
    await settle();
    expect([...live.keys()].sort()).toEqual(['search_photos', 'set_rating']);
    expect(live.get('set_rating')?.annotations).toEqual({ readOnlyHint: false, consequentialHint: true, untrustedContentHint: true });
    const fetches = get.mock.calls.length;
    authStatus.set(status());
    await settle();
    expect([...live.keys()]).toEqual(['search_photos']);
    expect(get.mock.calls.length).toBe(fetches);
  });

  it('logout clears every tier', async () => {
    setup(status({ edition_authenticated: true }));
    await settle();
    expect(live.size).toBe(2);
    authStatus.set(null);
    await settle();
    expect(live.size).toBe(0);
  });

  it('registers no server tool and fetches nothing while the browser opt-in is off', async () => {
    setup(status(), false);
    await settle();
    expect(get).not.toHaveBeenCalled();
    expect(live.size).toBe(0);
  });

  it('turning the opt-in off tears the tools down', async () => {
    setup(status());
    await settle();
    service.setOptIn(false);
    await settle();
    expect(live.size).toBe(0);
    expect(localStorage.getItem(INPAGE_OPT_IN_KEY)).toBeNull();
  });

  it('fetches nothing when features.mcp_inpage is false', async () => {
    setup(status({}, { mcp_inpage: false }));
    await settle();
    expect(get).not.toHaveBeenCalled();
    expect(live.size).toBe(0);
  });

  it('does not re-fetch when the status changes without changing the level', async () => {
    setup(status());
    await settle();
    authStatus.set(status({ display_name: 'someone else' }));
    await settle();
    expect(get).toHaveBeenCalledTimes(1);
  });

  it('does not abort an in-flight POST when the edition child is destroyed by a lock', async () => {
    setup(status({ edition_authenticated: true }));
    await settle();
    const reply = new Subject<{ ok: boolean }>();
    let unsubscribed = false;
    post.mockImplementation(() => new Observable(sub => {
      const inner = reply.subscribe(sub);
      return () => { unsubscribed = true; inner.unsubscribe(); };
    }));
    const pending = live.get('set_rating')!.execute({ rating: 3 }, {});
    authStatus.set(status());
    await settle();
    expect(live.has('set_rating')).toBe(false);
    expect(unsubscribed).toBe(false);
    reply.next({ ok: true });
    reply.complete();
    expect(JSON.parse(await pending)).toEqual({ ok: true });
  });

  it('injects the caller tab selection for target "selection", strips tab_id and sends the session header', async () => {
    setup(status({ edition_authenticated: true }));
    await settle();
    await live.get('set_rating')!.execute({ target: 'selection', rating: 4, tab_id: 'other' }, {});
    expect(uiExecute).toHaveBeenCalledWith('ui_get_selection', {});
    const [url, body, options] = post.mock.calls[0];
    expect(url).toBe('/api/mcp/call');
    expect(body).toEqual({
      tool: 'set_rating',
      arguments: { target: 'selection', rating: 4 },
      selection_snapshot: { scope: 'paths', count: 1, paths: ['/a.jpg'] },
    });
    expect(options.headers.get(SESSION_HEADER)).toMatch(/^[A-Za-z0-9_-]{1,64}$/);
  });

  it('sends no snapshot when the target is not the selection', async () => {
    setup(status({ edition_authenticated: true }));
    await settle();
    await live.get('set_rating')!.execute({ target: 'paths', rating: 4 }, {});
    expect(uiExecute).not.toHaveBeenCalled();
    expect(post.mock.calls[0][1]).not.toHaveProperty('selection_snapshot');
  });

  it('reports a changed write to the notifier, but not a read', async () => {
    setup(status({ edition_authenticated: true }));
    await settle();
    post.mockReturnValue(of({ ok: true, changed: 3, batch_id: 'b1' }));
    await live.get('set_rating')!.execute({ rating: 1 }, {});
    expect(notify).toHaveBeenCalledWith(3, 'b1');
    notify.mockClear();
    await live.get('search_photos')!.execute({ query: 'x' }, {});
    expect(notify).not.toHaveBeenCalled();
  });

  it('turns a 403 into an error envelope and a transport failure into upstream_error', async () => {
    setup(status());
    await settle();
    post.mockReturnValueOnce(throwError(() => ({ status: 403 })));
    expect(JSON.parse(await live.get('search_photos')!.execute({}, {})).error).toBe('forbidden_level');
    post.mockReturnValueOnce(throwError(() => ({ status: 0 })));
    expect(JSON.parse(await live.get('search_photos')!.execute({}, {})).error).toBe('upstream_error');
  });
});
