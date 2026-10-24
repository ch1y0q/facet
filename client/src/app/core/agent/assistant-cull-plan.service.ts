import { Injectable, inject, signal } from '@angular/core';
import type { components } from '../api/schema';
import { plainScopeDate } from '../../shared/utils/date-format';
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
  /** The user's keepers carried over from the plan a re-plan replaced; absent means "the plan's keepers". */
  current_paths?: string[];
  /** A group the user confirmed on the plan a re-plan replaced: registered as confirmed, without a new journal entry. */
  confirmed?: boolean;
}

/** A group's photos and the keepers the user chose: an open flip or a confirmed group a re-plan carries over. */
export interface CullPlanFlip {
  paths: string[];
  current: string[];
}

export type CullSuggestionAction = 'keep' | 'reject';

/** The assistant's proposal for one photo; `reason` is untrusted text and only ever rendered as text. */
export interface CullSuggestion {
  action: CullSuggestionAction;
  reason: string;
}

/** The held suggestions, keyed by photo path (a note by the path of one member photo of its group). */
export interface CullSuggestions {
  photos: ReadonlyMap<string, CullSuggestion>;
  notes: ReadonlyMap<string, string>;
}

/** What `ui_suggest_culling` answers, minus the digest the handler adds. */
export interface CullSuggestOutcome {
  applied: string[];
  redundant: string[];
  closed: string[];
  missing: string[];
  groups_applied: string[];
  groups_missing: string[];
  /** Notes refused because their group is confirmed, skipped or counting down. */
  groups_closed: string[];
  /** Photo suggestions held after the call: the same count `ui_get_context.culling.suggestions_total` reports. */
  suggestions_total: number;
  /** Group notes held after the call. */
  notes_total: number;
}

/** What the tab holds at most; a merge beyond it is refused whole. */
export const MAX_STORED_SUGGESTIONS = 300;
export const MAX_STORED_NOTES = 100;

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
  /** The window the plan was computed for: the pin's request, which a date re-plan from the toolbar moves. */
  scope: { album_id: number | null; date_from: string | null; date_to: string | null };
  /** Groups whose confirm has landed. */
  confirmed: number[];
  /** Groups the user flipped away from the plan and has not confirmed or skipped yet. */
  pending: number[];
  /** Every group (confirmed or not) whose keepers differ from the plan's, with the paths to pass as overrides. */
  changed: CullPlanChangedGroup[];
  /** Plan groups neither confirmed, skipped nor flipped. */
  untouched: number;
  /** The plan itself was cut (group or photo cap); distinct from the list trimming `ui_get_context` may add. */
  plan_truncated: boolean;
  /** Stored photo suggestions, whether or not their photo is still in the plan. */
  suggestions_total: number;
  /** Suggestions whose photo the user has put in the suggested state while the plan's own state differs. */
  suggestions_accepted: number;
  /** Suggestions still waiting: an open group, the photo's current state differs from the suggested action. */
  suggestions_open: { path: string; action: CullSuggestionAction }[];
}

/** Why the last plan load failed: `out_of_date` is the 412 (the digest moved), `failed` anything else. */
export type CullPlanLoadFailure = 'out_of_date' | 'failed';

/** A plan response the store keeps so a re-mounted darkroom rebuilds the plan without posting its digest again. */
export interface HeldPlan<T> {
  data: T;
  /** Status and current keepers per group key, as the user left them. */
  state: Map<string, { status: EntryStatus; current: string[] }>;
}

export type EntryStatus = 'open' | 'confirmed' | 'skipped';

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

  /**
   * The assistant's per-photo suggestions and per-group notes. Immutable maps replaced on every change so
   * the template pipes re-evaluate; deliberately untouched by `setPin`, because the store's slider re-plan
   * pins a new digest and they must survive it.
   */
  readonly suggestions = signal<CullSuggestions>({ photos: new Map(), notes: new Map() });

  private entries = new Map<string, Entry>();
  private meta: Meta | null = null;
  private decisionsProbe: (() => boolean) | null = null;
  private closedGroupsProbe: (() => ReadonlySet<string>) | null = null;
  private held: { digest: string; data: unknown } | null = null;
  private failure: { digest: string; reason: CullPlanLoadFailure } | null = null;

  /** Hold a plan. A different digest forgets what was learned about the previous one, so a snapshot never mixes two plans. */
  setPin(pin: CullPlanPin): void {
    if (this.pin()?.digest !== pin.digest) {
      this.entries = new Map();
      this.meta = null;
      this.held = null;
      this.failure = null;
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
    this.clearSuggestions();
    this.entries = new Map();
    this.meta = null;
    this.held = null;
  }

  /** Forget every suggestion and note. */
  clearSuggestions(): void {
    this.suggestions.set({ photos: new Map(), notes: new Map() });
  }

  /**
   * Annotate the held plan. A photo is stored only when it is in the plan, its group is open and the
   * suggestion differs from the plan's own choice; the rest is reported, not stored. Merges by path unless
   * `replace`. Returns `'too_large'`, changing nothing, when the result would exceed the stored caps.
   */
  suggest(
    photos: { path: string; action: CullSuggestionAction; reason: string }[],
    notes: { path: string; note: string }[],
    replace: boolean,
  ): CullSuggestOutcome | 'too_large' {
    const entryOf = new Map<string, Entry>();
    for (const e of this.entries.values()) for (const path of e.paths) entryOf.set(path, e);
    const nextPhotos = new Map(replace ? [] : this.suggestions().photos);
    const nextNotes = new Map(replace ? [] : this.suggestions().notes);
    const closedKeys = this.closedGroupsProbe?.() ?? new Set<string>();
    const out: CullSuggestOutcome = { applied: [], redundant: [], closed: [], missing: [], groups_applied: [], groups_missing: [], groups_closed: [], suggestions_total: 0, notes_total: 0 };
    for (const { path, action, reason } of photos) {
      const e = entryOf.get(path);
      if (!e) out.missing.push(path);
      else if (this.isClosed(e, closedKeys)) out.closed.push(path);
      else if ((action === 'keep') === e.keep_paths.includes(path)) {
        // The later call wins: agreeing with the plan retires an earlier proposal for the same photo.
        nextPhotos.delete(path);
        out.redundant.push(path);
      }
      else {
        nextPhotos.set(path, { action, reason });
        out.applied.push(path);
      }
    }
    for (const { path, note } of notes) {
      const e = entryOf.get(path);
      if (!e) {
        out.groups_missing.push(path);
        continue;
      }
      if (this.isClosed(e, closedKeys)) {
        out.groups_closed.push(path);
        continue;
      }
      nextNotes.set(path, note);
      out.groups_applied.push(path);
    }
    if (nextPhotos.size > MAX_STORED_SUGGESTIONS || nextNotes.size > MAX_STORED_NOTES) return 'too_large';
    this.suggestions.set({ photos: nextPhotos, notes: nextNotes });
    out.suggestions_total = nextPhotos.size;
    out.notes_total = nextNotes.size;
    return out;
  }

  /** Keep the loaded plan response for `digest` so leaving /culling and coming back does not re-post it. */
  hold(digest: string, data: unknown): void {
    this.held = { digest, data };
  }

  /** The held response for `digest` with the user's per-group state, or null when none is held for it. */
  heldPlan<T>(digest: string): HeldPlan<T> | null {
    if (!this.held || this.held.digest !== digest || !this.meta) return null;
    return {
      data: this.held.data as T,
      state: new Map([...this.entries].map(([key, e]) => [key, { status: e.status, current: [...e.current] }])),
    };
  }

  /** Record why the plan for `digest` did not load; the handler of `ui_show_culling_plan` reads it. */
  recordLoadFailure(digest: string, reason: CullPlanLoadFailure): void {
    this.failure = { digest, reason };
  }

  /** The failure recorded for `digest`, if any. */
  loadFailure(digest: string): CullPlanLoadFailure | null {
    return this.failure?.digest === digest ? this.failure.reason : null;
  }

  /** The plan loaded: replace the read model with its groups. `meta.total` counts the whole plan, not only `entries`. */
  register(entries: CullPlanEntryInput[], meta: Meta): void {
    // Compared over the group's own photos only: a keeper the group does not list can never be toggled.
    this.entries = new Map(entries.map(({ current_paths, confirmed, ...e }) => {
      const own = new Set(e.paths);
      const keep = e.keep_paths.filter(path => own.has(path));
      const carried = current_paths ? new Set(current_paths) : null;
      const current = carried ? e.paths.filter(path => carried.has(path)) : [...keep];
      const status: EntryStatus = confirmed ? 'confirmed' : 'open';
      return [e.key, { ...e, keep_paths: keep, status, current }];
    }));
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
   * The mounted darkroom reports the group keys no decision can change any more (confirmed, counting down,
   * hidden), including those whose commit has not landed yet. Returns the function that withdraws the probe.
   */
  registerClosedGroupsProbe(probe: () => ReadonlySet<string>): () => void {
    this.closedGroupsProbe = probe;
    return () => {
      if (this.closedGroupsProbe === probe) this.closedGroupsProbe = null;
    };
  }

  /** True when the group takes no more decisions: settled, or counting down to a confirm or skip. */
  private isClosed(entry: Entry, closedKeys: ReadonlySet<string>): boolean {
    return entry.status !== 'open' || closedKeys.has(entry.key);
  }

  /**
   * True when swapping the plan would discard something the user did on the darkroom now on screen: its
   * own probe says so, or an unconfirmed plan group sits flipped. A flip is held in the plan and restored
   * when the darkroom re-mounts, so it counts even while none is mounted; only the manual probe goes with it.
   */
  hasUnsavedDecisions(): boolean {
    const probe = this.decisionsProbe;
    return (probe !== null && probe()) || this.hasUnconfirmedFlips();
  }

  /** True when an unconfirmed group's keepers differ from the plan: re-seeding would throw that away. */
  hasUnconfirmedFlips(): boolean {
    return [...this.entries.values()].some(e => e.status === 'open' && differs(e));
  }

  /** The unconfirmed, unskipped groups whose keepers differ from the plan: what a re-plan carries over. */
  openFlips(): CullPlanFlip[] {
    return [...this.entries.values()]
      .filter(e => e.status === 'open' && differs(e))
      .map(e => ({ paths: [...e.paths], current: [...e.current] }));
  }

  /** The groups the user confirmed, with the keepers they confirmed: what a re-plan carries over when a group comes back. */
  confirmedEntries(): CullPlanFlip[] {
    return [...this.entries.values()]
      .filter(e => e.status === 'confirmed')
      .map(e => ({ paths: [...e.paths], current: [...e.current] }));
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
    const stored = this.suggestions().photos;
    const closedKeys = this.closedGroupsProbe?.() ?? new Set<string>();
    const open: { path: string; action: CullSuggestionAction }[] = [];
    let accepted = 0;
    for (const e of all) {
      for (const path of e.paths) {
        const suggestion = stored.get(path);
        if (!suggestion) continue;
        const kept = e.current.includes(path);
        if (kept === (suggestion.action === 'keep')) {
          if (e.keep_paths.includes(path) !== kept) accepted++;
        } else if (!this.isClosed(e, closedKeys)) open.push({ path, action: suggestion.action });
      }
    }
    return {
      plan_digest: pin.digest,
      groups_total: this.meta.total,
      scope: {
        album_id: pin.request.album_id ?? null,
        date_from: plainScopeDate(pin.request.date_from, 'from'),
        date_to: plainScopeDate(pin.request.date_to, 'to'),
      },
      confirmed,
      pending,
      changed,
      untouched: Math.max(0, this.meta.total - confirmed.length - skipped - pending.length),
      plan_truncated: this.meta.truncated,
      suggestions_total: stored.size,
      suggestions_accepted: accepted,
      suggestions_open: open,
    };
  }
}

function differs(entry: Entry): boolean {
  return entry.current.length !== entry.keep_paths.length
    || entry.current.some(path => !entry.keep_paths.includes(path));
}
