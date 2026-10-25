import { ChangeDetectionStrategy, Component, inject, signal } from '@angular/core';
import { MatButtonModule } from '@angular/material/button';
import { MatCheckboxModule } from '@angular/material/checkbox';
import { MatIconModule } from '@angular/material/icon';
import { MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatTooltipModule } from '@angular/material/tooltip';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { I18N } from '../../core/i18n/keys';
import { CardActionId, CardActionsConfig, DEFAULT_CARD_ACTIONS } from '../../shared/components/photo-card/card-actions';
import { CardActionsService } from './card-actions.service';

/** Which action id each button row is labelled and iconned with. */
export const CARD_ACTION_META: Record<CardActionId, { icon: string; labelKey: string }> = {
  similar: { icon: 'image_search', labelKey: 'similar.find_similar' },
  critique: { icon: 'analytics', labelKey: 'critique.title' },
  embed: { icon: 'save', labelKey: 'photoCard.embed_to_file' },
  assign_face: { icon: 'person_add', labelKey: 'manage_persons.assign_face' },
  duplicate_set: { icon: 'photo_library', labelKey: 'photoCard.duplicate_set' },
  burst_set: { icon: 'burst_mode', labelKey: 'photoCard.burst_set' },
  sequence_set: { icon: 'auto_awesome_motion', labelKey: 'photoCard.sequence_set' },
  open_detail: { icon: 'open_in_full', labelKey: 'photoCard.open_detail' },
};

/** Reorder and show/hide the photo card's hover buttons. Arrows rather than a
 *  drag list: the dialog has at most eight rows and keyboard-operable arrows
 *  need no drag-and-drop polyfill to stay accessible. */
@Component({
  selector: 'app-card-actions-dialog',
  standalone: true,
  imports: [MatButtonModule, MatCheckboxModule, MatIconModule, MatDialogModule, MatTooltipModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title>{{ I18N.gallery.card_actions.title | translate }}</h2>
    <mat-dialog-content>
      <p class="text-sm opacity-70 mb-3">{{ I18N.gallery.card_actions.hint | translate }}</p>
      <div class="flex flex-col gap-1">
        @for (id of order(); track id; let i = $index) {
          <div class="flex items-center gap-2 px-2 py-1 rounded hover:bg-[var(--mat-sys-surface-container-high)]">
            <mat-checkbox [checked]="!isHidden(id)" (change)="toggle(id, $event.checked)">
              <span class="flex items-center gap-2">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4 opacity-70">{{ CARD_ACTION_META[id].icon }}</mat-icon>
                {{ CARD_ACTION_META[id].labelKey | translate }}
              </span>
            </mat-checkbox>
            <span class="ml-auto flex items-center">
              <button mat-icon-button class="!w-8 !h-8" [disabled]="i === 0"
                      [matTooltip]="I18N.gallery.card_actions.move_up | translate"
                      [attr.aria-label]="I18N.gallery.card_actions.move_up | translate"
                      (click)="move(i, -1)">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">arrow_upward</mat-icon>
              </button>
              <button mat-icon-button class="!w-8 !h-8" [disabled]="i === order().length - 1"
                      [matTooltip]="I18N.gallery.card_actions.move_down | translate"
                      [attr.aria-label]="I18N.gallery.card_actions.move_down | translate"
                      (click)="move(i, 1)">
                <mat-icon class="!text-base !w-4 !h-4 !leading-4">arrow_downward</mat-icon>
              </button>
            </span>
          </div>
        }
      </div>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="reset()">{{ I18N.gallery.card_actions.reset | translate }}</button>
      <button mat-button (click)="ref.close()">{{ I18N.ui.buttons.cancel | translate }}</button>
      <button mat-flat-button color="primary" (click)="save()">{{ I18N.ui.buttons.save | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class CardActionsDialogComponent {
  protected readonly I18N = I18N;
  protected readonly CARD_ACTION_META = CARD_ACTION_META;
  protected readonly ref = inject(MatDialogRef<CardActionsDialogComponent>);
  private readonly service = inject(CardActionsService);

  private readonly initial = this.service.config();
  protected readonly order = signal<CardActionId[]>([...this.initial.order]);
  protected readonly hidden = signal<Set<CardActionId>>(new Set(this.initial.hidden));

  protected isHidden(id: CardActionId): boolean {
    return this.hidden().has(id);
  }

  protected toggle(id: CardActionId, visible: boolean): void {
    this.hidden.update(current => {
      const next = new Set(current);
      if (visible) next.delete(id); else next.add(id);
      return next;
    });
  }

  protected move(index: number, delta: -1 | 1): void {
    this.order.update(order => {
      const next = [...order];
      const target = index + delta;
      [next[index], next[target]] = [next[target], next[index]];
      return next;
    });
  }

  protected reset(): void {
    this.order.set([...DEFAULT_CARD_ACTIONS.order]);
    this.hidden.set(new Set(DEFAULT_CARD_ACTIONS.hidden));
  }

  protected save(): void {
    const config: CardActionsConfig = { order: this.order(), hidden: [...this.hidden()] };
    this.service.set(config);
    this.ref.close();
  }
}
