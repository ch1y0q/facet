import { InjectionToken, Signal } from '@angular/core';
import { Observable } from 'rxjs';

/** A secondary editor shares explicit exclusions with its original, authorized proposal. */
export interface StackReviewDraft {
  excluded: Signal<ReadonlySet<string>>;
  current: () => boolean;
  exclude: (path: string) => () => void;
  lock: () => boolean;
  unlock: () => void;
}
export interface StackEditorData {
  stackId?: string;
  paths?: string[];
  activePath?: string | null;
  reviewDraft?: StackReviewDraft;
  /** Explicit selection only; never materialize a whole-view selection. */
  selectedPaths?: string[];
  skippable?: boolean;
  /** Captured by the commit, independent of the editor view's lifetime. */
  onUndone?: () => void;
}
export const SKIP_SUGGESTION = 'skip';
export interface StackEditorHost {
  readonly data: StackEditorData;
  readonly presentation: 'dialog' | 'page';
  readonly keydown$: Observable<KeyboardEvent>;
  readonly closing$: Observable<unknown>;
  readonly onUndone?: () => void;
  setBusy(busy: boolean): void;
  finish(result: 'saved' | 'skip' | 'close'): void;
  invalidate(): void;
}
export const STACK_EDITOR_HOST = new InjectionToken<StackEditorHost>('StackEditorHost');
