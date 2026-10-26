import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { TranslatePipe } from '../../../shared/pipes/translate.pipe';
import { i18nKeys } from '../../../core/i18n/keys';

/** The "?" menu entry's dialog: the current page's help text in a proper
 *  modal, instead of toggling the in-page banner — a menu affordance that
 *  opens a banner reads as a misfire. */
@Component({
  selector: 'app-help-dialog',
  standalone: true,
  imports: [MatButtonModule, MatDialogModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title>{{ I18N.culling.help | translate }}</h2>
    <mat-dialog-content>
      @if (descriptionKey; as key) {
        <p class="text-sm whitespace-pre-line">{{ key | translate }}</p>
      } @else {
        <p class="text-sm opacity-70">{{ I18N.gallery.help_none | translate }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-flat-button color="primary" mat-dialog-close>
        {{ I18N.dialog.ok | translate }}
      </button>
    </mat-dialog-actions>
  `,
})
export class HelpDialogComponent {
  protected readonly I18N = i18nKeys();
  private readonly dialogRef = inject(MatDialogRef<HelpDialogComponent>);
  /** Set by the opener from PageHelpService before open(). */
  readonly descriptionKey = (inject(MAT_DIALOG_DATA) as { key?: string | null }).key ?? null;
}
