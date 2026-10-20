import type { Mock } from 'vitest';
import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { AuthService, AuthStatus } from '../services/auth.service';
import { AgentWebMcpService, IS_SECURE_CONTEXT, WEBMCP_POLYFILL_LOADER } from './agent-web-mcp.service';
import { UiToolDefinition, WebMcpToolRegistry } from './webmcp-registry.service';
import contractFile from './ui-tools.schema.json';
import { UiToolContractFile } from './ui-tool.types';

interface RegisteredTool {
  name: string;
  annotations?: { readOnlyHint?: boolean; untrustedContentHint?: boolean };
  execute: (args: unknown, client: unknown) => unknown;
}

function status(overrides: Partial<AuthStatus> = {}): AuthStatus {
  return {
    authenticated: true, multi_user: false, edition_enabled: false, edition_authenticated: false,
    edition_password_required: false, login_password_required: true, user_id: null, user_role: null,
    display_name: null, features: { mcp: true }, download_profiles: [], ...overrides,
  };
}

function tool(name: string, readOnly: boolean, untrusted: boolean): UiToolDefinition {
  return {
    name, description: `${name} desc`, inputSchema: { type: 'object', properties: {} },
    annotations: { readOnlyHint: readOnly, untrustedContentHint: untrusted },
    execute: vi.fn(async () => ({ ok: true as const, data: { name } })),
  };
}

describe('AgentWebMcpService', () => {
  let authStatus: ReturnType<typeof signal<AuthStatus | null>>;
  let live: Map<string, RegisteredTool>;
  let registerTool: Mock;
  let installWebMCP: Mock;
  let loader: Mock;
  let secure: boolean;
  let resolveLoad: (() => void) | null;
  let service: AgentWebMcpService;

  const settle = async (): Promise<void> => {
    TestBed.tick();
    await new Promise(resolve => setTimeout(resolve, 0));
    await new Promise(resolve => setTimeout(resolve, 0));
  };

  beforeEach(() => {
    live = new Map();
    registerTool = vi.fn((registered: RegisteredTool, options?: { signal?: AbortSignal }) => {
      if (live.has(registered.name)) throw new DOMException('duplicate', 'InvalidStateError');
      live.set(registered.name, registered);
      options?.signal?.addEventListener('abort', () => live.delete(registered.name));
      return Promise.resolve();
    });
    installWebMCP = vi.fn(() => {
      Object.defineProperty(document, 'modelContext', { value: { registerTool }, configurable: true });
    });
    resolveLoad = null;
    loader = vi.fn(() => new Promise(resolve => {
      resolveLoad = () => resolve({ installWebMCP });
      resolveLoad();
    }));
    secure = true;
    authStatus = signal<AuthStatus | null>(status());
    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: { status: authStatus } },
        { provide: WEBMCP_POLYFILL_LOADER, useValue: loader },
        { provide: IS_SECURE_CONTEXT, useValue: () => secure },
        {
          provide: WebMcpToolRegistry,
          useValue: { tools: [tool('ui_get_selection', true, true), tool('ui_navigate', false, false)], ready: signal(true), load: () => Promise.resolve() },
        },
      ],
    });
    service = TestBed.inject(AgentWebMcpService);
  });

  afterEach(() => {
    Reflect.deleteProperty(document, 'modelContext');
    TestBed.resetTestingModule();
  });

  it('registers every tool after the polyfill installed, with the contract hints', async () => {
    await settle();
    expect(installWebMCP).toHaveBeenCalledTimes(1);
    expect(registerTool).toHaveBeenCalledTimes(2);
    expect(installWebMCP.mock.invocationCallOrder[0]).toBeLessThan(registerTool.mock.invocationCallOrder[0]);
    expect(service.state()).toBe('active');
    expect(live.get('ui_get_selection')?.annotations).toEqual({ readOnlyHint: true, untrustedContentHint: true });
    expect(live.get('ui_navigate')?.annotations).toEqual({ readOnlyHint: false, untrustedContentHint: false });
  });

  it('declares every tool of the generated contract in-page, ui_get_context included', async () => {
    TestBed.resetTestingModule();
    live.clear();
    const contract = contractFile as unknown as UiToolContractFile;
    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: { status: signal(status()) } },
        { provide: WEBMCP_POLYFILL_LOADER, useValue: loader },
        { provide: IS_SECURE_CONTEXT, useValue: () => true },
        {
          provide: WebMcpToolRegistry,
          useValue: { tools: contract.tools.map(t => tool(t.name, t.annotations.readOnlyHint, t.annotations.untrustedContentHint)), ready: signal(true), load: () => Promise.resolve() },
        },
      ],
    });
    TestBed.inject(AgentWebMcpService);
    await settle();
    expect([...live.keys()].sort()).toEqual(contract.tools.map(t => t.name).sort());
    expect(live.has('ui_get_context')).toBe(true);
  });

  it('runs a tool through the registry envelope', async () => {
    await settle();
    const result = await live.get('ui_navigate')?.execute({}, {});
    expect(JSON.parse(result as string)).toEqual({ ok: true, data: { name: 'ui_navigate' } });
  });

  it('registers nothing and never loads the polyfill when the feature flag is off', async () => {
    TestBed.resetTestingModule();
    loader.mockClear();
    registerTool.mockClear();
    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: { status: signal(status({ features: { mcp: false } })) } },
        { provide: WEBMCP_POLYFILL_LOADER, useValue: loader },
        { provide: IS_SECURE_CONTEXT, useValue: () => true },
        { provide: WebMcpToolRegistry, useValue: { tools: [tool('ui_navigate', false, false)], ready: signal(true), load: () => Promise.resolve() } },
      ],
    });
    TestBed.inject(AgentWebMcpService);
    await settle();
    expect(loader).not.toHaveBeenCalled();
    expect(registerTool).not.toHaveBeenCalled();
  });

  it('skips everything outside a secure context and says why', async () => {
    TestBed.resetTestingModule();
    loader.mockClear();
    secure = false;
    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: { status: signal(status()) } },
        { provide: WEBMCP_POLYFILL_LOADER, useValue: loader },
        { provide: IS_SECURE_CONTEXT, useValue: () => secure },
        { provide: WebMcpToolRegistry, useValue: { tools: [tool('ui_navigate', false, false)], ready: signal(true), load: () => Promise.resolve() } },
      ],
    });
    const insecure = TestBed.inject(AgentWebMcpService);
    await settle();
    expect(loader).not.toHaveBeenCalled();
    expect(registerTool).not.toHaveBeenCalled();
    expect(insecure.state()).toBe('insecure_context');
  });

  it('unregisters every tool on logout, and a re-login registers again without InvalidStateError', async () => {
    await settle();
    expect(live.size).toBe(2);
    authStatus.set(null);
    await settle();
    expect(live.size).toBe(0);
    expect(service.state()).toBe('off');
    authStatus.set(status());
    await settle();
    expect(live.size).toBe(2);
    expect(registerTool).toHaveBeenCalledTimes(4);
  });

  it('goes back to off and registers nothing when the polyfill fails to load', async () => {
    TestBed.resetTestingModule();
    registerTool.mockClear();
    const failing = vi.fn(() => Promise.reject(new Error('chunk failed')));
    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: { status: signal<AuthStatus | null>(status()) } },
        { provide: WEBMCP_POLYFILL_LOADER, useValue: failing },
        { provide: IS_SECURE_CONTEXT, useValue: () => true },
        { provide: WebMcpToolRegistry, useValue: { tools: [tool('ui_navigate', false, false)], ready: signal(true), load: () => Promise.resolve() } },
      ],
    });
    const failed = TestBed.inject(AgentWebMcpService);
    await settle();
    expect(failing).toHaveBeenCalled();
    expect(failed.state()).toBe('off');
    expect(failed.sessionInjector()).toBeNull();
    expect(registerTool).not.toHaveBeenCalled();
  });

  it('exposes the session injector while active and clears it after logout', async () => {
    await settle();
    expect(service.sessionInjector()).not.toBeNull();
    authStatus.set(null);
    await settle();
    expect(service.sessionInjector()).toBeNull();
  });

  it('unregisters every tool when the app is destroyed', async () => {
    await settle();
    expect(live.size).toBe(2);
    TestBed.resetTestingModule();
    expect(live.size).toBe(0);
  });

  it('unregisters when the feature turns off', async () => {
    await settle();
    authStatus.set(status({ features: { mcp: false } }));
    await settle();
    expect(live.size).toBe(0);
  });

  it('does not register if the user logs out while the polyfill chunk is loading', async () => {
    TestBed.resetTestingModule();
    registerTool.mockClear();
    let release: () => void = () => undefined;
    const slowLoader = vi.fn(() => new Promise<{ installWebMCP: () => void }>(resolve => {
      release = () => resolve({ installWebMCP });
    }));
    const st = signal<AuthStatus | null>(status());
    TestBed.configureTestingModule({
      providers: [
        { provide: AuthService, useValue: { status: st } },
        { provide: WEBMCP_POLYFILL_LOADER, useValue: slowLoader },
        { provide: IS_SECURE_CONTEXT, useValue: () => true },
        { provide: WebMcpToolRegistry, useValue: { tools: [tool('ui_navigate', false, false)], ready: signal(true), load: () => Promise.resolve() } },
      ],
    });
    TestBed.inject(AgentWebMcpService);
    TestBed.tick();
    st.set(null);
    TestBed.tick();
    release();
    await settle();
    expect(registerTool).not.toHaveBeenCalled();
  });
});
