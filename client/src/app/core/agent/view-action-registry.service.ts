import { Injectable } from '@angular/core';
import { UiToolHandler } from './ui-tool.types';

/**
 * Root registry for UI-tool actions that only a mounted, route-scoped view can
 * perform (today: the darkroom's `ui_show_culling_group`). The view registers a
 * handler on init and removes it through its `DestroyRef`; while nothing is
 * registered the tool answers `no_active_view`.
 */
@Injectable({ providedIn: 'root' })
export class ViewActionRegistry {
  private readonly actions = new Map<string, UiToolHandler>();

  /** Register `handler` for `name`; the returned function removes it (only if it is still the registered one). */
  register(name: string, handler: UiToolHandler): () => void {
    this.actions.set(name, handler);
    return () => {
      if (this.actions.get(name) === handler) this.actions.delete(name);
    };
  }

  get(name: string): UiToolHandler | undefined {
    return this.actions.get(name);
  }
}
