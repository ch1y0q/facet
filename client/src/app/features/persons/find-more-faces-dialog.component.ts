import { Component, inject, signal, computed, OnInit, ChangeDetectionStrategy } from '@angular/core';
import { HttpErrorResponse } from '@angular/common/http';
import { MatButtonModule } from '@angular/material/button';
import { MatButtonToggleModule } from '@angular/material/button-toggle';
import { MatDialogModule, MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressSpinnerModule } from '@angular/material/progress-spinner';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { FaceThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { i18nKeys } from '../../core/i18n/keys';

/** One row of ``GET /api/person/{id}/possible_faces``. */
export interface PossibleFace {
  face_id: number;
  photo_path: string;
  person_id?: number | null;
  person_name?: string | null;
  similarity: number;
  distance: number;
}

export interface FindMoreFacesDialogData {
  personId: number;
  personName: string | null;
}

/** What the dialog closes with: how many faces it moved onto the person. */
export interface FindMoreFacesResult {
  added: number;
}

export type FindMoreScope = 'all' | 'unassigned';

/** Faces shown per round. */
export const FIND_MORE_PAGE = 48;
/** Rows asked of the server per round, so the faces dismissed earlier can be dropped and still fill a page. */
export const FIND_MORE_FETCH = 100;
/** Floor of the server's search; matches its own default. */
export const FIND_MORE_MIN_SIMILARITY = 0.3;
/** A face at or above this similarity starts ticked, unless a differently named person owns it. */
export const FIND_MORE_PRESELECT = 0.5;

/**
 * "Find more faces like this person": a teach-by-example loop over the
 * ``possible_faces`` search. Each round lists the faces closest to the person's
 * centroid; the user ticks the right ones and adds them, which recomputes the
 * centroid server-side, so the next round is ranked against what was just
 * confirmed. Faces shown in a round and left unticked are taken as "not this
 * person" and are not offered again while the dialog stays open.
 */
@Component({
  selector: 'app-find-more-faces-dialog',
  imports: [
    MatButtonModule,
    MatButtonToggleModule,
    MatDialogModule,
    MatIconModule,
    MatProgressSpinnerModule,
    MatTooltipModule,
    TranslatePipe,
    FaceThumbnailUrlPipe,
  ],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title class="truncate">
      {{ I18N.persons.find_more_title | translate }}
    </h2>
    <mat-dialog-content class="!flex !flex-col gap-3 min-w-[320px] min-h-[160px]">
      <p class="text-sm text-gray-400">
        {{ I18N.persons.find_more_desc | translate:{ name: data.personName || (I18N.persons.unnamed | translate) } }}
      </p>
      <div class="flex items-center gap-2 flex-wrap">
        <mat-button-toggle-group
          hideSingleSelectionIndicator
          [value]="scope()"
          (change)="setScope($event.value)"
          [attr.aria-label]="I18N.persons.find_more_scope | translate">
          <mat-button-toggle value="all">{{ I18N.persons.find_more_scope_all | translate }}</mat-button-toggle>
          <mat-button-toggle value="unassigned">{{ I18N.persons.find_more_scope_unassigned | translate }}</mat-button-toggle>
        </mat-button-toggle-group>
        <span class="flex-1"></span>
        @if (rows().length > 0) {
          <button mat-button (click)="selectAll()">{{ I18N.persons.find_more_select_all | translate }}</button>
          <button mat-button (click)="clearSelection()">{{ I18N.persons.find_more_clear | translate }}</button>
        }
      </div>
      @if (loading()) {
        <div class="flex items-center justify-center py-8">
          <mat-spinner diameter="32" [attr.aria-label]="I18N.ui.labels.loading | translate" />
        </div>
      } @else if (error()) {
        <p class="text-sm text-center py-8">{{ error() }}</p>
      } @else if (rows().length === 0) {
        <p class="text-sm opacity-60 text-center py-8">{{ I18N.persons.find_more_none | translate }}</p>
      } @else {
        <div class="flex flex-wrap gap-2 justify-center">
          @for (row of rows(); track row.face_id; let i = $index) {
            <button
              class="relative rounded-lg overflow-hidden border-2 transition-colors cursor-pointer"
              [class.border-blue-500]="row.selected"
              [class.border-transparent]="!row.selected"
              [attr.aria-pressed]="row.selected"
              [attr.aria-label]="I18N.persons.find_more_select_face | translate:{ index: i + 1 }"
              [matTooltip]="row.person_name ? (I18N.persons.find_more_owner | translate:{ name: row.person_name }) : ''"
              (click)="toggle(row.face_id)">
              <img [src]="row.face_id | faceThumbnailUrl" alt="" class="w-24 h-24 object-cover" />
              <span class="absolute bottom-0 left-0 right-0 bg-black/60 text-white text-[0.625rem] px-1 truncate">
                {{ I18N.persons.find_more_similarity | translate:{ percent: row.percent } }}
                @if (row.person_name) { · {{ row.person_name }} }
              </span>
              @if (row.selected) {
                <span class="absolute top-1 right-1 bg-blue-500 text-white rounded-full flex items-center justify-center w-5 h-5">
                  <mat-icon class="!text-sm !w-4 !h-4 leading-4">check</mat-icon>
                </span>
              }
            </button>
          }
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="close()">{{ I18N.persons.find_more_done | translate }}</button>
      <button mat-flat-button [disabled]="selectedIds().size === 0 || busy()" (click)="addSelected()">
        <mat-icon>person_add</mat-icon>
        {{ I18N.persons.find_more_add | translate:{ count: selectedIds().size } }}
      </button>
    </mat-dialog-actions>
  `,
})
export class FindMoreFacesDialogComponent implements OnInit {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);
  readonly data: FindMoreFacesDialogData = inject(MAT_DIALOG_DATA);
  readonly dialogRef = inject(MatDialogRef<FindMoreFacesDialogComponent, FindMoreFacesResult>);

  readonly scope = signal<FindMoreScope>('all');
  readonly loading = signal(true);
  readonly busy = signal(false);
  readonly error = signal<string | null>(null);
  readonly faces = signal<PossibleFace[]>([]);
  readonly selectedIds = signal<Set<number>>(new Set());
  /** Faces shown in an earlier round and left unticked: not offered again. */
  private readonly dismissed = new Set<number>();
  private added = 0;

  readonly rows = computed(() => {
    const selected = this.selectedIds();
    return this.faces().map((f) => ({
      ...f,
      selected: selected.has(f.face_id),
      percent: Math.round(f.similarity * 100),
    }));
  });

  ngOnInit(): Promise<void> {
    return this.load();
  }

  async load(): Promise<void> {
    this.loading.set(true);
    this.error.set(null);
    try {
      const res = await firstValueFrom(
        this.api.get<{ faces: PossibleFace[] }>(`/person/${this.data.personId}/possible_faces`, {
          scope: this.scope(),
          limit: FIND_MORE_FETCH,
          min_similarity: FIND_MORE_MIN_SIMILARITY,
        }),
      );
      const faces = (res.faces ?? [])
        .filter((f) => !this.dismissed.has(f.face_id))
        .slice(0, FIND_MORE_PAGE);
      this.faces.set(faces);
      // A face owned by a person of the same name is a split-off cluster of this one, not someone else.
      const sameName = (f: PossibleFace) => !!f.person_name && f.person_name === this.data.personName;
      this.selectedIds.set(new Set(
        faces
          .filter((f) => f.similarity >= FIND_MORE_PRESELECT && (!f.person_name || sameName(f)))
          .map((f) => f.face_id),
      ));
    } catch (err) {
      this.faces.set([]);
      this.selectedIds.set(new Set());
      this.error.set(this.errorMessage(err));
    } finally {
      this.loading.set(false);
    }
  }

  setScope(scope: FindMoreScope): void {
    if (scope === this.scope()) return;
    this.scope.set(scope);
    void this.load();
  }

  toggle(faceId: number): void {
    this.selectedIds.update((set) => {
      const next = new Set(set);
      if (next.has(faceId)) {
        next.delete(faceId);
      } else {
        next.add(faceId);
      }
      return next;
    });
  }

  selectAll(): void {
    this.selectedIds.set(new Set(this.faces().map((f) => f.face_id)));
  }

  clearSelection(): void {
    this.selectedIds.set(new Set());
  }

  async addSelected(): Promise<void> {
    const faceIds = [...this.selectedIds()];
    if (faceIds.length === 0 || this.busy()) return;
    this.busy.set(true);
    try {
      await firstValueFrom(
        this.api.post(`/persons/${this.data.personId}/assign_faces`, { face_ids: faceIds }),
      );
      this.added += faceIds.length;
      const chosen = new Set(faceIds);
      for (const f of this.faces()) {
        if (!chosen.has(f.face_id)) this.dismissed.add(f.face_id);
      }
      await this.load();
    } catch {
      this.error.set(this.i18n.t(this.I18N.persons.find_more_add_error));
    } finally {
      this.busy.set(false);
    }
  }

  close(): void {
    this.dialogRef.close({ added: this.added });
  }

  /** A 412 means no centroid yet, or a scan over the server's ceiling, whose detail says how to narrow it. */
  private errorMessage(err: unknown): string {
    if (err instanceof HttpErrorResponse && err.status === 412) {
      const detail = typeof err.error?.detail === 'string' ? err.error.detail : '';
      if (detail.includes('centroid')) return this.i18n.t(this.I18N.persons.find_more_no_centroid);
      if (detail) return detail;
    }
    return this.i18n.t(this.I18N.persons.find_more_error);
  }
}
