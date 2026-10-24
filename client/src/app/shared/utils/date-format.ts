/** Convert a Date to an ISO date string (YYYY-MM-DD), or empty string if null. */
export function toIsoDateString(d: Date | null): string {
  if (!d) return '';
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/**
 * A scope date as a plain `YYYY-MM-DD` when it is the EXIF form of a whole-day edge (`from` at 00:00:00, `to` at
 * 23:59:59), which is what the server's normaliser makes of a date-only value and reads back identically; any
 * other value (a scene's real times) is returned unchanged, since a plain date would widen it.
 */
export function plainScopeDate(value: string | null | undefined, edge: 'from' | 'to'): string | null {
  if (!value) return null;
  const m = /^(\d{4}):(\d{2}):(\d{2}) (\d{2}:\d{2}:\d{2})$/.exec(value);
  if (!m || m[4] !== (edge === 'from' ? '00:00:00' : '23:59:59')) return value;
  return `${m[1]}-${m[2]}-${m[3]}`;
}
