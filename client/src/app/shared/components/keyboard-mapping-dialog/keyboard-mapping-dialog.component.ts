import { ChangeDetectionStrategy, Component, HostListener, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatDialogModule } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { TranslatePipe } from '../../../shared/pipes/translate.pipe';
import { i18nKeys, I18N } from '../../../core/i18n/keys';
import { KeymapConfig, KeyboardMappingService } from '../../../core/services/keyboard-mapping.service';

/** The remappable actions, labelled with the same strings the keyboard
 *  reference tables use, so the settings dialog and the reference can never
 *  name an action differently. */
const KEYMAP_ACTIONS: { id: keyof KeymapConfig; labelKey: string }[] = [
  { id: 'favourite', labelKey: I18N.shortcuts.favorite },
  { id: 'reject', labelKey: I18N.shortcuts.reject },
  { id: 'keep', labelKey: I18N.review.shortcut },
  { id: 'focusSearch', labelKey: I18N.shortcuts.focus_search },
  { id: 'toggleSidebar', labelKey: I18N.shortcuts.toggle_filters },
  { id: 'swapLayout', labelKey: I18N.shortcuts.toggle_layout },
];

/** Keys capture refuses: the digits drive rating (and the 0 reject alias),
 *  Space scrolls the page, ? opens the shortcut reference. Modifier combos
 *  are not remappable at all, and multi-key names (arrows, Home, F-keys)
 *  never reach the capture branch. */
const RESERVED_KEYS = new Set(['0', '1', '2', '3', '4', '5', ' ', '?']);

/** Lets the user reassign the primary key of each gallery and photo-page
 *  action. Click a row to enter capture mode, press the new key; Esc backs
 *  out, and a key held by another action or a reserved key is refused with
 *  an inline message. */
@Component({
  selector: 'app-keyboard-mapping-dialog',
  standalone: true,
  imports: [MatButtonModule, MatDialogModule, MatIconModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <div class="px-6 pt-5">
      <div class="flex items-center gap-3 mb-1">
        <div class="w-9 h-9 rounded-lg bg-[var(--mat-sys-primary-container)] flex items-center justify-center shrink-0">
          <mat-icon class="!text-base !w-5 !h-5 !leading-5 text-[var(--mat-sys-on-primary-container)]">keyboard</mat-icon>
        </div>
        <h2 mat-dialog-title class="!text-base !font-semibold !m-0 !p-0">{{ I18N.shortcuts.title | translate }}</h2>
      </div>
    </div>
    <mat-dialog-content class="!px-6">
      <p class="text-xs opacity-60 mt-0 mb-3">{{ I18N.shortcuts.keymap_hint | translate }}</p>
      <div class="flex flex-col gap-1">
        @for (action of KEYMAP_ACTIONS; track action.id) {
          <div class="flex items-center gap-3 py-0.5">
            <span class="flex-1 text-sm">{{ action.labelKey | translate }}</span>
            <button
              type="button"
              mat-stroked-button
              class="!min-w-[3.5rem] !px-3 !py-0.5 !rounded-md font-mono text-xs"
              [class.!border-[var(--mat-sys-primary)]]="capturing() === action.id"
              [attr.aria-label]="action.labelKey"
              (click)="startCapture(action.id, $event)">
              @if (capturing() === action.id) {
                {{ I18N.shortcuts.press_key | translate }}
              } @else {
                {{ displayKey(action.id) }}
              }
            </button>
          </div>
        }
      </div>
      @if (error(); as message) {
        <p class="text-xs text-[var(--mat-sys-error)] mt-2 mb-0">{{ message | translate }}</p>
      }
    </mat-dialog-content>
    <mat-dialog-actions class="!px-6 !pb-5">
      <button mat-button (click)="resetAll()">{{ I18N.shortcuts.reset_keys | translate }}</button>
      <span class="flex-1"></span>
      <button mat-flat-button mat-dialog-close class="!rounded-lg !px-5">{{ I18N.dialog.ok | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class KeyboardMappingDialogComponent {
  protected readonly I18N = i18nKeys();
  protected readonly KEYMAP_ACTIONS = KEYMAP_ACTIONS;
  private readonly mapping = inject(KeyboardMappingService);
  private readonly capturingAction = signal<keyof KeymapConfig | null>(null);
  private readonly errorMessage = signal('');
  protected readonly capturing = this.capturingAction.asReadonly();
  protected readonly error = this.errorMessage.asReadonly();

  protected displayKey(action: keyof KeymapConfig): string {
    return this.mapping.key(action).toUpperCase();
  }

  protected startCapture(action: keyof KeymapConfig, event: MouseEvent): void {
    event.stopPropagation();
    this.errorMessage.set('');
    this.capturingAction.set(action);
  }

  protected resetAll(): void {
    this.mapping.resetAll();
    this.errorMessage.set('');
    this.capturingAction.set(null);
  }

  @HostListener('document:keydown', ['$event'])
  protected onKeydown(event: KeyboardEvent): void {
    const action = this.capturingAction();
    if (!action) return;
    event.preventDefault();
    event.stopPropagation();
    if (event.key === 'Escape') {
      this.capturingAction.set(null);
      return;
    }
    if (event.key.length !== 1 || event.ctrlKey || event.metaKey || event.altKey) return;
    const key = event.key.toLowerCase();
    if (RESERVED_KEYS.has(key)) {
      this.errorMessage.set(I18N.shortcuts.key_reserved);
      this.capturingAction.set(null);
      return;
    }
    const clash = KEYMAP_ACTIONS.find(a => a.id !== action && this.mapping.key(a.id) === key);
    if (clash) {
      this.errorMessage.set(I18N.shortcuts.key_in_use);
      this.capturingAction.set(null);
      return;
    }
    this.mapping.setKey(action, key);
    this.errorMessage.set('');
    this.capturingAction.set(null);
  }
}
