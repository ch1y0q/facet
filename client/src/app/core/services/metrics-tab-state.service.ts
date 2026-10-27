import { Injectable, signal } from '@angular/core';

const METRICS_TAB_KEY = 'facet_photo_detail_tab';
export const METRICS_TABS = ['exif', 'quality', 'composition', 'technical', 'histogram'] as const;
export type MetricsTab = typeof METRICS_TABS[number];

function storedMetricsTab(): MetricsTab {
  try {
    const stored = localStorage.getItem(METRICS_TAB_KEY);
    return METRICS_TABS.find(tab => tab === stored) ?? 'exif';
  } catch {
    return 'exif';
  }
}

/**
 * The open metric tab, one per app rather than per component: the gallery is
 * kept alive behind photo detail, so a tab chosen there must reach the
 * gallery's panel on Back, not only the next component created.
 */
@Injectable({ providedIn: 'root' })
export class MetricsTabState {
  readonly tab = signal<MetricsTab>(storedMetricsTab());

  select(tab: MetricsTab): void {
    this.tab.set(tab);
    try {
      localStorage.setItem(METRICS_TAB_KEY, tab);
    } catch {
      // Storage blocked: the tab still switches, it is just not remembered.
    }
  }
}
