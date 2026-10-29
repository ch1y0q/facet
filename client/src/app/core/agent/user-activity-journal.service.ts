import { DestroyRef, Injectable, effect, inject, signal, untracked } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';
import { AuthService } from '../services/auth.service';
import { pathOf } from '../../shared/utils/url-path';

export type UserActivityKind =
  | 'stack'
  | 'rating'
  | 'reject'
  | 'review'
  | 'favorite'
  | 'cull_confirm'
  | 'cull_skip'
  | 'tags'
  | 'album'
  | 'person'
  | 'junk'
  | 'compare'
  | 'filters'
  | 'navigate';

export interface UserActivityEntry {
  seq: number;
  kind: UserActivityKind;
  paths: string[];
  /** True when more paths were acted on than the entry keeps. */
  truncated: boolean;
  value: unknown;
  /** Epoch milliseconds. */
  at: number;
}

export interface UserActivityReport {
  items: UserActivityEntry[];
  /** The latest seq issued; pass it back as `activity_since` to see only what is newer. */
  until: number;
  /** True when older matching items were dropped to fit the item cap. */
  truncated: boolean;
}

export const ACTIVITY_MAX_PATHS = 20;
export const ACTIVITY_MAX_ITEMS = 50;
/** Entries kept in memory; the report never needs more than the item cap, a margin covers a late reader. */
const JOURNAL_CAPACITY = 500;
/** Quiet time after the last filter edit before the merged `filters` entry is written. */
export const FILTER_FLUSH_MS = 1000;
const FILTER_MAX_KEYS = 12;
const FILTER_MAX_STRING = 80;

export type FilterChange = { changed: Record<string, unknown> } | { reset: true };

interface PendingFilters {
  reset: boolean;
  changed: Record<string, string | number | boolean | null>;
}

/**
 * What the user did in this tab, newest last, in memory for the session. A reader asks for
 * everything after a seq it already holds; reading consumes nothing. Only user entry points
 * record: assistant writes (`AssistantChangesService`, `refreshPaths`) never do, and nothing
 * records while a UI tool runs (`suppress`), so the agent's own navigation is not reported
 * back to it as the user's. A new UI surface that mutates must call `record` itself: nothing
 * is observed implicitly, so an action nobody records is never reported. A real user action that
 * lands while a UI tool runs is dropped too, because `suppress` is a global counter.
 */
@Injectable({ providedIn: 'root' })
export class UserActivityJournal {
  private readonly router = inject(Router);
  private readonly auth = inject(AuthService);
  /** The darkroom's lightbox photo; here because the darkroom's `CullingStore` is component-scoped, invisible to root services. */
  readonly darkroomFocus = signal<string | null>(null);
  private entries: UserActivityEntry[] = [];
  private seq = 0;
  private suppressed = 0;
  private pendingFilters: PendingFilters | null = null;
  private filterTimer: ReturnType<typeof setTimeout> | null = null;
  private lastPath: string | null = null;

  constructor() {
    let first = true;
    effect(() => {
      this.auth.identity();
      untracked(() => {
        // `seq` is kept: a cursor held from before the change must never re-read or skip an item.
        if (first) first = false;
        else {
          this.entries = [];
          this.dropPendingFilters();
        }
      });
    });
    inject(DestroyRef).onDestroy(() => this.dropPendingFilters());
    this.router.events.subscribe(event => {
      if (!(event instanceof NavigationEnd)) return;
      const url = event.urlAfterRedirects;
      const path = pathOf(url);
      // The photo detail's query names the photo it shows, so stepping to another one is a real navigation.
      const page = path === '/photo' ? `${path}?path=${new URLSearchParams(url.split('#')[0].split('?')[1] ?? '').get('path') ?? ''}` : path;
      const samePage = page === this.lastPath;
      this.lastPath = page;
      // Any other query-only navigation is the URL sync of a filter edit (or a tab switch): the edit has its own entry.
      if (!samePage) this.record('navigate', [], event.urlAfterRedirects);
    });
  }

  record(kind: UserActivityKind, paths: readonly string[], value: unknown = null): void {
    this.flushFilters();
    if (this.suppressed > 0) return;
    this.append(kind, paths, value);
  }

  /**
   * A gallery filter edit, merged with the ones that follow it into one `filters` entry written
   * after a quiet second. Suppression is decided here, at edit time: an assistant-driven change
   * is never buffered, and a buffered user edit is written whatever happens later.
   */
  recordFilters(change: FilterChange): void {
    if (this.suppressed > 0) return;
    const pending = this.pendingFilters ?? { reset: false, changed: {} };
    if ('reset' in change) {
      pending.reset = true;
      pending.changed = {};
    } else {
      for (const [key, raw] of Object.entries(change.changed)) {
        const value = sanitizeFilterValue(raw);
        if (value === undefined) continue;
        if (!(key in pending.changed) && Object.keys(pending.changed).length >= FILTER_MAX_KEYS) continue;
        pending.changed[key] = value;
      }
    }
    if (!pending.reset && Object.keys(pending.changed).length === 0) return;
    this.pendingFilters = pending;
    if (this.filterTimer) clearTimeout(this.filterTimer);
    this.filterTimer = setTimeout(() => this.flushFilters(), FILTER_FLUSH_MS);
  }

  private flushFilters(): void {
    const pending = this.pendingFilters;
    this.dropPendingFilters();
    if (!pending) return;
    const hasChanged = Object.keys(pending.changed).length > 0;
    this.append('filters', [], {
      ...(pending.reset ? { reset: true } : {}),
      ...(hasChanged ? { changed: pending.changed } : {}),
    });
  }

  private dropPendingFilters(): void {
    if (this.filterTimer) clearTimeout(this.filterTimer);
    this.filterTimer = null;
    this.pendingFilters = null;
  }

  private append(kind: UserActivityKind, paths: readonly string[], value: unknown): void {
    this.seq += 1;
    const entry: UserActivityEntry = {
      seq: this.seq,
      kind,
      paths: paths.slice(0, ACTIVITY_MAX_PATHS),
      truncated: paths.length > ACTIVITY_MAX_PATHS,
      value,
      at: Date.now(),
    };
    this.entries = [...this.entries, entry].slice(-JOURNAL_CAPACITY);
  }

  /** Runs `fn` with recording off; the scope ends when its promise settles. */
  async suppress<T>(fn: () => Promise<T>): Promise<T> {
    this.suppressed += 1;
    try {
      return await fn();
    } finally {
      this.suppressed -= 1;
    }
  }

  /** The entries with `seq > since`, at most the item cap (the oldest dropped). Stateless. */
  since(since = 0): UserActivityReport {
    this.flushFilters();
    const newer = this.entries.filter(entry => entry.seq > since);
    const truncated = newer.length > ACTIVITY_MAX_ITEMS;
    return { items: truncated ? newer.slice(-ACTIVITY_MAX_ITEMS) : newer, until: this.seq, truncated };
  }
}

/** A user-typed name as an entry carries it: capped, and untrusted data to its reader. */
export function activityName(name: string): string {
  return name.slice(0, FILTER_MAX_STRING);
}

function sanitizeFilterValue(raw: unknown): string | number | boolean | null | undefined {
  if (raw === null || typeof raw === 'number' || typeof raw === 'boolean') return raw;
  if (typeof raw === 'string') return raw.slice(0, FILTER_MAX_STRING);
  return undefined;
}
