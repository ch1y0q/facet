import { ChangeDetectionStrategy, Component, inject } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule, MatDialogRef, MAT_DIALOG_DATA } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { TranslatePipe } from '../../../shared/pipes/translate.pipe';
import { i18nKeys } from '../../../core/i18n/keys';

/** The "?" menu entry's dialog: the current page's help text in a proper
 *  modal, instead of toggling the in-page banner — a menu affordance that
 *  opens a banner reads as a misfire. */
@Component({
  selector: 'app-help-dialog',
  standalone: true,
  imports: [MatButtonModule, MatDialogModule, MatIconModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <div class="px-6 pt-5">
      <div class="flex items-center gap-3 mb-3">
        <div class="w-9 h-9 rounded-lg bg-[var(--mat-sys-primary-container)] flex items-center justify-center shrink-0">
          <mat-icon class="!text-xl !w-5 !h-5 text-[var(--mat-sys-on-primary-container)]">help_outline</mat-icon>
        </div>
        <h2 class="text-base font-semibold m-0">{{ I18N.culling.help | translate }}</h2>
      </div>
    </div>
    <mat-dialog-content class="!px-6">
      @if (descriptionKey; as key) {
        <p class="text-sm leading-relaxed m-0">{{ key | translate }}</p>
      } @else {
        <p class="text-sm leading-relaxed m-0 opacity-70">{{ I18N.gallery.help_none | translate }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions class="!px-6 !pb-5">
      <span class="flex-1"></span>
      <button mat-flat-button color="primary" mat-dialog-close class="!rounded-lg !px-5">
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
