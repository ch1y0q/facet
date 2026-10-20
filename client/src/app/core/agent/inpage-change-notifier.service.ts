import { Injectable, inject } from '@angular/core';
import { MatSnackBar, MatSnackBarRef, TextOnlySnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../services/api.service';
import { I18nService } from '../services/i18n.service';
import { I18N } from '../i18n/keys';

const SNACKBAR_MS = 8000;

/**
 * One non-blocking "Assistant changed N photos" snackbar per burst. Writes landing while it is open
 * raise its count instead of stacking; Undo reverts every batch of the burst.
 */
@Injectable({ providedIn: 'root' })
export class InpageChangeNotifier {
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);
  private ref: MatSnackBarRef<TextOnlySnackBar> | null = null;
  private count = 0;
  private batches: string[] = [];

  /** Record a write that changed `changed` photos (journal batch `batchId`). */
  notify(changed: number, batchId?: string): void {
    if (changed <= 0) return;
    this.count += changed;
    if (batchId) this.batches.push(batchId);
    const message = this.i18n.t(I18N.dialog.connect_assistant.inpage_changed, { count: String(this.count) });
    const ref = this.snackBar.open(message, this.i18n.t(I18N.dialog.connect_assistant.inpage_undo), { duration: SNACKBAR_MS });
    this.ref = ref;
    const batches = this.batches;
    ref.onAction().subscribe(() => void this.undo([...batches]));
    ref.afterDismissed().subscribe(() => {
      // A later write replaced this snackbar: only the one still current ends the burst.
      if (this.ref !== ref) return;
      this.ref = null;
      this.count = 0;
      this.batches = [];
    });
  }

  private async undo(batches: string[]): Promise<void> {
    for (const batch_id of batches) {
      try {
        await firstValueFrom(this.api.undoMcpAction({ batch_id }));
      } catch {
        return;
      }
    }
  }
}
