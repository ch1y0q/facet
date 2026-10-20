import {
  EnvironmentInjector,
  Injectable,
  computed,
  createEnvironmentInjector,
  declareExperimentalWebMcpTool,
  effect,
  inject,
  signal,
  untracked,
} from '@angular/core';
import { HttpClient, HttpHeaders } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { McpCallRequest, McpCallResponse, McpInpageLevel, McpInpageTool, McpInpageTools } from '../api/types';
import { AgentWebMcpService } from './agent-web-mcp.service';
import { InpageChangeNotifier } from './inpage-change-notifier.service';
import { WebMcpToolRegistry } from './webmcp-registry.service';

type WebMcpDescriptor = Parameters<typeof declareExperimentalWebMcpTool>[0];

export const INPAGE_OPT_IN_KEY = 'facet_agent_inpage_tools';
export const SESSION_HEADER = 'X-Facet-Agent-Session';
const TIERS: readonly McpInpageLevel[] = ['readonly', 'user', 'edition'];
const STRIPPED_ARGS = ['tab_id'] as const;

function readOptIn(): boolean {
  try {
    return localStorage.getItem(INPAGE_OPT_IN_KEY) === '1';
  } catch {
    return false;
  }
}

/** The caller's level from the cached auth status: edition when unlocked, user for a signed-in multi-user account, else readonly. */
export function inpageLevel(status: { authenticated: boolean; multi_user: boolean; edition_authenticated: boolean } | null): McpInpageLevel | null {
  if (!status?.authenticated) return null;
  if (status.edition_authenticated) return 'edition';
  return status.multi_user ? 'user' : 'readonly';
}

/**
 * Registers the server's own read and write tools as in-page WebMCP tools, for a browser whose user
 * opted in. Each proxy POSTs `/api/mcp/call`, so there is one implementation of every tool, on the server.
 *
 * One child injector per level tier hangs off the session injector: unlocking edition adds the edition
 * child, locking destroys only it, and logout, the opt-in turning off or `features.mcp_inpage` going
 * false destroys all of them.
 */
@Injectable({ providedIn: 'root' })
export class ServerToolRegistry {
  private readonly auth = inject(AuthService);
  private readonly web = inject(AgentWebMcpService);
  private readonly ui = inject(WebMcpToolRegistry);
  private readonly http = inject(HttpClient);
  private readonly notifier = inject(InpageChangeNotifier);

  /** Per-browser opt-in, default off. */
  readonly optedIn = signal(readOptIn());
  /** Random per tab: it only isolates confirmation nonces between this user's sessions. */
  private readonly sessionId = crypto.randomUUID();
  private readonly children = new Map<McpInpageLevel, EnvironmentInjector>();
  private generation = 0;
  private parent: EnvironmentInjector | null = null;

  /** Level to register for, or null when nothing should load; re-evaluated only when this value changes. */
  private readonly plan = computed(() => {
    const status = this.auth.status();
    const wanted = !!status?.authenticated && status.features['mcp'] === true && status.features['mcp_inpage'] === true && this.optedIn();
    return wanted ? inpageLevel(status) : null;
  }, { equal: (a, b) => a === b });

  constructor() {
    effect(() => {
      const level = this.plan();
      const session = this.web.sessionInjector();
      untracked(() => void this.apply(session && level ? level : null, session));
    });
  }

  setOptIn(on: boolean): void {
    try {
      if (on) localStorage.setItem(INPAGE_OPT_IN_KEY, '1');
      else localStorage.removeItem(INPAGE_OPT_IN_KEY);
    } catch {
      // Storage may be blocked; the choice then lasts for this page only.
    }
    this.optedIn.set(on);
  }

  private async apply(level: McpInpageLevel | null, session: EnvironmentInjector | null): Promise<void> {
    const generation = ++this.generation;
    if (!level || !session) {
      this.destroyTiers(0);
      this.parent = null;
      return;
    }
    if (this.parent !== session) {
      this.destroyTiers(0);
      this.parent = session;
    }
    const rank = TIERS.indexOf(level);
    // Lock: only the tiers above the new level go.
    this.destroyTiers(rank + 1);
    const missing = TIERS.slice(0, rank + 1).filter(tier => !this.children.has(tier));
    if (!missing.length) return;
    let listing: McpInpageTools;
    try {
      listing = await firstValueFrom(this.http.get<McpInpageTools>('/api/mcp/inpage_tools'));
    } catch {
      return;
    }
    // Logout, a lock or the opt-in turning off may have landed during the fetch.
    if (generation !== this.generation) return;
    for (const tier of missing) {
      const child = createEnvironmentInjector([], session);
      this.children.set(tier, child);
      const tools = listing.tools.filter(tool => tool.required_level === tier);
      await Promise.allSettled(tools.map(tool => declareExperimentalWebMcpTool(this.descriptor(tool), child)));
    }
  }

  private destroyTiers(fromRank: number): void {
    for (const tier of TIERS.slice(fromRank)) {
      this.children.get(tier)?.destroy();
      this.children.delete(tier);
    }
  }

  private descriptor(tool: McpInpageTool): WebMcpDescriptor {
    const readOnly = tool.annotations.readOnlyHint === true;
    return {
      name: tool.name,
      description: tool.description,
      inputSchema: this.stripSchema(tool.inputSchema),
      annotations: {
        readOnlyHint: readOnly,
        ...(readOnly ? {} : { consequentialHint: true }),
        untrustedContentHint: true,
      },
      execute: (args: unknown) => this.call(tool, args),
    } as unknown as WebMcpDescriptor;
  }

  private stripSchema(schema: Record<string, unknown>): Record<string, unknown> {
    const properties = { ...(schema['properties'] as Record<string, unknown> | undefined) };
    for (const key of STRIPPED_ARGS) delete properties[key];
    const required = Array.isArray(schema['required']) ? (schema['required'] as string[]).filter(k => !STRIPPED_ARGS.includes(k as 'tab_id')) : undefined;
    return { ...schema, properties, ...(required ? { required } : {}) };
  }

  /**
   * The proxy call. Deliberately not tied to the injector's abort signal: a lock destroys the edition
   * child while a dry-run-then-confirm may be in flight, and cancelling it would strand the user's intent.
   */
  private async call(tool: McpInpageTool, args: unknown): Promise<string> {
    const input = { ...((args && typeof args === 'object' ? args : {}) as Record<string, unknown>) };
    for (const key of STRIPPED_ARGS) delete input[key];
    const body: McpCallRequest = { tool: tool.name, arguments: input };
    const properties = (tool.inputSchema['properties'] ?? {}) as Record<string, unknown>;
    if ('target' in properties && input['target'] === 'selection') {
      const selection = await this.ui.execute('ui_get_selection', {});
      if (!selection.ok) return JSON.stringify(selection);
      body.selection_snapshot = selection.data;
    }
    try {
      const response = await firstValueFrom(this.http.post<McpCallResponse>('/api/mcp/call', body, {
        headers: new HttpHeaders({ [SESSION_HEADER]: this.sessionId }),
      }));
      if (response.ok && tool.annotations.readOnlyHint !== true && response.changed) this.notifier.notify(response.changed, response.batch_id);
      return JSON.stringify(response);
    } catch (err) {
      // A 401 already reached the interceptor (logout); a 403 just reports, without ending the session.
      const status = (err as { status?: number }).status;
      const code = status === 403 ? 'forbidden_level' : 'upstream_error';
      return JSON.stringify({ ok: false, error: code, message: `The server refused the call (${status ?? 'network error'}).` });
    }
  }
}
