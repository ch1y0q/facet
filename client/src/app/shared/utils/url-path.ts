/** The path of a router URL: everything before the query string or fragment. */
export function pathOf(url: string): string {
  return url.split('?')[0].split('#')[0];
}
