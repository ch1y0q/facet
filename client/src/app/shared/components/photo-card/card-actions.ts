/** The hover actions a photo card's top row can carry, in display order.
 *
 *  Lives beside the card component so both the card (shared) and the gallery's
 *  configuration service (features) can import it without a shared → features
 *  edge. */

export type CardActionId =
  | 'similar'       // find-similar menu (feature-gated server-side)
  | 'critique'      // why-this-score dialog
  | 'embed'         // write metadata to file (edition)
  | 'assign_face'   // assign unassigned faces (edition, per-photo)
  | 'duplicate_set' // open this photo's duplicate group in the gallery
  | 'burst_set'     // open this photo's burst group in the gallery
  | 'sequence_set'  // open this photo's bracket/panorama set in the gallery
  | 'open_detail';  // open the photo page

/** How a set-opening action reaches the gallery's set scope. */
export type CardSetKind = 'burst' | 'duplicate' | 'sequence';

export interface CardActionsConfig {
  /** Every known action, in the order the card renders the visible ones. */
  order: CardActionId[];
  /** Actions turned off. A member of `order` but not `hidden` is visible. */
  hidden: CardActionId[];
}

/** The card as it has always looked, plus the duplicate-group button: the four
 *  original buttons, then the set openings and the photo-page shortcut, which
 *  an install shows only after opting in. */
export const DEFAULT_CARD_ACTIONS: CardActionsConfig = {
  order: ['similar', 'critique', 'embed', 'assign_face', 'duplicate_set', 'burst_set', 'sequence_set', 'open_detail'],
  hidden: ['burst_set', 'sequence_set', 'open_detail'],
};

export const CARD_ACTION_IDS: readonly CardActionId[] = DEFAULT_CARD_ACTIONS.order;
