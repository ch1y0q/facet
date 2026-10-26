import { Injectable, signal } from '@angular/core';

/** The current page's help text (an i18n key), shown by the help dialog that
 *  the header's ? button and the user menu's Help entry both open. Each route
 *  sets its description on init and clears it on destroy. */
@Injectable({ providedIn: 'root' })
export class PageHelpService {
  /** i18n key of the current page's help description (null = no help). */
  readonly descriptionKey = signal<string | null>(null);

  setDescription(key: string | null): void {
    this.descriptionKey.set(key);
  }
}
