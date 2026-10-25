import { Injectable, signal } from '@angular/core';
import { CARD_ACTION_IDS, CardActionsConfig, DEFAULT_CARD_ACTIONS } from '../../shared/components/photo-card/card-actions';

const STORAGE_KEY = 'facet_card_actions';

function load(): CardActionsConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return DEFAULT_CARD_ACTIONS;
    const saved = JSON.parse(raw) as Partial<CardActionsConfig>;
    // An order saved by an older build misses actions added since; append the
    // newcomers so they exist (in their default visibility) rather than vanish.
    const order = (saved.order ?? []).filter(id => CARD_ACTION_IDS.includes(id));
    for (const id of CARD_ACTION_IDS) {
      if (!order.includes(id)) order.push(id);
    }
    return {
      order,
      hidden: (saved.hidden ?? []).filter(id => order.includes(id)),
    };
  } catch {
    return DEFAULT_CARD_ACTIONS;
  }
}

/** Per-browser layout of the photo card's hover buttons, persisted in
 *  localStorage like the thumbnail size and the darkroom sliders — a viewing
 *  preference of this browser, not library data. */
@Injectable({ providedIn: 'root' })
export class CardActionsService {
  readonly config = signal<CardActionsConfig>(load());

  set(config: CardActionsConfig): void {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(config));
    } catch { /* private mode: keep the session value */ }
    this.config.set(config);
  }

  reset(): void {
    this.set(DEFAULT_CARD_ACTIONS);
  }
}
