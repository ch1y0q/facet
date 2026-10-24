import { Injectable, inject, signal, untracked } from '@angular/core';
import { Router } from '@angular/router';
import { HttpBackend, HttpClient, HttpHeaders } from '@angular/common/http';
import { firstValueFrom } from 'rxjs';
import { AuthService } from '../services/auth.service';
import type { Album } from '../services/album.service';
import { GalleryStore } from '../../features/gallery/gallery.store';
import { CompareFiltersService } from '../../features/comparison/compare-filters.service';
import { validateAgainstSchema, withDefaults } from './schema-validate';
import { UserActivityJournal } from './user-activity-journal.service';
import { MODAL_OPEN_MESSAGE, createUiToolHandlers } from './ui-tool-handlers';
import { AssistantCullPlanService } from './assistant-cull-plan.service';
import { ViewActionRegistry } from './view-action-registry.service';
import { PageContextService } from './page-context.service';
import {
  UI_TOOL_ERROR_CODES,
  UiActionRow,
  UiToolContract,
  UiToolContractFile,
  UiToolEnvelope,
  UiToolError,
  UiToolHandler,
} from './ui-tool.types';

export interface UiToolDefinition extends UiToolContract {
  execute(args: unknown): Promise<UiToolEnvelope>;
}

/** Contract entries that have no handler, and handlers that have no contract entry. Both must be empty. */
export function contractHandlerMismatch(
  contract: readonly UiToolContract[],
  handlers: Record<string, UiToolHandler>,
): { missingHandlers: string[]; missingContract: string[] } {
  const names = new Set(contract.map(t => t.name));
  return {
    missingHandlers: contract.filter(t => !Object.hasOwn(handlers, t.name)).map(t => t.name),
    missingContract: Object.keys(handlers).filter(name => !names.has(name)),
  };
}

/**
 * The one lazy-load gate: starts the contract's load for a session that wants it, and says whether
 * it is both wanted and loaded. Reads `ready()` (so a caller inside an effect re-runs when it lands).
 */
export function contractReadyWhen(registry: Pick<WebMcpToolRegistry, 'ready' | 'load'>, enabled: boolean): boolean {
  if (enabled && !registry.ready()) untracked(() => void registry.load());
  return enabled && registry.ready();
}

/**
 * The single registry of UI tools: the generated server contract plus the
 * handler map. `execute` is the one path both consumers use (the tab bridge and
 * in-page WebMCP); it validates, runs the handler and returns the result
 * envelope. It never throws.
 */
@Injectable({ providedIn: 'root' })
export class WebMcpToolRegistry {
  /** True once the contract has loaded and `tools` is populated. */
  readonly ready = signal(false);
  toolsVersion = '';
  tools: readonly UiToolDefinition[] = [];
  /** The generated jobs table; `ui_get_context` reports the ones that apply. */
  actions: readonly UiActionRow[] = [];
  private readonly byName = new Map<string, UiToolDefinition>();
  // Interceptor-free: a refused probe is the tool's answer, not a toast, a logout check or a crash report.
  private readonly rawHttp = new HttpClient(inject(HttpBackend));
  private readonly auth = inject(AuthService);
  private readonly pageContext = inject(PageContextService);
  private readonly handlers = createUiToolHandlers({
    gallery: inject(GalleryStore),
    router: inject(Router),
    auth: this.auth,
    viewActions: inject(ViewActionRegistry),
    pageContext: this.pageContext,
    actions: () => this.actions,
    compareFilters: inject(CompareFiltersService),
    journal: inject(UserActivityJournal),
    plan: inject(AssistantCullPlanService),
    fetchAlbum: id => firstValueFrom(this.rawHttp.get<Album>(`/api/albums/${id}`, {
      headers: new HttpHeaders(this.auth.token ? { Authorization: `Bearer ${this.auth.token}` } : {}),
    })),
  });
  private readonly journal = inject(UserActivityJournal);
  private loading: Promise<void> | null = null;

  /**
   * Load the generated contract. A dynamic import, so its ~33 KB ships in a lazy
   * chunk fetched only for a session whose server has the agent feature on.
   */
  load(): Promise<void> {
    this.loading ??= import('./ui-tools.schema.json').then(module => {
      const contract = (module.default ?? module) as unknown as UiToolContractFile;
      this.toolsVersion = contract.version;
      this.actions = contract.actions;
      this.tools = contract.tools
        .filter(tool => Object.hasOwn(this.handlers, tool.name))
        .map(tool => ({ ...tool, execute: args => this.run(tool, this.handlers[tool.name], args) }));
      for (const tool of this.tools) this.byName.set(tool.name, tool);
      this.ready.set(true);
    }).catch(() => {
      this.loading = null;
    });
    return this.loading;
  }

  get toolNames(): string[] {
    return this.tools.map(t => t.name);
  }

  get(name: string): UiToolDefinition | undefined {
    return this.byName.get(name);
  }

  async execute(name: string, args: unknown): Promise<UiToolEnvelope> {
    const tool = this.byName.get(name);
    if (!tool) return { ok: false, error: 'not_found', message: `Unknown tool ${name}.` };
    return tool.execute(args);
  }

  private async run(tool: UiToolContract, handler: UiToolHandler, args: unknown): Promise<UiToolEnvelope> {
    try {
      const input = args === undefined || args === null ? {} : args;
      const issues = validateAgainstSchema(tool.inputSchema, input);
      if (issues.length) return { ok: false, error: 'invalid_input', message: issues.slice(0, 5).join('; ').slice(0, 500) };
      if (!tool.annotations.readOnlyHint && this.pageContext.overlays().length) {
        return { ok: false, error: 'modal_open', message: MODAL_OPEN_MESSAGE };
      }
      // The agent driving the tab is not the user: nothing it does is journaled as user activity.
      const data = await this.journal.suppress(() => handler(withDefaults(tool.inputSchema, input as Record<string, unknown>)));
      return { ok: true, data };
    } catch (err) {
      if (err instanceof UiToolError && UI_TOOL_ERROR_CODES.includes(err.code)) {
        return { ok: false, error: err.code, message: err.message.slice(0, 500) };
      }
      const message = err instanceof Error ? err.message : 'The tab failed to run the tool.';
      return { ok: false, error: 'upstream_error', message: message.slice(0, 500) };
    }
  }
}

