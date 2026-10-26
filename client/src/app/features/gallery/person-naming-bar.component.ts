import { Component, inject, input, signal, computed, effect, ChangeDetectionStrategy } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { MatButtonModule } from '@angular/material/button';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { ConfirmDialogComponent } from '../../shared/components/confirm-dialog/confirm-dialog.component';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { PersonThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { GalleryStore } from './gallery.store';
import { i18nKeys, I18N } from '../../core/i18n/keys';

/** One row of ``GET /api/filter_options/persons``: ``[id, name, photo_count]``. */
type PersonOptionRow = [number, string | null, number];

interface PersonOptionItem {
  id: number;
  name: string | null;
  count: number;
}

/** Names compared the way the server's same-name check does: case and outer spaces ignored. */
export function sameName(a: string | null, b: string | null): boolean {
  return !!a && !!b && a.trim().toLowerCase() === b.trim().toLowerCase();
}

/**
 * Shown above the gallery while it is filtered to one person: who the person is,
 * and, in edition mode, a name field to settle it from here after reviewing the
 * photos. A name that already belongs to another person merges this person into
 * that one (after a confirm) and moves the gallery to it; a new name renames this
 * person.
 */
@Component({
  selector: 'app-person-naming-bar',
  imports: [FormsModule, MatButtonModule, MatIconModule, MatTooltipModule, TranslatePipe, PersonThumbnailUrlPipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    @if (person(); as p) {
      <div class="mx-2 md:mx-4 mt-2 md:mt-4 px-3 py-2 rounded-md bg-[var(--mat-sys-surface-container-high)] border border-[var(--mat-sys-outline-variant)] flex flex-wrap items-center gap-3 text-sm">
        <img [src]="p.id | personThumbnailUrl" alt="" class="w-8 h-8 rounded-full object-cover shrink-0" />
        <span class="font-medium">
          @if (p.name) {
            {{ p.name }}
          } @else {
            {{ I18N.gallery.person_bar.unnamed | translate:{ id: p.id } }}
          }
        </span>
        @if (hiddenCount() > 0) {
          <span class="opacity-70">
            {{ I18N.gallery.person_bar.shown_of | translate:{ shown: shownCount(), all: shownCount() + hiddenCount() } }}
            · {{ I18N.gallery.person_bar.hidden_why | translate:{ n: hiddenCount(), why: hiddenReasons() } }}
          </span>
          <button mat-button class="!min-w-0" [matTooltip]="I18N.gallery.person_bar.show_all_hint | translate"
                  (click)="store.showAllHidden()">
            {{ I18N.gallery.person_bar.show_all | translate }}
          </button>
        } @else {
          <span class="opacity-70">{{ I18N.gallery.person_bar.photos | translate:{ count: shownCount() } }}</span>
          @if (store.hiddenFiltersStash()) {
            <button mat-button class="!min-w-0" (click)="store.restoreHidden()">
              {{ I18N.gallery.person_bar.hide_again | translate }}
            </button>
          }
        }
        @if (canEdit()) {
          <span class="flex-1"></span>
          <input
            class="bg-transparent border-b border-[var(--mat-sys-outline)] focus:border-[var(--mat-sys-primary)] outline-none py-0.5 w-56"
            [placeholder]="(p.name ? I18N.gallery.person_bar.rename_placeholder : I18N.gallery.person_bar.name_placeholder) | translate"
            [attr.aria-label]="I18N.gallery.person_bar.name_placeholder | translate"
            list="person-bar-names"
            autocomplete="off"
            [(ngModel)]="draft"
            (keyup.enter)="assign()" />
          <datalist id="person-bar-names">
            @for (n of otherNames(); track n) {
              <option [value]="n"></option>
            }
          </datalist>
          <button mat-flat-button [disabled]="busy()" (click)="assign()">
            <mat-icon>how_to_reg</mat-icon>
            {{ I18N.gallery.person_bar.assign | translate }}
          </button>
        }
      </div>
    }
  `,
})
export class PersonNamingBarComponent {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  protected readonly store = inject(GalleryStore);

  readonly personId = input.required<number>();
  readonly canEdit = input(false);

  private readonly options = signal<PersonOptionItem[]>([]);
  protected readonly busy = signal(false);
  protected draft = '';

  readonly person = computed(() => this.options().find((o) => o.id === this.personId()) ?? null);

  /** Photos the gallery shows for this person with the current filters. */
  readonly shownCount = computed(() => this.store.total());
  /** Photos of this person the gallery's hide toggles (bursts, blinks...) keep out of view. */
  readonly hiddenCount = computed(() => this.store.hiddenSummary().total);
  /** Why they are hidden, in words: "burst repeat", "blink"... joined with commas. */
  readonly hiddenReasons = computed(() => {
    const h = this.store.hiddenSummary();
    const keys: [number, string][] = [
      [h.bursts, I18N.gallery.person_bar.reason_bursts],
      [h.blinks, I18N.gallery.person_bar.reason_blinks],
      [h.duplicates, I18N.gallery.person_bar.reason_duplicates],
      [h.brackets, I18N.gallery.person_bar.reason_brackets],
      [h.panoramas, I18N.gallery.person_bar.reason_panoramas],
    ];
    return keys.filter(([n]) => n > 0).map(([n, key]) => this.i18n.t(key, { n })).join(', ');
  });

  /** Every other named person, for the suggestions. */
  readonly otherNames = computed(() =>
    this.options()
      .filter((o) => o.id !== this.personId() && !!o.name?.trim())
      .map((o) => (o.name as string).trim())
      .sort((a, b) => a.localeCompare(b)));

  constructor() {
    effect(() => {
      const id = this.personId();
      this.draft = '';
      void this.load(id);
    });
  }

  async load(id: number = this.personId()): Promise<void> {
    try {
      const res = await firstValueFrom(
        this.api.get<{ persons: PersonOptionRow[] }>('/filter_options/persons', { ids: String(id) }));
      if (id !== this.personId()) return;
      this.options.set((res.persons ?? []).map(([pid, name, count]) => ({ id: pid, name, count })));
    } catch {
      if (id === this.personId()) this.options.set([]);
    }
  }

  async assign(): Promise<void> {
    const me = this.person();
    const name = this.draft.trim();
    if (!me || !name || this.busy()) return;
    if (sameName(me.name, name)) {
      this.draft = '';
      return;
    }
    const target = this.options().find((o) => o.id !== me.id && sameName(o.name, name));
    this.busy.set(true);
    try {
      if (target) {
        await this.mergeInto(me, target);
      } else {
        await firstValueFrom(this.api.post(`/persons/${me.id}/rename`, { name }));
        this.snackBar.open(this.i18n.t(I18N.gallery.person_bar.named, { name }), '', { duration: 2500 });
        this.draft = '';
        await Promise.all([this.load(me.id), this.store.reloadPersonOptions()]);
      }
    } catch {
      this.snackBar.open(this.i18n.t(I18N.gallery.person_bar.error), '', { duration: 3000 });
    } finally {
      this.busy.set(false);
    }
  }

  /** Fold ``me`` into the existing person ``target``, then show ``target``'s photos. */
  private async mergeInto(me: PersonOptionItem, target: PersonOptionItem): Promise<void> {
    const label = me.name || this.i18n.t(I18N.gallery.person_bar.unnamed, { id: me.id });
    const ref = this.dialog.open(ConfirmDialogComponent, {
      data: {
        title: this.i18n.t(I18N.gallery.person_bar.merge_title, { name: target.name ?? '' }),
        message: this.i18n.t(I18N.gallery.person_bar.merge_message, {
          from: label, count: me.count, name: target.name ?? '',
        }),
        confirmLabel: this.i18n.t(I18N.gallery.person_bar.merge_confirm),
      },
    });
    if (!(await firstValueFrom(ref.afterClosed()))) return;
    await firstValueFrom(this.api.post('/persons/merge', { source_id: me.id, target_id: target.id }));
    this.snackBar.open(this.i18n.t(I18N.gallery.person_bar.merged, { name: target.name ?? '' }), '', { duration: 2500 });
    this.draft = '';
    await this.store.reloadPersonOptions();
    await this.store.updateFilters({ person_id: String(target.id) });
  }
}
