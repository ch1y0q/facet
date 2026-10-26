import { signal } from '@angular/core';

/** Private queue filters for every identity using this browser. */
export const REVIEW_QUEUE_STORAGE_KEY = 'facet_review_queues_v1';
const clearVersion = signal(0);
/** Invalidate cached bookmarks and reads that started before logout, even when
 *  the single-user identity stays `0|`. Normal status checks leave it alone. */
export const reviewQueueClearVersion = clearVersion.asReadonly();

export function clearReviewQueues(): void {
  clearVersion.update(version => version + 1);
  try { localStorage.removeItem(REVIEW_QUEUE_STORAGE_KEY); }
  catch { /* Storage may be disabled; logout must still complete. */ }
}
