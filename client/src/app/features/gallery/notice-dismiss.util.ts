/** The gallery's floating notices the user closed in this browser tab, keyed by kind,
 *  each holding the signature the notice had when it was closed. A notice whose
 *  signature has since changed (another scope, another count) is a different notice
 *  and shows again. Kept in sessionStorage: a reload keeps it closed, a new tab starts
 *  clean, and closing never changes anything else. */
export const NOTICE_DISMISSALS_KEY = 'facet_notice_dismissals';

export type NoticeKind = 'review_progress' | 'review_bookmark' | 'hidden' | 'restore_hidden' | 'render_migration';

export type NoticeDismissals = Partial<Record<NoticeKind, string>>;

export function readNoticeDismissals(): NoticeDismissals {
  try {
    const value: unknown = JSON.parse(sessionStorage.getItem(NOTICE_DISMISSALS_KEY) ?? '{}');
    return value && typeof value === 'object' && !Array.isArray(value) ? value as NoticeDismissals : {};
  } catch {
    return {};
  }
}

export function saveNoticeDismissals(dismissals: NoticeDismissals): void {
  try {
    sessionStorage.setItem(NOTICE_DISMISSALS_KEY, JSON.stringify(dismissals));
  } catch { /* Storage denied/full: the close still holds until reload. */ }
}
