import { Component, inject, input, signal, computed, effect, ChangeDetectionStrategy } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';

/** One row of ``GET /api/photo/faces`` as far as this overlay needs it. */
interface FaceRow {
  person_id?: number | null;
  box?: number[] | null;
}

/** A face to outline, in the photo's pixel frame (the SVG's viewBox). */
export interface FocusRect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/**
 * Red outline on the faces of the person the gallery is filtered to, drawn over
 * a gallery thumbnail so a cluster's photos show which face it is about. The
 * SVG's viewBox is the photo's own pixel frame and its aspect handling copies
 * the thumbnail's (``meet`` for a whole image, ``slice`` for an ``object-cover``
 * crop), so the outline lands on the face with no measuring.
 */
@Component({
  selector: 'app-face-focus-overlay',
  changeDetection: ChangeDetectionStrategy.Eager,
  host: { class: 'contents' },
  template: `
    @if (viewBox(); as vb) {
      <svg class="absolute inset-0 w-full h-full pointer-events-none z-10"
           [attr.viewBox]="vb"
           [attr.preserveAspectRatio]="cover() ? 'xMidYMid slice' : 'xMidYMid meet'"
           aria-hidden="true">
        @for (r of rects(); track $index) {
          <rect [attr.x]="r.x" [attr.y]="r.y" [attr.width]="r.w" [attr.height]="r.h"
                fill="transparent" stroke="#ef4444" stroke-width="3" vector-effect="non-scaling-stroke" />
        }
      </svg>
    }
  `,
})
export class FaceFocusOverlayComponent {
  private readonly api = inject(ApiService);

  readonly path = input.required<string>();
  /** The gallery's person filter: one id, or empty for none. */
  readonly personId = input('');
  readonly imageWidth = input<number | null>(null);
  readonly imageHeight = input<number | null>(null);
  /** True when the thumbnail is cropped to fill its tile (``object-cover``). */
  readonly cover = input(false);

  private readonly rows = signal<FaceRow[]>([]);

  /** The filtered person's id when it is exactly one. */
  private readonly focusId = computed(() => (/^\d+$/.test(this.personId()) ? Number(this.personId()) : null));

  readonly rects = computed<FocusRect[]>(() => {
    const id = this.focusId();
    const w = this.imageWidth();
    const h = this.imageHeight();
    if (id === null || !w || !h) return [];
    return this.rows()
      .filter((r): r is FaceRow & { box: number[] } => r.person_id === id && Array.isArray(r.box) && r.box.length === 4)
      .map(({ box: [x1, y1, x2, y2] }) => ({ x: x1 * w, y: y1 * h, w: (x2 - x1) * w, h: (y2 - y1) * h }));
  });

  protected readonly viewBox = computed(() => {
    const w = this.imageWidth();
    const h = this.imageHeight();
    return w && h && this.rects().length > 0 ? `0 0 ${w} ${h}` : null;
  });

  constructor() {
    effect(() => {
      const path = this.path();
      const id = this.focusId();
      if (id === null) {
        this.rows.set([]);
        return;
      }
      void this.load(path);
    });
  }

  private async load(path: string): Promise<void> {
    try {
      const res = await firstValueFrom(this.api.get<{ faces: FaceRow[] }>('/photo/faces', { path }));
      if (path === this.path()) this.rows.set(res.faces ?? []);
    } catch {
      if (path === this.path()) this.rows.set([]);
    }
  }
}
