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

function load(): KeymapConfig {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_KEYMAP };
    const saved = JSON.parse(raw) as Partial<KeymapConfig>;
    const out = { ...DEFAULT_KEYMAP };
    for (const action of Object.keys(DEFAULT_KEYMAP) as (keyof KeymapConfig)[]) {
      const v = saved[action];
      if (typeof v === 'string' && v.length === 1) out[action] = v.toLowerCase();
    }
    return out;
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

  setKey(action: keyof KeymapConfig, key: string): void {
    const k = key.length === 1 ? key.toLowerCase() : key;
    this.keymap.update(m => ({ ...m, [action]: k }));
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(this.keymap())); } catch { /* session-only */ }
  }

  resetAll(): void {
    this.keymap.set({ ...DEFAULT_KEYMAP });
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(DEFAULT_KEYMAP)); } catch { /* ignore */ }
  }

  /** The key for an action, from the current mapping. */
  key(action: keyof KeymapConfig): string {
    return this.keymap()[action];
  }
}
