import { Component, inject, input, output, signal, computed, effect, viewChild, ChangeDetectionStrategy } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { MatIconModule } from '@angular/material/icon';
import { MatMenuModule, MatMenuTrigger } from '@angular/material/menu';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from '../gallery/gallery.store';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { i18nKeys, I18N } from '../../core/i18n/keys';

/** One row of ``GET /api/photo/faces``. */
export interface PhotoFaceRow {
  id: number;
  face_index: number;
  person_id?: number | null;
  person_name?: string | null;
  box?: number[] | null;
}

/** A face as drawn: its box in the photo's own pixel space, the SVG's viewBox. */
export interface DrawnFace {
  id: number;
  personId: number | null;
  name: string | null;
  x: number;
  y: number;
  w: number;
  h: number;
  /** Label baseline, just above the box, or inside it when the box touches the top edge. */
  labelY: number;
}

/** Label size as a fraction of the frame's longer edge, so it reads the same at any resolution. */
const LABEL_SCALE = 0.022;

/**
 * Faces drawn over the photo-detail image: boxes appear while the pointer is over
 * the photo, a face's name on hovering that face, and clicking a face (edition
 * mode) opens a menu to change its person, take it off its person, or find more
 * faces like that person.
 *
 * The SVG's viewBox is the photo's own pixel frame, so it letterboxes exactly
 * like the ``object-contain`` image beneath it and shares its zoom transform:
 * boxes land on the faces with no measuring. Boxes come pre-normalised from the
 * server, which drops any whose stored dimensions cannot be trusted.
 */
@Component({
  selector: 'app-photo-face-layer',
  imports: [MatIconModule, MatMenuModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  host: { class: 'contents' },
  template: `
    @if (viewBox(); as vb) {
      <svg
        class="absolute inset-0 w-full h-full pointer-events-none"
        [attr.viewBox]="vb"
        preserveAspectRatio="xMidYMid meet"
        [style.transform]="transform()"
        aria-hidden="true">
        @for (f of faces(); track f.id) {
          <g
            class="group/face pointer-events-auto"
            [class.cursor-pointer]="canEdit()"
            (pointerdown)="$event.stopPropagation()"
            (dblclick)="$event.stopPropagation()"
            (click)="onFaceClick(f, $event)">
            <title>{{ f.name || (I18N.photo_faces.unknown | translate) }}</title>
            <rect
              [attr.x]="f.x" [attr.y]="f.y" [attr.width]="f.w" [attr.height]="f.h"
              fill="transparent"
              [attr.stroke]="f.name ? 'white' : '#fbbf24'"
              stroke-width="2"
              vector-effect="non-scaling-stroke"
              class="opacity-0 group-hover/photo:opacity-60 group-hover/face:opacity-100 transition-opacity" />
            <text
              [attr.x]="f.x"
              [attr.y]="f.labelY"
              [attr.font-size]="labelSize()"
              fill="white"
              stroke="black"
              [attr.stroke-width]="labelSize() / 6"
              paint-order="stroke"
              font-family="sans-serif"
              font-weight="600"
              class="opacity-0 group-hover/face:opacity-100 transition-opacity select-none">
              {{ f.name || (I18N.photo_faces.unknown | translate) }}
            </text>
          </g>
        }
      </svg>
    }
    <div class="fixed w-0 h-0" [style.left.px]="menuX()" [style.top.px]="menuY()" [matMenuTriggerFor]="faceMenu"></div>
    <mat-menu #faceMenu="matMenu">
      @if (menuFace(); as f) {
        <div class="px-4 py-2 text-xs opacity-70 truncate max-w-[16rem]">
          {{ f.name || (I18N.photo_faces.unknown | translate) }}
        </div>
        <button mat-menu-item (click)="changePerson(f)">
          <mat-icon>manage_accounts</mat-icon>
          {{ (f.personId ? I18N.photo_faces.change_person : I18N.photo_faces.name_face) | translate }}
        </button>
        @if (f.personId) {
          <button mat-menu-item (click)="findMore(f)">
            <mat-icon>person_search</mat-icon>
            {{ I18N.photo_faces.find_more | translate:{ name: f.name || '' } }}
          </button>
          <button mat-menu-item (click)="notThisPerson(f)">
            <mat-icon>person_remove</mat-icon>
            {{ I18N.photo_faces.not_person | translate:{ name: f.name || '' } }}
          </button>
        }
      }
    </mat-menu>
  `,
})
export class PhotoFaceLayerComponent {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly dialog = inject(MatDialog);
  private readonly snackBar = inject(MatSnackBar);
  private readonly i18n = inject(I18nService);
  private readonly store = inject(GalleryStore);

  readonly path = input.required<string>();
  readonly imageWidth = input<number | null>(null);
  readonly imageHeight = input<number | null>(null);
  /** The image's zoom/pan transform, so the boxes stay on the faces. */
  readonly transform = input('');
  readonly canEdit = input(false);
  /** Emitted after a face changed person, so the page can refresh the photo's people. */
  readonly changed = output<void>();

  private readonly menuTrigger = viewChild.required(MatMenuTrigger);
  private readonly rows = signal<PhotoFaceRow[]>([]);
  protected readonly menuFace = signal<DrawnFace | null>(null);
  protected readonly menuX = signal(0);
  protected readonly menuY = signal(0);

  protected readonly viewBox = computed(() => {
    const w = this.imageWidth();
    const h = this.imageHeight();
    return w && h && this.faces().length > 0 ? `0 0 ${w} ${h}` : null;
  });

  protected readonly labelSize = computed(() =>
    Math.max(this.imageWidth() ?? 0, this.imageHeight() ?? 0) * LABEL_SCALE);


  readonly faces = computed<DrawnFace[]>(() => {
    const w = this.imageWidth();
    const h = this.imageHeight();
    if (!w || !h) return [];
    const label = this.labelSize();
    return this.rows()
      .filter((r): r is PhotoFaceRow & { box: number[] } => Array.isArray(r.box) && r.box.length === 4)
      .map((r) => {
        const [x1, y1, x2, y2] = r.box;
        const y = y1 * h;
        return {
          id: r.id,
          personId: r.person_id ?? null,
          name: r.person_name ?? null,
          x: x1 * w,
          y,
          w: (x2 - x1) * w,
          h: (y2 - y1) * h,
          labelY: y - label * 0.4 > label ? y - label * 0.4 : y + label * 1.1,
        };
      });
  });

  constructor() {
    effect(() => {
      const path = this.path();
      void this.load(path);
    });
  }

  async load(path: string = this.path()): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.get<{ faces: PhotoFaceRow[] }>('/photo/faces', { path }));
      if (path === this.path()) this.rows.set(res.faces ?? []);
    } catch {
      if (path === this.path()) this.rows.set([]);
    }
  }

  onFaceClick(face: DrawnFace, event: MouseEvent): void {
    event.stopPropagation();
    if (!this.canEdit()) return;
    this.menuFace.set(face);
    this.menuX.set(event.clientX);
    this.menuY.set(event.clientY);
    this.menuTrigger().openMenu();
  }

  async changePerson(face: DrawnFace): Promise<void> {
    const { PersonSelectorDialogComponent } = await import('../gallery/person-selector-dialog.component');
    const ref = this.dialog.open(PersonSelectorDialogComponent, { width: '95vw', maxWidth: '400px' });
    const result = await firstValueFrom(ref.afterClosed()) as
      | { kind: 'select'; person: { id: number; name: string | null } }
      | { kind: 'create'; name: string }
      | undefined;
    if (!result) return;
    const path = this.path();
    let ok: boolean;
    if (result.kind === 'create') {
      ok = (await this.store.createPerson(result.name, [face.id], path)) !== null;
    } else {
      ok = await this.store.assignFace(face.id, result.person.id, path, result.person.name ?? '');
    }
    this.snackBar.open(
      this.i18n.t(ok ? I18N.notifications.faces_assigned : I18N.errors.action_failed), '', { duration: ok ? 2000 : 3000 });
    if (ok) await this.afterChange();
  }

  async notThisPerson(face: DrawnFace): Promise<void> {
    if (face.personId === null) return;
    await this.store.unassignPerson(this.path(), face.personId);
    await this.afterChange();
  }

  async findMore(face: DrawnFace): Promise<void> {
    if (face.personId === null) return;
    const { FindMoreFacesDialogComponent } = await import('../persons/find-more-faces-dialog.component');
    const ref = this.dialog.open(FindMoreFacesDialogComponent, {
      data: { personId: face.personId, personName: face.name },
      width: '95vw',
      maxWidth: '720px',
    });
    const result = await firstValueFrom(ref.afterClosed()) as { added: number } | undefined;
    if (result && result.added > 0) {
      this.snackBar.open(this.i18n.t(I18N.persons.find_more_added, { count: result.added }), '', { duration: 2000 });
      await this.afterChange();
    }
  }

  private async afterChange(): Promise<void> {
    await this.load();
    this.changed.emit();
  }
}
