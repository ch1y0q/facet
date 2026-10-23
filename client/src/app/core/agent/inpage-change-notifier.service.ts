import { Injectable, effect, inject, untracked } from '@angular/core';
import { MatSnackBar, MatSnackBarRef, TextOnlySnackBar } from '@angular/material/snack-bar';
import { AuthService } from '../services/auth.service';
import { I18nService } from '../services/i18n.service';
import { I18N } from '../i18n/keys';

const SNACKBAR_MS = 8000;

/**
 * One non-blocking "Assistant changed N photos" snackbar per burst. Writes landing while it is open
 * raise its count instead of stacking. Its only action is Close.
 */
@Injectable({ providedIn: 'root' })
export class InpageChangeNotifier {
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly auth = inject(AuthService);
  private ref: MatSnackBarRef<TextOnlySnackBar> | null = null;
  private count = 0;

  constructor() {
    let first = true;
    effect(() => {
      this.auth.identity();
      untracked(() => {
        if (first) first = false;
        else this.dropBurst();
      });
    });
  }

  /** Record a write that changed `changed` photos. */
  notify(changed: number): void {
    if (changed <= 0) return;
    this.count += changed;
    const keys = I18N.dialog.connect_assistant;
    const close = I18N.dialog.close;
    const message = this.i18n.t(this.count === 1 ? keys.inpage_changed : keys.inpage_changed_plural, { count: String(this.count) });
    const ref = this.snackBar.open(message, this.i18n.t(close), { duration: SNACKBAR_MS });
    this.ref = ref;
    ref.afterDismissed().subscribe(() => {
      // A later write replaced this snackbar: only the one still current ends the burst.
      if (this.ref !== ref) return;
      this.ref = null;
      this.count = 0;
    });
  }

  private dropBurst(): void {
    const ref = this.ref;
    this.ref = null;
    this.count = 0;
    ref?.dismiss();
  }
}
