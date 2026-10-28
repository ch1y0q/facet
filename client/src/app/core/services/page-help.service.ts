import { Injectable, signal } from '@angular/core';

/** An extra help line a page computes at runtime (an i18n key and its params). */
export interface PageHelpNote { key: string; params?: Record<string, string | number>; }

/** The current page's help text (an i18n key), shown by the help dialog that
 *  the user menu's Help entry opens. Each route sets its description on init
 *  and clears it on destroy. */
@Injectable({ providedIn: 'root' })
export class PageHelpService {
  /** i18n key of the current page's help description (null = no help). */
  readonly descriptionKey = signal<string | null>(null);
  /** Optional runtime line shown under the description (null = none). */
  readonly note = signal<PageHelpNote | null>(null);

  setDescription(key: string | null): void {
    this.descriptionKey.set(key);
    this.note.set(null);
  }
}
