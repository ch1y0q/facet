import {
  DestroyRef,
  EnvironmentInjector,
  Injectable,
  InjectionToken,
  createEnvironmentInjector,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { AuthService } from '../services/auth.service';
import { WebMcpDescriptor, registerWebMcpTools, toWebMcpDescriptor } from './webmcp-descriptor';
import { UiToolDefinition, WebMcpToolRegistry, contractReadyWhen } from './webmcp-registry.service';

/** Loads the polyfill. A dynamic import, so its code ships in a lazy chunk and never in the main bundle. */
export const WEBMCP_POLYFILL_LOADER = new InjectionToken<() => Promise<{ installWebMCP: () => void }>>(
  'WEBMCP_POLYFILL_LOADER',
  { providedIn: 'root', factory: () => () => import('@mcp-b/webmcp-polyfill') },
);

/** The polyfill's `installWebMCP` does nothing outside a secure context, so the in-page tools are skipped there. */
export const IS_SECURE_CONTEXT = new InjectionToken<() => boolean>('IS_SECURE_CONTEXT', {
  providedIn: 'root',
  factory: () => () => window.isSecureContext,
});

export type WebMcpState = 'off' | 'insecure_context' | 'active';

/**
 * Exposes the UI-tool registry to in-page agents as W3C WebMCP tools.
 *
 * Registrations live on a per-session child `EnvironmentInjector`: destroying
 * it aborts every registration, so logging out (or the feature turning off)
 * unregisters the tools and a later login registers the same names again
 * without the `InvalidStateError` a long-lived root registration would raise.
 */
@Injectable({ providedIn: 'root' })
export class AgentWebMcpService {
  private readonly auth = inject(AuthService);
  private readonly registry = inject(WebMcpToolRegistry);
  private readonly root = inject(EnvironmentInjector);
  private readonly loadPolyfill = inject(WEBMCP_POLYFILL_LOADER);
  private readonly isSecureContext = inject(IS_SECURE_CONTEXT);

  readonly state = signal<WebMcpState>('off');
  /** The live session injector while tools are registered, so server-tool tiers can hang children off it. */
  readonly sessionInjector = signal<EnvironmentInjector | null>(null);

  private session: EnvironmentInjector | null = null;
  private generation = 0;

  constructor() {
    effect(() => {
      const status = this.auth.status();
      const enabled = !!status?.authenticated && status.features['mcp'] === true;
      // The contract is fetched only for a session that has the feature on.
      const wanted = contractReadyWhen(this.registry, enabled);
      untracked(() => {
        if (wanted) void this.start();
        else this.stop();
      });
    });
    inject(DestroyRef).onDestroy(() => this.stop());
  }

  private async start(): Promise<void> {
    if (this.session) return;
    if (!this.isSecureContext()) {
      this.state.set('insecure_context');
      return;
    }
    const generation = ++this.generation;
    try {
      const polyfill = await this.loadPolyfill();
      // A logout, or the feature turning off, may have landed while the chunk was loading.
      if (generation !== this.generation) return;
      polyfill.installWebMCP();
    } catch {
      if (generation === this.generation) this.state.set('off');
      return;
    }
    const session = createEnvironmentInjector([], this.root);
    this.session = session;
    this.state.set('active');
    this.sessionInjector.set(session);
    await registerWebMcpTools(this.registry.tools.map(tool => this.descriptor(tool)), session);
  }

  private stop(): void {
    this.generation += 1;
    const session = this.session;
    this.session = null;
    this.state.set('off');
    this.sessionInjector.set(null);
    session?.destroy();
  }

  private descriptor(tool: UiToolDefinition): WebMcpDescriptor {
    return toWebMcpDescriptor({
      name: tool.name,
      description: tool.description,
      inputSchema: tool.inputSchema,
      annotations: {
        readOnlyHint: tool.annotations.readOnlyHint,
        untrustedContentHint: tool.annotations.untrustedContentHint,
      },
      execute: async (args: unknown) => JSON.stringify(await tool.execute(args)),
    });
  }
}
