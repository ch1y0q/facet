import type { Mock } from 'vitest';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { NavigationEnd, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { AuthService, AuthStatus } from '../services/auth.service';
import {
  AgentBridgeService,
  BACKOFF_MAX_MS,
  BRIDGE_SOCKET_FACTORY,
  BridgeSocket,
  SUPERSEDED_COOLDOWN_MS,
} from './agent-bridge.service';
import { WebMcpToolRegistry } from './webmcp-registry.service';

class FakeSocket implements BridgeSocket {
  static instances: FakeSocket[] = [];
  onopen: ((event: unknown) => void) | null = null;
  onmessage: ((event: { data: unknown }) => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  sent: Record<string, unknown>[] = [];
  closedWith: number | undefined;
  readyState = 1;
  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }
  send(data: string): void {
    if (this.readyState !== 1) throw new Error('InvalidStateError');
    this.sent.push(JSON.parse(data) as Record<string, unknown>);
  }
  close(code?: number): void {
    this.closedWith = code;
  }
  open(): void {
    this.onopen?.({});
  }
  receive(frame: unknown): void {
    this.onmessage?.({ data: JSON.stringify(frame) });
  }
  serverClose(code: number): void {
    this.onclose?.({ code });
  }
}

function status(overrides: Partial<AuthStatus> = {}): AuthStatus {
  return {
    authenticated: true, multi_user: true, edition_enabled: true, edition_authenticated: false,
    edition_password_required: false, login_password_required: true, user_id: 'u', user_role: 'user',
    display_name: 'U', features: { mcp: true, mcp_bridge: true }, download_profiles: [], ...overrides,
  };
}

describe('AgentBridgeService', () => {
  let authStatus: ReturnType<typeof signal<AuthStatus | null>>;
  let token: string | null;
  let loginRequired: boolean;
  let routerEvents: Subject<unknown>;
  let execute: Mock;
  let bridge: AgentBridgeService;

  const last = (): FakeSocket => FakeSocket.instances[FakeSocket.instances.length - 1];
  const settle = (): void => TestBed.tick();
  const connectReady = (): FakeSocket => {
    const socket = last();
    socket.open();
    socket.receive({ type: 'ready', user_id: 'u', tab_id: bridge.tabId, tools_version: 'v1' });
    return socket;
  };

  beforeEach(() => {
    vi.useFakeTimers();
    FakeSocket.instances = [];
    token = 'jwt-1';
    loginRequired = true;
    authStatus = signal<AuthStatus | null>(status());
    routerEvents = new Subject();
    execute = vi.fn(async () => ({ ok: true, data: { hello: 'world' } }));
    TestBed.configureTestingModule({
      providers: [
        { provide: BRIDGE_SOCKET_FACTORY, useValue: (url: string) => new FakeSocket(url) },
        {
          provide: AuthService,
          useValue: {
            status: authStatus,
            get token() { return token; },
            loginPasswordRequired: () => loginRequired,
          },
        },
        { provide: Router, useValue: { url: '/persons?x=1', events: routerEvents } },
        { provide: WebMcpToolRegistry, useValue: { toolNames: ['ui_navigate', 'ui_get_selection'], toolsVersion: 'v1', execute, ready: signal(true), load: () => Promise.resolve() } },
      ],
    });
    bridge = TestBed.inject(AgentBridgeService);
    settle();
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.useRealTimers();
    TestBed.resetTestingModule();
  });

  it('opens a same-origin ws URL and sends the auth frame first, with the token in the frame only', () => {
    expect(FakeSocket.instances).toHaveLength(1);
    const socket = last();
    expect(socket.url).toMatch(/^wss?:\/\/[^/]+\/api\/mcp\/bridge$/);
    expect(socket.url).not.toContain('jwt-1');
    socket.open();
    expect(socket.sent).toHaveLength(1);
    expect(socket.sent[0]).toMatchObject({
      type: 'auth', token: 'jwt-1', tab_id: bridge.tabId, route: '/persons?x=1',
      tools: ['ui_navigate', 'ui_get_selection'], tools_version: 'v1',
    });
    expect(typeof socket.sent[0]['focused']).toBe('boolean');
    expect(bridge.tabId).toMatch(/^[A-Za-z0-9_-]{1,64}$/);
  });

  it('sends a null token on an open install', () => {
    TestBed.resetTestingModule();
    FakeSocket.instances = [];
    token = null;
    loginRequired = false;
    TestBed.configureTestingModule({
      providers: [
        { provide: BRIDGE_SOCKET_FACTORY, useValue: (url: string) => new FakeSocket(url) },
        { provide: AuthService, useValue: { status: signal(status({ multi_user: false, login_password_required: false })), get token() { return token; }, loginPasswordRequired: () => loginRequired } },
        { provide: Router, useValue: { url: '/', events: routerEvents } },
        { provide: WebMcpToolRegistry, useValue: { toolNames: [], toolsVersion: 'v1', execute, ready: signal(true), load: () => Promise.resolve() } },
      ],
    });
    TestBed.inject(AgentBridgeService);
    settle();
    last().open();
    expect(last().sent[0]).toMatchObject({ type: 'auth', token: null });
  });

  it('does not connect when the feature is off, signed out, or a password install has no live token', () => {
    TestBed.resetTestingModule();
    for (const [st, tok] of [
      [status({ features: { mcp: false } }), 'jwt'],
      [status({ features: {} }), 'jwt'],
      [status({ features: { mcp: true, mcp_bridge: false } }), 'jwt'],
      [status({ features: { mcp: true } }), 'jwt'],
      [null, 'jwt'],
      [status({ authenticated: false }), 'jwt'],
      [status(), null],
    ] as [AuthStatus | null, string | null][]) {
      FakeSocket.instances = [];
      token = tok;
      TestBed.configureTestingModule({
        providers: [
          { provide: BRIDGE_SOCKET_FACTORY, useValue: (url: string) => new FakeSocket(url) },
          { provide: AuthService, useValue: { status: signal(st), get token() { return token; }, loginPasswordRequired: () => true } },
          { provide: Router, useValue: { url: '/', events: routerEvents } },
          { provide: WebMcpToolRegistry, useValue: { toolNames: [], toolsVersion: 'v1', execute, ready: signal(true), load: () => Promise.resolve() } },
        ],
      });
      TestBed.inject(AgentBridgeService);
      settle();
      expect(FakeSocket.instances).toHaveLength(0);
      TestBed.resetTestingModule();
    }
  });

  it('answers a call with exactly one result frame carrying the same id', async () => {
    const socket = connectReady();
    socket.receive({ type: 'call', id: 'abc', tool: 'ui_get_selection', args: {} });
    await vi.advanceTimersByTimeAsync(0);
    const results = socket.sent.filter(f => f['type'] === 'result');
    expect(results).toEqual([{ type: 'result', id: 'abc', ok: true, data: { hello: 'world' } }]);
    expect(execute).toHaveBeenCalledWith('ui_get_selection', {});
  });

  it('drops the answer when the socket that carried the call has gone, even if a new one is open', async () => {
    const first = connectReady();
    let release: (v: unknown) => void = () => undefined;
    execute.mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
    first.receive({ type: 'call', id: 'late', tool: 'ui_get_selection', args: {} });
    first.serverClose(1006);
    await vi.advanceTimersByTimeAsync(1000);
    const second = last();
    expect(second).not.toBe(first);
    second.open();
    release({ ok: true, data: {} });
    await vi.advanceTimersByTimeAsync(0);
    expect(second.sent.filter(f => f['type'] === 'result')).toEqual([]);
    expect(first.sent.filter(f => f['type'] === 'result')).toEqual([]);
  });

  it('sends nothing on a socket that is no longer OPEN', async () => {
    const socket = connectReady();
    let release: (v: unknown) => void = () => undefined;
    execute.mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
    socket.receive({ type: 'call', id: 'closing', tool: 'ui_get_selection', args: {} });
    socket.readyState = 2;
    release({ ok: true, data: {} });
    await vi.advanceTimersByTimeAsync(0);
    expect(socket.sent.filter(f => f['type'] === 'result')).toEqual([]);
  });

  it('swallows a send that throws after the OPEN check, so the answer promise resolves', async () => {
    const socket = connectReady();
    const send = vi.fn(() => { throw new Error('InvalidStateError'); });
    socket.send = send;
    const answer = (bridge as unknown as { answer: (call: unknown) => Promise<void> }).answer.bind(bridge);
    await expect(answer({ type: 'call', id: 'racing', tool: 'ui_get_selection', args: {} })).resolves.toBeUndefined();
    expect(send).toHaveBeenCalledTimes(1);
  });

  it('answers upstream_error when the result cannot be serialised', async () => {
    execute.mockResolvedValueOnce({ ok: true, data: { big: BigInt(1) } });
    const socket = connectReady();
    socket.receive({ type: 'call', id: 'bi', tool: 'ui_get_selection', args: {} });
    await vi.advanceTimersByTimeAsync(0);
    expect(socket.sent.at(-1)).toMatchObject({ type: 'result', id: 'bi', ok: false, error: 'upstream_error' });
  });

  it('ignores malformed, non-string and id-less-typed frames without answering', async () => {
    const socket = connectReady();
    const before = socket.sent.length;
    socket.onmessage?.({ data: 'not json' });
    socket.onmessage?.({ data: 42 });
    socket.onmessage?.({ data: new ArrayBuffer(4) });
    socket.receive({ type: 'call', id: 5, tool: 'ui_get_selection', args: {} });
    socket.receive({ type: 'nonsense' });
    await vi.advanceTimersByTimeAsync(0);
    expect(execute).not.toHaveBeenCalled();
    expect(socket.sent).toHaveLength(before);
  });

  describe('auth frame limits and a failing socket factory', () => {
    const rebuild = (factory: (url: string) => FakeSocket, url: string, toolNames: string[]): void => {
      TestBed.resetTestingModule();
      FakeSocket.instances = [];
      TestBed.configureTestingModule({
        providers: [
          { provide: BRIDGE_SOCKET_FACTORY, useValue: factory },
          { provide: AuthService, useValue: { status: signal(status()), get token() { return token; }, loginPasswordRequired: () => loginRequired } },
          { provide: Router, useValue: { url, events: routerEvents } },
          { provide: WebMcpToolRegistry, useValue: { toolNames, toolsVersion: 'v1', execute, ready: signal(true), load: () => Promise.resolve() } },
        ],
      });
      bridge = TestBed.inject(AgentBridgeService);
      settle();
    };

    it('truncates the route to 200 characters and the tool list to 64 names', () => {
      rebuild(url => new FakeSocket(url), '/' + 'r'.repeat(400), Array.from({ length: 70 }, (_, i) => `tool_${i}`));
      const socket = last();
      socket.open();
      expect((socket.sent[0]['route'] as string).length).toBe(200);
      expect((socket.sent[0]['tools'] as string[]).length).toBe(64);
    });

    it('reconnects after the factory throws, instead of giving up', async () => {
      let calls = 0;
      rebuild(url => {
        calls += 1;
        if (calls === 1) throw new Error('blocked');
        return new FakeSocket(url);
      }, '/', []);
      expect(FakeSocket.instances).toHaveLength(0);
      await vi.advanceTimersByTimeAsync(1000);
      expect(FakeSocket.instances).toHaveLength(1);
    });
  });

  it('sends an error result with only the code and message', async () => {
    execute.mockResolvedValueOnce({ ok: false, error: 'no_active_view', message: 'nothing here' });
    const socket = connectReady();
    socket.receive({ type: 'call', id: 'e1', tool: 'ui_next_page', args: {} });
    await vi.advanceTimersByTimeAsync(0);
    expect(socket.sent.at(-1)).toEqual({ type: 'result', id: 'e1', ok: false, error: 'no_active_view', message: 'nothing here' });
  });

  it('turns an oversized result into too_large', async () => {
    execute.mockResolvedValueOnce({ ok: true, data: 'x'.repeat(300 * 1024) });
    const socket = connectReady();
    socket.receive({ type: 'call', id: 'big', tool: 'ui_get_gallery_view', args: {} });
    await vi.advanceTimersByTimeAsync(0);
    expect(socket.sent.at(-1)).toMatchObject({ type: 'result', id: 'big', ok: false, error: 'too_large' });
  });

  it('answers ping with pong', () => {
    const socket = connectReady();
    socket.receive({ type: 'ping' });
    expect(socket.sent.at(-1)).toEqual({ type: 'pong' });
  });

  it('sends state frames on NavigationEnd, focus, blur and visibility change', () => {
    const socket = connectReady();
    const before = socket.sent.length;
    routerEvents.next(new NavigationEnd(1, '/stats', '/stats'));
    window.dispatchEvent(new Event('focus'));
    window.dispatchEvent(new Event('blur'));
    document.dispatchEvent(new Event('visibilitychange'));
    const states = socket.sent.slice(before);
    expect(states).toHaveLength(4);
    for (const frame of states) expect(frame).toMatchObject({ type: 'state', route: '/persons?x=1' });
  });

  it('does not send state before the server said ready', () => {
    const socket = last();
    socket.open();
    const before = socket.sent.length;
    window.dispatchEvent(new Event('focus'));
    expect(socket.sent).toHaveLength(before);
  });

  describe('close codes', () => {
    it('4401 stops reconnecting until a new login brings a different token', () => {
      const socket = connectReady();
      socket.serverClose(4401);
      expect(bridge.status()).toBe('blocked');
      vi.advanceTimersByTime(BACKOFF_MAX_MS * 3);
      expect(FakeSocket.instances).toHaveLength(1);
      authStatus.set(status());
      settle();
      expect(FakeSocket.instances).toHaveLength(1);
      token = 'jwt-2';
      authStatus.set(status());
      settle();
      expect(FakeSocket.instances).toHaveLength(2);
    });

    it('4401 on an open install with a leftover JWT retries once with a null token, then blocks', () => {
      loginRequired = false;
      authStatus.set(status({ multi_user: false, login_password_required: false }));
      settle();
      last().open();
      last().serverClose(4401);
      expect(FakeSocket.instances).toHaveLength(2);
      last().open();
      expect(last().sent[0]).toMatchObject({ type: 'auth', token: null });
      last().serverClose(4401);
      vi.advanceTimersByTime(BACKOFF_MAX_MS * 3);
      expect(FakeSocket.instances).toHaveLength(2);
      expect(bridge.status()).toBe('blocked');
    });

    it('4401 on a multi-user install blocks at once: the null token only opens an install with no accounts', () => {
      // The server reports login_password_required=false for a multi-user install (the flag is single-password only).
      loginRequired = false;
      last().open();
      last().serverClose(4401);
      expect(FakeSocket.instances).toHaveLength(1);
      expect(bridge.status()).toBe('blocked');
    });

    it('does not dial with a null token on a multi-user install', () => {
      TestBed.resetTestingModule();
      FakeSocket.instances = [];
      TestBed.configureTestingModule({
        providers: [
          { provide: BRIDGE_SOCKET_FACTORY, useValue: (url: string) => new FakeSocket(url) },
          { provide: AuthService, useValue: { status: signal(status({ multi_user: true, login_password_required: false })), token: null, loginPasswordRequired: () => false } },
          { provide: Router, useValue: { url: '/', events: routerEvents } },
          { provide: WebMcpToolRegistry, useValue: { toolNames: [], toolsVersion: 'v1', execute, ready: signal(true), load: () => Promise.resolve() } },
        ],
      });
      TestBed.inject(AgentBridgeService);
      settle();
      expect(FakeSocket.instances).toHaveLength(0);
    });

    it('4401 on the very first connection also blocks reconnects', () => {
      last().open();
      last().serverClose(4401);
      vi.advanceTimersByTime(BACKOFF_MAX_MS * 3);
      expect(FakeSocket.instances).toHaveLength(1);
    });

    it('4408 and 1006 reconnect with doubling backoff capped at 30 s, reset by ready', () => {
      let socket = connectReady();
      socket.serverClose(4408);
      vi.advanceTimersByTime(999);
      expect(FakeSocket.instances).toHaveLength(1);
      vi.advanceTimersByTime(1);
      expect(FakeSocket.instances).toHaveLength(2);
      last().serverClose(1006);
      vi.advanceTimersByTime(1999);
      expect(FakeSocket.instances).toHaveLength(2);
      vi.advanceTimersByTime(1);
      expect(FakeSocket.instances).toHaveLength(3);
      for (let i = 0; i < 8; i++) {
        last().serverClose(1006);
        vi.advanceTimersByTime(BACKOFF_MAX_MS);
      }
      const before = FakeSocket.instances.length;
      last().serverClose(1006);
      vi.advanceTimersByTime(BACKOFF_MAX_MS - 1);
      expect(FakeSocket.instances).toHaveLength(before);
      vi.advanceTimersByTime(1);
      expect(FakeSocket.instances).toHaveLength(before + 1);
      socket = connectReady();
      socket.serverClose(1006);
      vi.advanceTimersByTime(1000);
      expect(FakeSocket.instances).toHaveLength(before + 2);
    });

    it('4409 does not reconnect on a timer, however long it waits', () => {
      connectReady().serverClose(4409);
      vi.advanceTimersByTime(BACKOFF_MAX_MS * 4);
      expect(FakeSocket.instances).toHaveLength(1);
      expect(bridge.status()).toBe('disconnected');
    });

    it('4409 reconnects only when the user returns to the tab after the cooldown', () => {
      connectReady().serverClose(4409);
      vi.spyOn(document, 'hasFocus').mockReturnValue(true);
      vi.advanceTimersByTime(5000);
      window.dispatchEvent(new Event('focus'));
      expect(FakeSocket.instances).toHaveLength(1);
      vi.advanceTimersByTime(SUPERSEDED_COOLDOWN_MS);
      window.dispatchEvent(new Event('focus'));
      expect(FakeSocket.instances).toHaveLength(2);
    });

    it.each([4400, 4403, 4404])('%i does not retry', code => {
      last().open();
      last().serverClose(code);
      expect(bridge.status()).toBe('blocked');
      vi.advanceTimersByTime(BACKOFF_MAX_MS * 3);
      expect(FakeSocket.instances).toHaveLength(1);
    });
  });

  it('lifts a 4404 block when the server later reports the bridge on again', () => {
    last().open();
    last().serverClose(4404);
    expect(bridge.status()).toBe('blocked');
    authStatus.set(status({ features: { mcp: true, mcp_bridge: false } }));
    settle();
    authStatus.set(status());
    settle();
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it('closes the socket on logout and does not reconnect', () => {
    const socket = connectReady();
    authStatus.set(null);
    settle();
    expect(socket.closedWith).toBe(1000);
    expect(bridge.status()).toBe('disconnected');
    vi.advanceTimersByTime(BACKOFF_MAX_MS * 3);
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it('closes when the feature turns off and reconnects when it comes back', () => {
    const socket = connectReady();
    authStatus.set(status({ features: { mcp: false, mcp_bridge: false } }));
    settle();
    expect(socket.closedWith).toBe(1000);
    authStatus.set(status());
    settle();
    expect(FakeSocket.instances).toHaveLength(2);
  });

  it('reconnects with the new token after the session JWT rotates', () => {
    const socket = connectReady();
    token = 'jwt-edition';
    authStatus.set(status({ edition_authenticated: true }));
    settle();
    expect(socket.closedWith).toBe(1000);
    expect(FakeSocket.instances).toHaveLength(2);
    last().open();
    expect(last().sent[0]).toMatchObject({ type: 'auth', token: 'jwt-edition' });
  });

  it('a status refresh with an unchanged token keeps the same connection', () => {
    connectReady();
    authStatus.set(status());
    settle();
    expect(FakeSocket.instances).toHaveLength(1);
  });
});
