import { DestroyRef, Injectable, inject } from '@angular/core';
import { MatBottomSheet } from '@angular/material/bottom-sheet';
import { MatDialog } from '@angular/material/dialog';

/** Id the connect-assistant dialog opens with, so the overlay check can recognise it without importing the lazily loaded component. */
export const CONNECT_ASSISTANT_DIALOG_ID = 'connect-assistant-dialog';

export type PageContextValue = string | number | boolean | null;
export type PageContextReader = () => Record<string, unknown>;
export type OverlayKind = 'dialog' | 'bottom_sheet' | 'slideshow';

/** Free-text fields are cut here; path fields are never cut. */
const MAX_TEXT_LENGTH = 200;
const isPathField = (key: string): boolean => key === 'pair_a' || key === 'pair_b' || key.endsWith('_path');

/**
 * Root registry of what the open page shows (`ui_get_context.page`) and of the modal surfaces covering it
 * (`ui_get_context.overlays`, the `modal_open` refusal). A mounted page registers a reader of its filter
 * state and removes it through its `DestroyRef`, so a root filter service that outlives its page is never
 * reported for a page the user left.
 */
@Injectable({ providedIn: 'root' })
export class PageContextService {
  private readonly dialog = inject(MatDialog);
  private readonly bottomSheet = inject(MatBottomSheet);
  private current: { id: string; read: PageContextReader } | null = null;
  private readonly owned: OverlayKind[] = [];

  /** Register the page `id`; the returned function removes it (only if it is still the registered one). */
  register(id: string, read: PageContextReader): () => void {
    const entry = { id, read };
    this.current = entry;
    return () => {
      if (this.current === entry) this.current = null;
    };
  }

  /** `{id, ...scalars}` of the registered page, or `null`; a throwing reader yields `{id}`. */
  snapshot(): Record<string, PageContextValue> | null {
    if (!this.current) return null;
    const out: Record<string, PageContextValue> = { id: this.current.id };
    let state: Record<string, unknown>;
    try {
      state = this.current.read();
    } catch {
      return out;
    }
    for (const [key, value] of Object.entries(state)) {
      if (value === null || typeof value === 'number' || typeof value === 'boolean') out[key] = value;
      else if (typeof value === 'string') out[key] = isPathField(key) ? value : value.slice(0, MAX_TEXT_LENGTH);
    }
    return out;
  }

  /** Register a modal surface `MatDialog` cannot see; the returned function removes it. */
  registerOverlay(kind: OverlayKind): () => void {
    this.owned.push(kind);
    return () => {
      const index = this.owned.indexOf(kind);
      if (index >= 0) this.owned.splice(index, 1);
    };
  }

  /** What covers the page now. The connect-assistant dialog is the assistant's own setup surface and does not count. */
  overlays(): OverlayKind[] {
    const kinds = new Set<OverlayKind>(this.owned);
    if (this.dialog.openDialogs.some(ref => ref.id !== CONNECT_ASSISTANT_DIALOG_ID)) kinds.add('dialog');
    if (this.bottomSheet._openedBottomSheetRef) kinds.add('bottom_sheet');
    return [...kinds];
  }
}

/** Register the calling page's context for its lifetime; one line in the component, no cleanup to forget. */
export function registerPageContext(id: string, read: PageContextReader): void {
  const unregister = inject(PageContextService).register(id, read);
  inject(DestroyRef).onDestroy(unregister);
}

/** Register a modal surface owned by the calling component for its lifetime. */
export function registerOverlayForLifetime(kind: OverlayKind): void {
  const unregister = inject(PageContextService).registerOverlay(kind);
  inject(DestroyRef).onDestroy(unregister);
}
