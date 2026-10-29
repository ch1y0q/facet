import { InjectionToken } from '@angular/core';
import { Observable } from 'rxjs';

export interface StackEditorData {
  stackId?: string;
  paths?: string[];
  activePath?: string | null;
  /** Explicit selection only; never materialize a whole-view selection. */
  selectedPaths?: string[];
  skippable?: boolean;
}
export const SKIP_SUGGESTION = 'skip';
export interface StackEditorHost {
  readonly data: StackEditorData;
  readonly presentation: 'dialog' | 'page';
  readonly keydown$: Observable<KeyboardEvent>;
  readonly closing$: Observable<unknown>;
  /** Captured by the commit, independent of the editor view's lifetime. */
  readonly onUndone?: () => void;
  setBusy(busy: boolean): void;
  finish(result: 'saved' | 'skip' | 'close'): void;
  invalidate(): void;
}
export const STACK_EDITOR_HOST = new InjectionToken<StackEditorHost>('StackEditorHost');
