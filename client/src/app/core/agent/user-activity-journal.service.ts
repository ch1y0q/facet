import { Injectable, inject } from '@angular/core';
import { NavigationEnd, Router } from '@angular/router';

export type UserActivityKind =
  | 'rating'
  | 'reject'
  | 'favorite'
  | 'review_mark'
  | 'review_group'
  | 'tags'
  | 'album'
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

/**
 * What the user did in this tab, newest last, in memory for the session. A reader asks for
 * everything after a seq it already holds; reading consumes nothing. Only user entry points
 * record: assistant writes (`AssistantChangesService`, `refreshPaths`) never do, and nothing
 * records while a UI tool runs (`suppress`), so the agent's own navigation is not reported
 * back to it as the user's.
 */
@Injectable({ providedIn: 'root' })
export class UserActivityJournal {
  private readonly router = inject(Router);
  private entries: UserActivityEntry[] = [];
  private seq = 0;
  private suppressed = 0;

  constructor() {
    this.router.events.subscribe(event => {
      if (event instanceof NavigationEnd) this.record('navigate', [], event.urlAfterRedirects);
    });
  }

  record(kind: UserActivityKind, paths: readonly string[], value: unknown = null): void {
    if (this.suppressed > 0) return;
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
    const newer = this.entries.filter(entry => entry.seq > since);
    const truncated = newer.length > ACTIVITY_MAX_ITEMS;
    return { items: truncated ? newer.slice(-ACTIVITY_MAX_ITEMS) : newer, until: this.seq, truncated };
  }
}
