import { Injectable, effect, inject, signal, untracked } from '@angular/core';
import { Observable, Subject } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { InpageChangeNotifier } from './inpage-change-notifier.service';

/** One coalesced burst of assistant writes: the changed paths, or null when the scope is not enumerable (reload the view). */
export interface AssistantChangeBatch {
  paths: string[] | null;
  /** The number the "Assistant changed N photos" notice shows: max(unique paths, reported count). */
  count?: number;
}

export interface AssistantChangeReport {
  /** The tool that wrote, for the activity log. */
  tool?: string;
  paths: string[] | null;
  count: number | null;
}

/** One line of the activity log: an assistant write, or a tool call that drove this tab. */
export interface ActivityEntry {
  id: number;
  at: number;
  kind: 'write' | 'ui';
  tool: string;
  count: number | null;
  paths: string[] | null;
}

export const ACTIVITY_LIMIT = 50;
export const ACTIVE_MS = 4000;
export const CHANGES_DEBOUNCE_MS = 400;
export const CHANGES_MAX_WAIT_MS = 2000;

/**
 * The single client entry for "the assistant changed photos", fed by bridge `changed` frames and by in-page
 * `/api/mcp/call` responses. Reports within a burst are merged into one batch (a Set of paths; one null report
 * makes the whole batch null), flushed on a 400 ms trailing debounce capped at 2 s, and announced once through
 * `batch$` and once to the snackbar notifier.
 */
@Injectable({ providedIn: 'root' })
export class AssistantChangesService {
  private readonly notifier = inject(InpageChangeNotifier);
  private readonly auth = inject(AuthService);
  private readonly subject = new Subject<AssistantChangeBatch>();
  /** Emits one batch per burst, after the debounce. */
  readonly batch$: Observable<AssistantChangeBatch> = this.subject.asObservable();

  private readonly entries = signal<ActivityEntry[]>([]);
  /** The assistant's recent activity, newest first, capped at 50; session-only. */
  readonly activity = this.entries.asReadonly();
  private readonly activeFlag = signal(false);
  /** True for 4 s after any assistant event. */
  readonly active = this.activeFlag.asReadonly();
  private activeTimer: ReturnType<typeof setTimeout> | null = null;
  private nextId = 1;

  private paths = new Set<string>();
  private sticky = false;
  private extra = 0;
  private pending = false;
  private startedAt = 0;
  private timer: ReturnType<typeof setTimeout> | null = null;

  constructor() {
    let first = true;
    effect(() => {
      this.auth.identity();
      untracked(() => {
        if (first) first = false;
        else this.drop();
      });
    });
  }

  /** A tool call reached this tab. Read-only `ui_get_*` calls light the chip but are not listed. */
  noteCall(tool: string): void {
    this.light();
    if (!tool.startsWith('ui_get_')) this.append('ui', tool, null, null);
  }

  private light(): void {
    this.activeFlag.set(true);
    if (this.activeTimer !== null) clearTimeout(this.activeTimer);
    this.activeTimer = setTimeout(() => {
      this.activeTimer = null;
      this.activeFlag.set(false);
    }, ACTIVE_MS);
  }

  private append(kind: ActivityEntry['kind'], tool: string, count: number | null, paths: string[] | null): void {
    const entry: ActivityEntry = { id: this.nextId++, at: Date.now(), kind, tool, count, paths };
    this.entries.update(list => [entry, ...list].slice(0, ACTIVITY_LIMIT));
  }

  report(report: AssistantChangeReport): void {
    this.light();
    this.append('write', report.tool ?? '', report.count ?? report.paths?.length ?? null, report.paths);
    const now = Date.now();
    if (!this.pending) {
      this.pending = true;
      this.startedAt = now;
    }
    if (report.paths === null) this.sticky = true;
    else for (const path of report.paths) this.paths.add(path);
    // A null-path report counts whole; a path report only adds what its paths do not already say.
    this.extra += report.paths === null ? (report.count ?? 0) : Math.max(0, (report.count ?? 0) - report.paths.length);
    if (this.timer !== null) clearTimeout(this.timer);
    const delay = Math.min(CHANGES_DEBOUNCE_MS, Math.max(0, this.startedAt + CHANGES_MAX_WAIT_MS - now));
    this.timer = setTimeout(() => this.flush(), delay);
  }

  private flush(): void {
    this.timer = null;
    const notice = Math.max(this.paths.size, this.sticky ? this.extra : this.paths.size + this.extra);
    const batch: AssistantChangeBatch = { paths: this.sticky ? null : [...this.paths], count: notice };
    this.reset();
    // The notifier first: a subscriber that opens its own actionable snackbar then wins the single snackbar slot.
    this.notifier.notify(notice);
    this.subject.next(batch);
  }

  private drop(): void {
    this.entries.set([]);
    if (this.activeTimer !== null) clearTimeout(this.activeTimer);
    this.activeTimer = null;
    this.activeFlag.set(false);
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = null;
    this.reset();
  }

  private reset(): void {
    this.paths = new Set<string>();
    this.sticky = false;
    this.extra = 0;
    this.pending = false;
  }
}
