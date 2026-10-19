import { DestroyRef, Injectable, InjectionToken, computed, effect, inject, signal, untracked } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';
import { WebMcpToolRegistry } from './webmcp-registry.service';
import { UiToolEnvelope } from './ui-tool.types';

/** Minimal socket surface the bridge uses; the browser `WebSocket` satisfies it, tests pass a fake. */
export interface BridgeSocket {
  onopen: ((event: unknown) => void) | null;
  onmessage: ((event: { data: unknown }) => void) | null;
  onclose: ((event: { code: number }) => void) | null;
  onerror: ((event: unknown) => void) | null;
  /** Standard `WebSocket.readyState` (1 = OPEN); absent on a minimal fake. */
  readonly readyState?: number;
  send(data: string): void;
  close(code?: number): void;
}

export const BRIDGE_SOCKET_FACTORY = new InjectionToken<(url: string) => BridgeSocket>('BRIDGE_SOCKET_FACTORY', {
  providedIn: 'root',
  factory: () => (url: string) => new WebSocket(url) as unknown as BridgeSocket,
});

export type BridgeStatus = 'disconnected' | 'connecting' | 'connected' | 'blocked';

/** Close codes from the bridge protocol (server -> tab). */
export const BRIDGE_CLOSE = {
  BAD_FRAME: 4400,
  AUTH_FAILED: 4401,
  ORIGIN_REFUSED: 4403,
  DISABLED: 4404,
  IDLE: 4408,
  SUPERSEDED: 4409,
} as const;

export const BACKOFF_START_MS = 1000;
export const BACKOFF_MAX_MS = 30_000;
/** A superseded tab waits at least this long, and for the user to come back to it, before taking its slot again. */
export const SUPERSEDED_COOLDOWN_MS = 30_000;
const ROUTE_MAX = 200;
/** `WebSocket.OPEN`. */
const OPEN = 1;
const MAX_TOOLS = 64;
/** The server turns a result frame above 256 KiB into `too_large`; stay under it. */
const RESULT_FRAME_LIMIT = 250 * 1024;

function newTabId(): string {
  const bytes = new Uint8Array(12);
  crypto.getRandomValues(bytes);
  return Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
}

interface CallFrame {
  type: 'call';
  id: string;
  tool: string;
  args?: unknown;
}

/**
 * Tab side of the agent bridge (`/api/mcp/bridge`). It opens the socket only
 * while the user is signed in and `features.mcp` is on, authenticates in the
 * first frame (never in the URL), answers `call` frames through the registry,
 * and reports the tab's route and focus so the server can pick the right tab.
 */
@Injectable({ providedIn: 'root' })
export class AgentBridgeService {
  private readonly auth = inject(AuthService);
  private readonly router = inject(Router);
  private readonly registry = inject(WebMcpToolRegistry);
  private readonly socketFactory = inject(BRIDGE_SOCKET_FACTORY);

  /** Fresh per page load: a reload that reused the id would be seen as a second connection of the same tab (4409). */
  readonly tabId = newTabId();
  readonly status = signal<BridgeStatus>('disconnected');
  readonly connected = computed(() => this.status() === 'connected');

  private socket: BridgeSocket | null = null;
  private connectedToken: string | null | undefined;
  private attempt = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  /** Why we stopped, so a change of credentials (not just any status refresh) is what lifts it. */
  private block: { reason: 'auth' | 'closed'; token: string | null } | null = null;
  private supersededAt: number | null = null;

  constructor() {
    effect(() => {
      const wanted = this.wanted();
      untracked(() => this.reconcile(wanted));
    });
    this.router.events.subscribe(event => {
      if (event instanceof NavigationEnd) this.sendState();
    });
    const onActivity = () => {
      this.sendState();
      this.resumeAfterSupersede();
    };
    document.addEventListener('visibilitychange', onActivity);
    window.addEventListener('focus', onActivity);
    window.addEventListener('blur', onActivity);
    inject(DestroyRef).onDestroy(() => {
      document.removeEventListener('visibilitychange', onActivity);
      window.removeEventListener('focus', onActivity);
      window.removeEventListener('blur', onActivity);
      this.disconnect('disconnected');
    });
  }

  /** Set after an open install rejected a leftover JWT from an earlier password-protected life of the same browser profile. */
  private openInstallNullToken = false;

  private currentToken(): string | null {
    return this.openInstallNullToken ? null : this.auth.token;
  }

  /** A password install with no live token cannot authenticate; an open install legitimately sends `null`. */
  private canAuthenticate(): boolean {
    return this.currentToken() !== null || !this.auth.loginPasswordRequired();
  }

  /**
   * Signed in, the server serves the bridge (`features.mcp_bridge`: the agent feature on AND the
   * bridge switch on, so a bridge-off install is never dialled) and the contract has loaded.
   * Reading the contract's readiness here also starts its lazy load for a session that wants it.
   */
  private wanted(): boolean {
    const status = this.auth.status();
    const enabled = !!status?.authenticated && status.features['mcp_bridge'] === true;
    if (enabled && !this.registry.ready()) untracked(() => void this.registry.load());
    return enabled && this.registry.ready();
  }

  private reconcile(wanted: boolean): void {
    if (!wanted) {
      this.openInstallNullToken = false;
      this.block = null;
      this.supersededAt = null;
      this.disconnect('disconnected');
      return;
    }
    const token = this.currentToken();
    if (this.block?.reason === 'auth' && token !== this.block.token) this.block = null;
    if (this.block) return;
    if (!this.canAuthenticate()) {
      this.disconnect('disconnected');
      return;
    }
    if (this.socket && this.connectedToken !== token) {
      // The session JWT rotated (login, edition grant or drop): the old connection will be 4401'd at its next ping.
      this.disconnect('disconnected');
    }
    if (!this.socket && this.retryTimer === null && this.supersededAt === null) this.connect();
  }

  private connect(): void {
    this.clearRetry();
    const token = this.currentToken();
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    let socket: BridgeSocket;
    try {
      socket = this.socketFactory(`${scheme}://${location.host}/api/mcp/bridge`);
    } catch {
      this.scheduleReconnect();
      return;
    }
    this.socket = socket;
    this.connectedToken = token;
    this.status.set('connecting');
    socket.onopen = () => {
      if (this.socket !== socket) return;
      this.sendRaw({
        type: 'auth',
        token,
        tab_id: this.tabId,
        route: this.routeForServer(),
        focused: this.isFocused(),
        tools: this.registry.toolNames.slice(0, MAX_TOOLS),
        tools_version: this.registry.toolsVersion,
      });
    };
    socket.onmessage = event => {
      if (this.socket === socket) this.onFrame(event.data);
    };
    socket.onclose = event => {
      if (this.socket === socket) this.onClosed(event.code);
    };
    socket.onerror = () => undefined;
  }

  private onFrame(data: unknown): void {
    if (typeof data !== 'string') return;
    let frame: { type?: string };
    try {
      frame = JSON.parse(data) as { type?: string };
    } catch {
      return;
    }
    switch (frame.type) {
      case 'ready':
        this.attempt = 0;
        this.status.set('connected');
        break;
      case 'ping':
        this.sendRaw({ type: 'pong' });
        break;
      case 'call':
        void this.answer(frame as CallFrame);
        break;
      default:
        break;
    }
  }

  private async answer(call: CallFrame): Promise<void> {
    if (typeof call.id !== 'string') return;
    // The socket that carried the call; a tool can outlive it (reconnect, sign-out), and its answer then belongs to nobody.
    const socket = this.socket;
    const envelope: UiToolEnvelope = await this.registry.execute(call.tool, call.args);
    const frame = envelope.ok
      ? { type: 'result', id: call.id, ok: true, data: envelope.data }
      : { type: 'result', id: call.id, ok: false, error: envelope.error, message: envelope.message.slice(0, 500) };
    let text: string;
    try {
      text = JSON.stringify(frame);
    } catch {
      text = JSON.stringify({ type: 'result', id: call.id, ok: false, error: 'upstream_error', message: 'The result could not be serialised.' });
    }
    if (text.length > RESULT_FRAME_LIMIT) {
      text = JSON.stringify({ type: 'result', id: call.id, ok: false, error: 'too_large', message: 'The result is too large to send; narrow the request.' });
    }
    if (!socket || this.socket !== socket || (socket.readyState !== undefined && socket.readyState !== OPEN)) return;
    try {
      socket.send(text);
    } catch {
      // The socket closed between the check and the send; the server times the call out on its own.
    }
  }

  private onClosed(code: number): void {
    this.socket = null;
    switch (code) {
      case BRIDGE_CLOSE.AUTH_FAILED:
        if (this.connectedToken !== null && !this.openInstallNullToken && !this.auth.loginPasswordRequired()) {
          // An open install accepts `null` but not a stale JWT: retry once as the anonymous principal.
          this.openInstallNullToken = true;
          this.status.set('disconnected');
          this.connect();
          return;
        }
        this.block = { reason: 'auth', token: this.connectedToken ?? null };
        this.status.set('blocked');
        return;
      case BRIDGE_CLOSE.BAD_FRAME:
      case BRIDGE_CLOSE.ORIGIN_REFUSED:
      case BRIDGE_CLOSE.DISABLED:
        // A client bug, a refused origin or a disabled feature: retrying cannot fix any of them.
        this.block = { reason: 'closed', token: this.connectedToken ?? null };
        this.status.set('blocked');
        return;
      case BRIDGE_CLOSE.SUPERSEDED:
        // Reconnecting at once would evict whichever tab replaced us; wait for the user to return to this one.
        this.supersededAt = Date.now();
        this.status.set('disconnected');
        return;
      default:
        this.status.set('disconnected');
        this.scheduleReconnect();
    }
  }

  private scheduleReconnect(): void {
    this.clearRetry();
    const delayMs = Math.min(BACKOFF_MAX_MS, BACKOFF_START_MS * 2 ** this.attempt);
    this.attempt += 1;
    this.retryTimer = setTimeout(() => {
      this.retryTimer = null;
      if (this.wanted() && !this.block && this.canAuthenticate()) this.connect();
    }, delayMs);
  }

  private resumeAfterSupersede(): void {
    if (this.supersededAt === null || !this.isFocused()) return;
    if (Date.now() - this.supersededAt < SUPERSEDED_COOLDOWN_MS) return;
    this.supersededAt = null;
    this.reconcile(this.wanted());
  }

  private clearRetry(): void {
    if (this.retryTimer !== null) {
      clearTimeout(this.retryTimer);
      this.retryTimer = null;
    }
  }

  private disconnect(next: BridgeStatus): void {
    this.clearRetry();
    this.attempt = 0;
    const socket = this.socket;
    this.socket = null;
    if (socket) {
      socket.onclose = null;
      socket.onmessage = null;
      try {
        socket.close(1000);
      } catch {
        // already closed
      }
    }
    this.status.set(next);
  }

  private routeForServer(): string {
    return (this.router.url || '/').slice(0, ROUTE_MAX);
  }

  private isFocused(): boolean {
    return document.visibilityState === 'visible' && document.hasFocus();
  }

  private sendState(): void {
    if (this.status() !== 'connected') return;
    this.sendRaw({ type: 'state', route: this.routeForServer(), focused: this.isFocused() });
  }

  private sendRaw(frame: Record<string, unknown>): void {
    this.socket?.send(JSON.stringify(frame));
  }
}
