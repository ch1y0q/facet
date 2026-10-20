import { Injectable, signal } from '@angular/core';

/** Index of the A/B compare tab inside the comparison page's tab group. */
export const COMPARE_AB_TAB_INDEX = 1;

/** Pair-selection strategy the A/B tab starts with. */
export const DEFAULT_COMPARE_STRATEGY = 'uncertainty';

@Injectable({ providedIn: 'root' })
export class CompareFiltersService {
  readonly selectedCategory = signal<string>('');
  /** Pair-selection strategy of the A/B tab; kept here so a UI tool can set it without touching the page. */
  readonly strategy = signal<string>(DEFAULT_COMPARE_STRATEGY);
  /** Tab shown by the comparison page; the page writes it on every tab change, a UI tool may set it. */
  readonly activeTab = signal<number>(0);
}
