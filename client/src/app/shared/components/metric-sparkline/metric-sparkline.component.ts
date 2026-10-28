import { ChangeDetectionStrategy, Component, computed, input } from '@angular/core';
import { bucketIndexOf, MetricDistribution, normalizeBars } from '../../utils/metric-distribution';

/**
 * A metric's library-wide distribution as a row of bars; given a value, the bar
 * it falls in is lit. Decorative: whoever shows it says in words what it means.
 */
@Component({
  selector: 'app-metric-sparkline',
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block h-3' },
  template: `
    <div class="flex items-end gap-px h-full px-2" aria-hidden="true">
      @for (h of bars(); track $index) {
        <span class="flex-1 min-h-0.5 rounded-sm bg-[var(--mat-sys-primary)]"
              [class.opacity-25]="$index !== lit()"
              [style.height.%]="h"></span>
      }
    </div>
  `,
})
export class MetricSparklineComponent {
  readonly range = input.required<MetricDistribution>();
  readonly value = input<number | null | undefined>(undefined);

  protected readonly bars = computed(() => normalizeBars(this.range().buckets));

  protected readonly lit = computed(() => {
    const value = this.value();
    return value === null || value === undefined || !Number.isFinite(value) ? -1 : bucketIndexOf(this.range(), value);
  });
}
