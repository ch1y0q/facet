const MAX_CODE_POINTS = 200;
const MIN_CODE_POINTS = 3;

/** Client-side guard for online place search (api/place_search.py): the trimmed text, which is what gets sent, needs
 * 3..200 code points and no control character (code point below 32). Returns the trimmed query, or null when the
 * server would refuse it. */
export function normalizeOnlineQuery(raw: string): string | null {
  const query = raw.trim();
  const length = Array.from(query).length;
  if (length < MIN_CODE_POINTS || length > MAX_CODE_POINTS) return null;
  return Array.from(query).some(char => char.codePointAt(0)! < 32) ? null : query;
}
