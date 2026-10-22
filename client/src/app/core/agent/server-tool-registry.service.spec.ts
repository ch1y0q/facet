import type { Mock } from 'vitest';
import { EnvironmentInjector, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { HttpClient } from '@angular/common/http';
import { Observable, Subject, of, throwError } from 'rxjs';
import { AuthService, AuthStatus } from '../services/auth.service';
import { AgentWebMcpService } from './agent-web-mcp.service';
import { AssistantChangesService } from './assistant-changes.service';
import { AgentBridgeService } from './agent-bridge.service';
import { INPAGE_OPT_IN_KEY, INPAGE_RETRY_MS, ServerToolRegistry, SESSION_HEADER, inpageLevel } from './server-tool-registry.service';
import { GalleryStore } from '../../features/gallery/gallery.store';
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
  { name: 'search_photos', description: 'd', inputSchema: { type: 'object', properties: { query: {}, tab_id: {} } }, annotations: { readOnlyHint: true, consequentialHint: false, untrustedContentHint: true }, required_level: 'readonly' },
  { name: 'set_rating', description: 'd', inputSchema: { type: 'object', properties: { target: {}, rating: {} } }, annotations: { readOnlyHint: false, consequentialHint: true, untrustedContentHint: true }, required_level: 'edition' },
];

describe('ServerToolRegistry', () => {
  let authStatus: ReturnType<typeof signal<AuthStatus | null>>;
  let session: ReturnType<typeof signal<EnvironmentInjector | null>>;
  let live: Map<string, Registered>;
  let get: Mock;
  let post: Mock;
  let report: Mock;
  let uiExecute: Mock;
  let review: ReturnType<typeof signal<{ keep: string[]; remove: string[]; truncated: boolean }>>;
  let hasReview: ReturnType<typeof signal<boolean>>;
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
    review = signal({ keep: [] as string[], remove: [] as string[], truncated: false });
    hasReview = signal(false);
    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: { status: authStatus } },
        { provide: AgentWebMcpService, useValue: { sessionInjector: session } },
        { provide: HttpClient, useValue: { get, post } },
        { provide: AssistantChangesService, useValue: { report } },
        { provide: AgentBridgeService, useValue: { tabId: 'tab-1' } },
        { provide: WebMcpToolRegistry, useValue: { execute: uiExecute } },
        { provide: GalleryStore, useValue: { review, hasReview } },
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
    report = vi.fn();
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
      tab_id: 'tab-1',
      selection_snapshot: { scope: 'paths', count: 1, paths: ['/a.jpg'] },
    });
    expect(options.headers.get(SESSION_HEADER)).toMatch(/^[A-Za-z0-9_-]{1,64}$/);
  });

  it('sends the tab review as review_snapshot whenever a review exists, even with empty lists, and omits it otherwise', async () => {
    setup(status({ edition_authenticated: true }));
    await settle();
    await live.get('set_rating')!.execute({ rating: 4 }, {});
    expect(post.mock.calls[0][1]).not.toHaveProperty('review_snapshot');
    hasReview.set(true);
    await live.get('set_rating')!.execute({ rating: 4 }, {});
    expect(post.mock.calls[1][1].review_snapshot).toEqual({ keep: [], remove: [], truncated: false });
    review.set({ keep: ['/k.jpg'], remove: ['/r.jpg'], truncated: false });
    await live.get('set_rating')!.execute({ rating: 4 }, {});
    expect(post.mock.calls[2][1].review_snapshot).toEqual({ keep: ['/k.jpg'], remove: ['/r.jpg'], truncated: false });
  });

  it('counts an auto_cull apply by its show_paths when the envelope has no changed', async () => {
    setup(status({ edition_authenticated: true }));
    await settle();
    post.mockReturnValue(of({ ok: true, changed_paths: null, show_paths: ['/a', '/b'] }));
    await live.get('set_rating')!.execute({ rating: 1 }, {});
    expect(report).toHaveBeenCalledWith(expect.objectContaining({ paths: null, count: 2, showPaths: ['/a', '/b'] }));
  });

  it('reports agentTool, a per-call callId and showPaths from the response', async () => {
    setup(status({ edition_authenticated: true }));
    await settle();
    post.mockReturnValue(of({ ok: true, changed: 2, changed_paths: null, show_paths: ['/a', '/b'] }));
    await live.get('set_rating')!.execute({ rating: 1 }, {});
    await live.get('set_rating')!.execute({ rating: 1 }, {});
    const first = report.mock.calls[0][0];
    const second = report.mock.calls[1][0];
    expect(first).toMatchObject({ agentTool: 'set_rating', showPaths: ['/a', '/b'], paths: null, count: 2 });
    expect(typeof first.callId).toBe('string');
    expect(first.callId.length).toBeGreaterThan(0);
    expect(second.callId).not.toBe(first.callId);
  });

  it('sends no snapshot when the target is not the selection', async () => {
    setup(status({ edition_authenticated: true }));
    await settle();
    await live.get('set_rating')!.execute({ target: 'paths', rating: 4 }, {});
    expect(uiExecute).not.toHaveBeenCalled();
    expect(post.mock.calls[0][1]).not.toHaveProperty('selection_snapshot');
  });

  it('reports a write carrying changed_paths to AssistantChanges, not a read, and sends the tab id', async () => {
    setup(status({ edition_authenticated: true }));
    await settle();
    post.mockReturnValue(of({ ok: true, changed: 3, changed_paths: ['/a', '/b', '/c'] }));
    await live.get('set_rating')!.execute({ rating: 1 }, {});
    expect(report).toHaveBeenCalledTimes(1);
    expect(report).toHaveBeenCalledWith({ tool: 'set_rating', agentTool: 'set_rating', callId: expect.any(String), paths: ['/a', '/b', '/c'], count: 3 });
    expect(post.mock.calls[0][1].tab_id).toBe('tab-1');
    report.mockClear();
    post.mockReturnValue(of({ ok: true }));
    await live.get('search_photos')!.execute({ query: 'x' }, {});
    expect(report).not.toHaveBeenCalled();
  });

  it('reports on key presence: null paths, ok:false outcome_unknown, and no report when the key is absent', async () => {
    setup(status({ edition_authenticated: true }));
    await settle();
    post.mockReturnValueOnce(of({ ok: true, changed_paths: null, changed: 12 }));
    await live.get('set_rating')!.execute({ rating: 1 }, {});
    expect(report).toHaveBeenLastCalledWith({ tool: 'set_rating', agentTool: 'set_rating', callId: expect.any(String), paths: null, count: 12 });
    post.mockReturnValueOnce(of({ ok: false, error: 'outcome_unknown', changed_paths: ['/z'] }));
    await live.get('set_rating')!.execute({ rating: 1 }, {});
    expect(report).toHaveBeenLastCalledWith({ tool: 'set_rating', agentTool: 'set_rating', callId: expect.any(String), paths: ['/z'], count: 1 });
    report.mockClear();
    post.mockReturnValueOnce(of({ ok: true, changed: 2 }));
    await live.get('set_rating')!.execute({ rating: 1 }, {});
    expect(report).not.toHaveBeenCalled();
  });

  it('turns a 403 into an error envelope and a transport failure into upstream_error', async () => {
    setup(status());
    await settle();
    post.mockReturnValueOnce(throwError(() => ({ status: 403 })));
    expect(JSON.parse(await live.get('search_photos')!.execute({}, {})).error).toBe('forbidden_level');
    post.mockReturnValueOnce(throwError(() => ({ status: 0 })));
    expect(JSON.parse(await live.get('search_photos')!.execute({}, {})).error).toBe('upstream_error');
  });

  it('constructs without crypto.randomUUID (plain-HTTP context) and still sends a well-formed session id', async () => {
    Object.defineProperty(crypto, 'randomUUID', { value: undefined, configurable: true });
    try {
      setup(status());
      await settle();
      await live.get('search_photos')!.execute({}, {});
      const id = post.mock.calls[0][2].headers.get(SESSION_HEADER) as string;
      expect(id).toMatch(/^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/);
    } finally {
      Reflect.deleteProperty(crypto, 'randomUUID');
    }
  });

  it('a lock during the user-tier registration creates no edition child', async () => {
    const userTool: McpInpageTool = { name: 'user_tool', description: 'd', inputSchema: { type: 'object', properties: {} }, annotations: { readOnlyHint: true, consequentialHint: false, untrustedContentHint: true }, required_level: 'user' };
    get.mockReturnValue(of({ level: 'edition', tools: [...TOOLS, userTool] }));
    let release: () => void = () => undefined;
    const gate = new Promise<void>(resolve => { release = resolve; });
    Object.defineProperty(document, 'modelContext', {
      configurable: true,
      value: {
        registerTool: (tool: Registered, options?: { signal?: AbortSignal }) => {
          live.set(tool.name, tool);
          options?.signal?.addEventListener('abort', () => live.delete(tool.name));
          return tool.name === 'user_tool' ? gate : Promise.resolve();
        },
      },
    });
    setup(status({ multi_user: true, edition_authenticated: true }));
    await settle();
    expect(live.has('user_tool')).toBe(true);
    authStatus.set(status({ multi_user: true }));
    await settle();
    release();
    await settle();
    expect(live.has('set_rating')).toBe(false);
    expect([...live.keys()].sort()).toEqual(['search_photos', 'user_tool']);
  });

  describe('a failed tool listing', () => {
    const settleFake = async (): Promise<void> => {
      for (let i = 0; i < 4; i += 1) {
        TestBed.tick();
        await vi.advanceTimersByTimeAsync(0);
      }
    };

    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('warns and retries once after the backoff', async () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
      get.mockReturnValueOnce(throwError(() => ({ status: 500 })));
      setup(status());
      await settleFake();
      expect(live.size).toBe(0);
      expect(warn).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(INPAGE_RETRY_MS);
      await settleFake();
      expect(get).toHaveBeenCalledTimes(2);
      expect([...live.keys()]).toEqual(['search_photos']);
      warn.mockRestore();
    });

    it('gives up after the one retry instead of looping', async () => {
      const warn = vi.spyOn(console, 'warn').mockImplementation(() => undefined);
      get.mockReturnValue(throwError(() => ({ status: 500 })));
      setup(status());
      await settleFake();
      await vi.advanceTimersByTimeAsync(INPAGE_RETRY_MS * 10);
      await settleFake();
      expect(get).toHaveBeenCalledTimes(2);
      expect(live.size).toBe(0);
      warn.mockRestore();
    });
  });
});

describe('inpageLevel', () => {
  const base = { authenticated: true, multi_user: false, edition_authenticated: false };

  it('is null when nobody is signed in or the status is unknown', () => {
    expect(inpageLevel(null)).toBeNull();
    expect(inpageLevel({ ...base, authenticated: false })).toBeNull();
  });

  it('maps a multi-user regular account to user and an admin to edition', () => {
    expect(inpageLevel({ ...base, multi_user: true })).toBe('user');
    expect(inpageLevel({ ...base, multi_user: true, edition_authenticated: true })).toBe('edition');
  });

  it('maps a single-password install to readonly when locked and edition when unlocked', () => {
    expect(inpageLevel(base)).toBe('readonly');
    expect(inpageLevel({ ...base, edition_authenticated: true })).toBe('edition');
  });

  it('maps an open install (authenticated, no passwords, edition not unlocked) to readonly', () => {
    expect(inpageLevel({ authenticated: true, multi_user: false, edition_authenticated: false })).toBe('readonly');
  });
});
