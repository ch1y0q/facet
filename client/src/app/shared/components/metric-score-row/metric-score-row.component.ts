import { ChangeDetectionStrategy, Component, input } from '@angular/core';
import { MetricDistribution } from '../../utils/metric-distribution';
import { MetricRankComponent } from '../metric-rank/metric-rank.component';

/**
 * One score as a stat: its name on a first line, then the value large (projected,
 * so each row keeps its own formatting) beside the library distribution with the
 * value's bar lit. Without a distribution, the name and the value only.
 */
@Component({
  selector: 'app-metric-score-row',
  imports: [MetricRankComponent],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'block py-1.5' },
  template: `
    <span class="block truncate text-[var(--mat-sys-on-surface-variant)]">{{ label() }}</span>
    <div class="flex items-center gap-4 mt-1 pl-2 pr-1">
      <span class="w-12 shrink-0 text-lg font-semibold leading-tight tabular-nums text-[var(--mat-sys-primary)]"><ng-content /></span>
      @if (range(); as range) {
        <app-metric-rank class="min-w-0 flex-1" [range]="range" [value]="value()" [percent]="percent()" />
      }
    </div>
  `,
})
export class MetricScoreRowComponent {
  readonly label = input.required<string>();
  readonly range = input<MetricDistribution | undefined>(undefined);
  readonly value = input<number | null | undefined>(undefined);
  /** The metric is a 0-1 fraction shown as a percentage; its range is described the same way. */
  readonly percent = input(false);
}
