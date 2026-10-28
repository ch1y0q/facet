import { Injectable, signal } from '@angular/core';

/** The user-customisable keyboard actions. Each entry maps an action id to
 *  the (lowercased) primary key that triggers it on the gallery and photo
 *  pages. Modifiers (Ctrl/Cmd/Alt) are not remappable. */
export interface KeymapConfig {
  favourite: string;
  reject: string;
  keep: string;
  focusSearch: string;
  toggleSidebar: string;
  swapLayout: string;
}

export const DEFAULT_KEYMAP: KeymapConfig = {
  favourite: 'f',
  reject: 'x',
  keep: 'k',
  focusSearch: '/',
  toggleSidebar: 'b',
  swapLayout: 'v',
};

const STORAGE_KEY = 'facet_keymap';

/** Keys no action may take: the digits drive rating (and the 0 reject
 *  alias), Space selects the focused photo, ? opens the shortcut reference. */
const RESERVED_KEYS = new Set(['0', '1', '2', '3', '4', '5', '6', '7', '8', '9', ' ', '?']);

/** The stored form of a pressed key — lowercased, one character, not
 *  reserved — or null when no action may take it. Lowercasing can lengthen a
 *  character (`İ` becomes two code units), so length is checked after it. */
export function assignableKey(key: string): string | null {
  const k = key.toLowerCase();
  return k.length === 1 && !RESERVED_KEYS.has(k) ? k : null;
}

/** A saved key that is reserved or that two actions share (a hand edit, or an
 *  older save meeting a newer rule) falls back to that action's default, so
 *  one keystroke never fires two actions. If that default is itself already
 *  taken by another saved key, nothing short of the full defaults is safe. */
function load(): KeymapConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_KEYMAP };
    const saved = JSON.parse(raw) as Partial<Record<keyof KeymapConfig, unknown>>;
    const actions = Object.keys(DEFAULT_KEYMAP) as (keyof KeymapConfig)[];
    const keys = actions.map(action => {
      const v = saved[action];
      return typeof v === 'string' ? assignableKey(v) : null;
    });
    const out = { ...DEFAULT_KEYMAP };
    actions.forEach((action, i) => {
      const k = keys[i];
      if (k && keys.indexOf(k) === keys.lastIndexOf(k)) out[action] = k;
    });
    return new Set(Object.values(out)).size === actions.length ? out : { ...DEFAULT_KEYMAP };
  } catch {
    return { ...DEFAULT_KEYMAP };
  }
}

/** Per-browser keyboard mapping for the gallery and photo-page actions,
 *  persisted in localStorage. Defaults match the built-in bindings; the user
 *  can reassign the primary key of each action from the settings dialog. */
@Injectable({ providedIn: 'root' })
export class KeyboardMappingService {
  readonly keymap = signal<KeymapConfig>(load());

  /** Assigns `key` to `action`. Refuses a key no action may take
   *  (`'reserved'`) or one another action holds (`'in_use'`). */
  setKey(action: keyof KeymapConfig, key: string): 'reserved' | 'in_use' | null {
    const k = assignableKey(key);
    if (!k) return 'reserved';
    const map = this.keymap();
    if ((Object.keys(map) as (keyof KeymapConfig)[]).some(a => a !== action && map[a] === k)) return 'in_use';
    this.save({ ...map, [action]: k });
    return null;
  }

  resetAll(): void {
    this.save({ ...DEFAULT_KEYMAP });
  }

  private save(map: KeymapConfig): void {
    this.keymap.set(map);
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(map)); } catch { /* session-only */ }
  }

  /** The key for an action, from the current mapping. */
  key(action: keyof KeymapConfig): string {
    return this.keymap()[action];
  }
}
