export function basename(path: string): string {
  return path.split(/[\\/]/).pop() ?? path;
}

/** Copy `lines` one per row, through the same clipboard-then-execCommand route as `copyText`; rejects when neither worked. */
export async function copyLines(lines: string[]): Promise<void> {
  if (!await copyText(lines.join('\n'))) throw new Error('The clipboard is not available');
}

/**
 * Copy `text`; resolves false when neither route worked. `navigator.clipboard` is undefined on
 * plain-http LAN (no secure context), so fall back to a hidden textarea and `execCommand`.
 */
export async function copyText(text: string): Promise<boolean> {
  try {
    await navigator.clipboard.writeText(text);
    return true;
  } catch {
    const area = document.createElement('textarea');
    area.value = text;
    area.setAttribute('readonly', '');
    area.style.position = 'fixed';
    area.style.opacity = '0';
    document.body.appendChild(area);
    area.select();
    try {
      return document.execCommand('copy');
    } finally {
      area.remove();
    }
  }
}
