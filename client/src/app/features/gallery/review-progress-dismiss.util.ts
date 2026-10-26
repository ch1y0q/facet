/** Whether the gallery's review-progress banner is shown, persisted in
 *  localStorage (per browser) and toggled from the user menu — the banner is
 *  a culling-workflow aid, and users who just browse can turn it off for
 *  good instead of dismissing the same fixture every visit. */
export const REVIEW_PROGRESS_VISIBLE_KEY = 'facet_review_progress_visible';

export function readReviewProgressVisible(): boolean {
  try {
    return localStorage.getItem(REVIEW_PROGRESS_VISIBLE_KEY) !== 'false';
  } catch {
    return true;
  }
}
