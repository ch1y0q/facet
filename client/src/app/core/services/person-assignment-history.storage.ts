/** Private browser-local IDs. Logout removes all identities on a shared browser. */
export const PERSON_ASSIGNMENT_HISTORY_KEY = 'facet_person_assignments_v1';

export function clearPersonAssignmentHistory(): void {
  try { localStorage.removeItem(PERSON_ASSIGNMENT_HISTORY_KEY); }
  catch { /* Storage may be disabled; logout must still complete. */ }
}
