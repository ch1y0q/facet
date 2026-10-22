import { Injectable, inject, signal } from '@angular/core';
import type { components } from '../api/schema';
import { UserActivityJournal } from './user-activity-journal.service';

/** The auto-cull request a plan was computed from: the body of `POST /culling/plan` minus the digest. */
export type CullPlanRequest = Omit<components['schemas']['CullingPlanBody'], 'expected_digest'>;

/** What the tab holds about the assistant's plan: the digest to verify, the request to reproduce it, and where to look. */
export interface CullPlanPin {
  digest: string;
  request: CullPlanRequest;
  /** 1-based plan group number the assistant asked the tab to land on. */
  focusNumber?: number;
}

/** One plan group as the store registers it once the plan has loaded. */
export interface CullPlanEntryInput {
  /** `groupKey()` of the group: `${group_id}_${type}`. */
  key: string;
  type: string;
  group_id: number;
  number: number;
  /** Every photo of the group, in display order. */
  paths: string[];
  /** The plan's keepers. */
  keep_paths: string[];
}

export interface CullPlanChangedGroup {
  type: string;
  group_id: number;
  number: number;
  keep_paths: string[];
  reject_paths: string[];
}

/** The read model `ui_get_context.culling` reports; plan group numbers are the plan's own, 1-based. */
export interface CullPlanSnapshot {
  plan_digest: string;
  groups_total: number;
  /** Groups whose confirm has landed. */
  confirmed: number[];
  /** Groups the user flipped away from the plan and has not confirmed or skipped yet. */
  pending: number[];
  /** Every group (confirmed or not) whose keepers differ from the plan's, with the paths to pass as overrides. */
  changed: CullPlanChangedGroup[];
  /** Plan groups neither confirmed, skipped nor flipped. */
  untouched: number;
  truncated: boolean;
}

type EntryStatus = 'open' | 'confirmed' | 'skipped';

interface Entry extends CullPlanEntryInput {
  status: EntryStatus;
  /** Current keepers, in `paths` order. */
  current: string[];
}

interface Meta {
  total: number;
  truncated: boolean;
}

/**
 * The assistant's culling plan as the tab sees it. Root-scoped on purpose: the darkroom's `CullingStore`
 * lives one visit, but the plan must survive the route navigation `ui_show_culling_plan` triggers and stay
 * readable by `ui_get_context` while the user sits on another page.
 *
 * The store reports into it (`register`, `recordSelection`, `recordConfirm`, `recordSkip`); a confirm or
 * skip is reported only once it has landed, and that is also the only moment the user journal hears of it.
 */
@Injectable({ providedIn: 'root' })
export class AssistantCullPlanService {
  private readonly journal = inject(UserActivityJournal);

  /** The held plan, or null in manual mode. */
  readonly pin = signal<CullPlanPin | null>(null);

  private entries = new Map<string, Entry>();
  private meta: Meta | null = null;
  private decisionsProbe: (() => boolean) | null = null;

  /** Hold a plan. A different digest forgets what was learned about the previous one, so a snapshot never mixes two plans. */
  setPin(pin: CullPlanPin): void {
    if (this.pin()?.digest !== pin.digest) {
      this.entries = new Map();
      this.meta = null;
    }
    this.pin.set(pin);
  }

  /** Move the landing group without touching the digest or the request. */
  setFocus(focusNumber: number | undefined): void {
    this.pin.update(pin => (pin ? { ...pin, focusNumber } : pin));
  }

  /** Leave plan mode: the pin and everything learned about the plan go. */
  clear(): void {
    this.pin.set(null);
    this.entries = new Map();
    this.meta = null;
  }

  /** The plan loaded: replace the read model with its groups. `meta.total` counts the whole plan, not only `entries`. */
  register(entries: CullPlanEntryInput[], meta: Meta): void {
    this.entries = new Map(entries.map(e => [e.key, { ...e, status: 'open' as const, current: [...e.keep_paths] }]));
    this.meta = meta;
  }

  /** The user's current keepers of a group (a toggle, an exclusive pick, an undo). */
  recordSelection(key: string, kept: Iterable<string>): void {
    const entry = this.entries.get(key);
    if (!entry) return;
    const keptSet = new Set(kept);
    entry.current = entry.paths.filter(path => keptSet.has(path));
  }

  /** A confirm landed on the server. */
  recordConfirm(key: string, kept: string[]): void {
    const entry = this.entries.get(key);
    if (!entry) return;
    this.recordSelection(key, kept);
    entry.status = 'confirmed';
    this.journal.record('cull_confirm', entry.current, {
      type: entry.type,
      group_id: entry.group_id,
      number: entry.number,
      keep: entry.current.length,
      reject: entry.paths.length - entry.current.length,
    });
  }

  /** A skip's cooldown elapsed. */
  recordSkip(key: string): void {
    const entry = this.entries.get(key);
    if (!entry) return;
    entry.status = 'skipped';
    this.journal.record('cull_skip', entry.paths, { type: entry.type, group_id: entry.group_id, number: entry.number });
  }

  /**
   * The mounted darkroom reports whether it holds decisions a new plan would discard (a manual feed's
   * choices, a confirm still counting down). Returns the function that withdraws the probe.
   */
  registerDecisionsProbe(probe: () => boolean): () => void {
    this.decisionsProbe = probe;
    return () => {
      if (this.decisionsProbe === probe) this.decisionsProbe = null;
    };
  }

  /**
   * True when swapping the plan would discard something the user did on the darkroom now on screen: its
   * own probe says so, or an unconfirmed plan group sits flipped. With no darkroom mounted those decisions
   * went with it, so nothing is at stake.
   */
  hasUnsavedDecisions(): boolean {
    const probe = this.decisionsProbe;
    return probe !== null && (probe() || this.hasUnconfirmedFlips());
  }

  /** True when an unconfirmed group's keepers differ from the plan: re-seeding would throw that away. */
  hasUnconfirmedFlips(): boolean {
    return [...this.entries.values()].some(e => e.status === 'open' && differs(e));
  }

  /** Null in manual mode or before the plan loaded. */
  snapshot(): CullPlanSnapshot | null {
    const pin = this.pin();
    if (!pin || !this.meta) return null;
    const all = [...this.entries.values()].sort((a, b) => a.number - b.number);
    const confirmed = all.filter(e => e.status === 'confirmed').map(e => e.number);
    const pending = all.filter(e => e.status === 'open' && differs(e)).map(e => e.number);
    const skipped = all.filter(e => e.status === 'skipped').length;
    const changed = all.filter(e => e.status !== 'skipped' && differs(e)).map(e => ({
      type: e.type,
      group_id: e.group_id,
      number: e.number,
      keep_paths: e.current,
      reject_paths: e.paths.filter(path => !e.current.includes(path)),
    }));
    return {
      plan_digest: pin.digest,
      groups_total: this.meta.total,
      confirmed,
      pending,
      changed,
      untouched: Math.max(0, this.meta.total - confirmed.length - skipped - pending.length),
      truncated: this.meta.truncated,
    };
  }
}

function differs(entry: Entry): boolean {
  return entry.current.length !== entry.keep_paths.length
    || entry.current.some(path => !entry.keep_paths.includes(path));
}
