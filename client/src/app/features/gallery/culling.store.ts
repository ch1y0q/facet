import { SEQUENCE_KINDS_KEPT_WHOLE } from '../../shared/pipes/sequence-kind.pipe';
import { Injectable, inject, signal, computed, WritableSignal } from '@angular/core';
import { Subject, firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import type { ComparisonStats } from '../../core/api/types';
import { Album, AlbumService } from '../../core/services/album.service';
import { I18nService } from '../../core/services/i18n.service';
import { I18N } from '../../core/i18n/keys';
import { CULLING_GROUP_TYPES, type CullingGroup } from './burst-culling.pipes';

export interface CullingGroupsResponse {
  groups: CullingGroup[];
  total_groups: number;
  page: number;
  per_page: number;
  total_pages: number;
}

/** A genre culling preset (GET /api/culling/profiles) bundling the culling knobs. */
export interface CullProfile {
  id: string;
  label_key: string;
  strictness: number | null;
  eyes_closed_max: number | null;
  poor_expression_min: number | null;
  keep_min_per_group: number;
  similarity_threshold: number | null;
}
export interface CullProfilesResponse { profiles: CullProfile[]; default: string; }

// Per-user culling toolbar preferences, persisted so the page reopens the way
// the user left it. The URL query param (deep links / "Cull this scene") still
// overrides the stored granularity.
export const CULL_GROUP_BY_KEY = 'facet_culling_group_by';
export const CULL_SORT_KEY = 'facet_culling_sort';
export const CULL_SORT_DIR_KEY = 'facet_culling_sort_direction';
export const CULL_PROFILE_KEY = 'facet_culling_profile';

export const GROUP_BY_VALUES = ['all', ...CULLING_GROUP_TYPES] as const;
export type GroupBy = typeof GROUP_BY_VALUES[number];
const SORT_VALUES = ['easiest', 'redundant', 'best', 'recent', 'needs_comparisons', 'chronological'];

export function readStoredGroupBy(): GroupBy {
  const v = localStorage.getItem(CULL_GROUP_BY_KEY);
  return (GROUP_BY_VALUES as readonly string[]).includes(v ?? '') ? v as GroupBy : 'all';
}

export function readStoredSort(): string {
  const v = localStorage.getItem(CULL_SORT_KEY);
  return v && SORT_VALUES.includes(v) ? v : 'easiest';
}

/** Stored sort direction. '' means "whatever the active mode naturally does". */
export function readStoredSortDirection(): '' | 'asc' | 'desc' {
  const v = localStorage.getItem(CULL_SORT_DIR_KEY);
  return v === 'asc' || v === 'desc' ? v : '';
}

/** Replace one key of a Map held in a signal (clones, so the signal notifies). */
export function updateMapSignal<K, V>(sig: WritableSignal<Map<K, V>>, key: K, value: V): void {
  sig.update(m => { const next = new Map(m); next.set(key, value); return next; });
}

/** Drop one key of a Map held in a signal (clones, so the signal notifies). */
export function deleteMapKey<K, V>(sig: WritableSignal<Map<K, V>>, key: K): void {
  sig.update(m => { if (!m.has(key)) return m; const next = new Map(m); next.delete(key); return next; });
}

/** Add a value to a Set held in a signal (clones, so the signal notifies). */
export function addToSetSignal<V>(sig: WritableSignal<Set<V>>, value: V): void {
  sig.update(s => { const next = new Set(s); next.add(value); return next; });
}

/** Response of POST /api/culling/auto (dry-run preview and apply share the shape). */
export interface AutoCullResponse {
  groups_processed: number;
  kept: number;
  rejected: number;
  highlights_added: number;
  dry_run: boolean;
  preview: { group_id: number; type: string; keep_paths: string[]; reject_paths: string[]; best_path: string }[];
  preview_truncated: boolean;
}

/** Request body of POST /culling/auto. The dry run's body is kept verbatim so
 *  the apply re-sends the very parameters the displayed counts came from. */
export interface AutoCullRequest {
  group_by: GroupBy;
  strictness: number;
  dry_run: boolean;
  highlights_album: string;
  trim_brackets: boolean;
  profile?: string;
  album_id?: number;
  date_from?: string;
  date_to?: string;
}

/** How an auto-cull dry run ended, for the callers that reconcile their own
 *  state against the snapshot it publishes. `superseded` covers both a newer
 *  run and the destructive apply owning the dialog: in neither case is the
 *  outcome this caller's to act on, and reading it as its own failure reverts
 *  UI state to a snapshot that is no longer the one on screen. */
export type AutoCullRunOutcome = 'landed' | 'superseded' | 'failed';

/** Response of GET /api/culling/suggest_profile: the preset the scope's own
 *  content argues for, and the confidence it named it with (surfaced in the
 *  Suggested badge's tooltip). The endpoint also returns `evidence` -- the
 *  per-genre counts `confidence` was computed from -- which nothing here
 *  reads, so it is left off this type rather than declared and ignored. */
export interface ProfileSuggestion {
  profile: string | null;
  confidence: number;
}

/** Monotonic guard for the two passes here that can be superseded while they
 *  await — darkroom focus peaking and the auto-cull dry run. A pass takes a
 *  ticket with `next()` and drops its result unless `isCurrent(ticket)` still
 *  holds; `cancel()` invalidates whatever is in flight without starting one. */
export class RunGeneration {
  private value = 0;

  next(): number {
    return ++this.value;
  }

  isCurrent(run: number): boolean {
    return run === this.value;
  }

  cancel(): void {
    this.value++;
  }
}

/** A user-facing message the store wants shown. The store never touches the
 *  snackbar: the component renders these, so the store stays free of the DOM. */
export interface CullingNotice {
  key: string;
  params?: Record<string, string | number>;
  duration: number;
}

/**
 * Data state and API calls of the darkroom (`BurstCullingComponent`).
 *
 * Provided by the component (`providers: [CullingStore]`), so its lifetime is
 * one darkroom visit: decisions never persist across visits. The `root`
 * registration exists only so the component can still be instantiated as a
 * plain service by a test bed, which ignores component-level providers.
 * View state (zoom, focus, keyboard, layout, DOM) stays in the component.
 */
@Injectable({ providedIn: 'root' })
export class CullingStore {
  private readonly api = inject(ApiService);
  private readonly i18n = inject(I18nService);

  /** Messages for the component to show (error and success toasts). */
  readonly notice$ = new Subject<CullingNotice>();

  /** Granularity served by the feed: all (merged burst+similar) | burst | similar | scene. */
  readonly groupBy = signal<GroupBy>(readStoredGroupBy());

  // Optional scope from "Cull this scene" / album entry points (query params).
  readonly scopeAlbum = signal<string | null>(null);
  readonly scopeFrom = signal<string | null>(null);
  readonly scopeTo = signal<string | null>(null);
  readonly scopeScene = signal<string | null>(null);
  readonly albums = signal<Album[]>([]);
  readonly scopeAlbumName = computed(() =>
    AlbumService.nameById(this.albums(), this.scopeAlbum()));
  /** Human label for the scope button / banner (null = whole library). */
  readonly scopeLabel = computed(() => {
    const album = this.scopeAlbumName();
    const scene = this.scopeScene();
    if (album && scene) return `${album} · ${scene}`;
    return album ?? scene ?? null;
  });

  // Personal-ranker status, surfaced as the "this cull trains My Taste" chip.
  readonly rankerComparisons = signal<number | null>(null);
  readonly rankerTrained = signal(false);
  /** Per-category comparison counts + threshold, for the weight-tuning chip. */
  readonly comparisonStats = signal<ComparisonStats | null>(null);

  readonly similarityThreshold = signal(85);
  /** Auto-keep strictness (0-100): higher keeps fewer photos below the best. */
  readonly strictness = signal(100);
  readonly excludeRejected = signal(true);
  /** Server-side ordering of culling groups. */
  readonly sortMode = signal(readStoredSort());
  /** Explicit sort direction; '' leaves each mode its natural one. */
  readonly sortDirection = signal<'' | 'asc' | 'desc'>(readStoredSortDirection());

  /** Genre culling presets (GET /api/culling/profiles). */
  readonly cullProfiles = signal<CullProfile[]>([]);

  readonly groups = signal<CullingGroup[]>([]);
  readonly totalGroups = signal(0);
  readonly loading = signal(true);
  readonly loadingMore = signal(false);
  readonly currentPage = signal(1);
  readonly totalPages = signal(1);
  readonly hasMore = computed(() => this.currentPage() < this.totalPages());

  /** group_id -> set of kept paths */
  readonly selectionsMap = signal<Map<number, Set<string>>>(new Map());
  /** Set of confirmed group keys (group_id + '_' + type) */
  readonly confirmedGroups = signal<Set<string>>(new Set());

  /** Seconds a skipped group stays cancellable before it is hidden. */
  readonly passCountdownSeconds = 7;
  /** Map of group key -> remaining countdown seconds for groups being passed */
  readonly passingGroups = signal<Map<string, number>>(new Map());
  /** Set of group keys hidden after pass timeout */
  readonly hiddenGroups = signal<Set<string>>(new Set());
  readonly confirming = signal(false);

  /** Group keys in the feed carrying a correction the detector has not applied yet. */
  readonly pendingCorrectionKeys = computed(
    () => new Set(this.groups()
      .filter(g => g.photos.some(p => p.sequence_override && p.sequence_override_pending))
      .map(g => this.groupKey(g))),
  );

  /**
   * Corrections dropped this session that the detector had already applied.
   *
   * Dropping a still-pending correction needs no re-run: the detector never
   * touched `photos` for it. But dropping an APPLIED one (`sequence_override`
   * set, not pending) leaves the forced set sitting in `photos` until the
   * detector runs again -- and by then `pendingCorrectionKeys` sees nothing, so
   * the re-run banner would never appear without this counter.
   *
   * A key is only ever removed here by a successful re-run (see
   * `pollDetection`): the group may still be pending again in the meantime
   * (re-marked) or no longer pending (undone), but in either case `photos`
   * still holds the stale applied set until the detector runs, so the key
   * must stay recorded regardless of what happens to the pending correction.
   */
  readonly droppedApplied = signal<Set<string>>(new Set());

  /** Groups needing a re-run: the union of still-pending corrections and applied
   *  ones dropped this session. A group that is both pending and dropped counts
   *  once, and keeps counting even after its pending correction is cleared or
   *  re-marked away, because `droppedApplied` is never trimmed by that. */
  readonly rerunNeeded = computed(
    () => new Set([...this.pendingCorrectionKeys(), ...this.droppedApplied()]).size);

  /** Active timers for passing groups (for cleanup) */
  private readonly passTimers = new Map<string, { timeoutId: ReturnType<typeof setTimeout>; intervalId: ReturnType<typeof setInterval>; onElapsed: () => void; commit: boolean }>();

  /** Active preset id ('' = custom / none). Persisted; re-applied on open. */
  readonly selectedProfile = signal<string>(localStorage.getItem(CULL_PROFILE_KEY) ?? '');
  /** The preset the current scope's own content argues for
   *  (GET /culling/suggest_profile), or null while none was inferred. */
  readonly profileSuggestion = signal<ProfileSuggestion | null>(null);
  /** Set the moment the user picks a preset or moves a knob — including a
   *  choice restored from a previous session. A manual choice is never
   *  overwritten by a suggestion for the rest of the session. */
  readonly profileChosen = signal(false);
  /** The scope the cached suggestion answers for; a scope change refetches. */
  private suggestionScopeKey: string | null = null;
  private suggestionApplied = false;

  /** Dry-run result of POST /culling/auto shown in the confirm dialog (null = closed). */
  readonly autoCullPreview = signal<AutoCullResponse | null>(null);
  /** The dry-run body the preview on screen was computed from, set with it and
   *  never re-derived: Apply re-sends this verbatim (dry_run flipped) so the
   *  counts the user agreed to and the knobs that run cannot diverge. A
   *  suggestion applying a preset mid-flight used to move strictness and the
   *  profile between the request and its answer, and the apply then read the
   *  moved signals. */
  readonly autoCullRequest = signal<AutoCullRequest | null>(null);
  /** Bumped per dry run, so a superseded one can never publish over a newer
   *  preview — the pair above must always describe the same run. */
  readonly autoCullRun = new RunGeneration();
  /** True between a dry run's request and its answer. A suggestion landing in
   *  that window has to re-run too: the dialog is not open yet, so waiting on
   *  `autoCullPreview` would have opened it on counts from the knobs the
   *  suggestion just replaced. */
  dryRunInFlight = false;
  /** True while any auto-cull request is in flight (dry run or apply): it drives
   *  the dialog's spinner and disables the knobs that would re-run it. */
  readonly autoCullLoading = signal(false);
  /** True while the *destructive* apply is in flight — the one request that
   *  cannot be abandoned. Every dismissal path (Cancel, backdrop, Escape) is
   *  ignored for its duration and Apply refuses to fire twice, because
   *  dismissing mid-flight re-armed Apply over a snapshot already being applied,
   *  and the apply's own close then bumped the dry-run generation over the run
   *  the reopened dialog was waiting on. */
  readonly autoCullApplying = signal(false);
  /** What the dialog actually renders busy. Not `autoCullLoading` alone: a dry
   *  run that a profile suggestion started behind the apply clears that flag
   *  when it lands, which would drop the spinner and re-arm the knobs while the
   *  destructive request is still open. */
  readonly autoCullBusy = computed(() => this.autoCullLoading() || this.autoCullApplying());
  /** Whether the apply also fills the Highlights album (dialog checkbox, opt-in). */
  readonly autoCullHighlights = signal(false);
  /** Whether auto-cull also proposes trimming redundant, non-clipping bracket
   *  exposures (dialog checkbox); toggling re-runs the dry run since it
   *  changes the preview's group/keep/reject counts. */
  readonly trimBrackets = signal(false);
  /** Translated preset name whose suggestion re-ran an already-open dialog's
   *  preview — the counts changed under the user, so the dialog says why. */
  readonly autoCullSuggestionNotice = signal<string | null>(null);
  /** True when trimming brackets returned the very same counts: without this the
   *  toggle looks broken, since a re-run that changes nothing is silent. */
  readonly trimBracketsUnchanged = signal(false);


  /** Monotonic id bumped on every filter change; loadGroups/loadMore drop late responses whose generation no longer matches. */
  private loadGenerationId = 0;
  private readonly similarSeed = Math.floor(Math.random() * 1_000_000);

  groupKey(group: CullingGroup): string {
    return `${group.group_id}_${group.type}`;
  }

  buildParams(page: number): Record<string, string | number | boolean> {
    const params: Record<string, string | number | boolean> = {
      page,
      per_page: 20,
      similarity_threshold: (this.similarityThreshold() / 100).toString(),
      seed: this.similarSeed,
      exclude_rejected: this.excludeRejected(),
      sort: this.sortMode(),
      direction: this.sortDirection(),
      group_by: this.groupBy(),
    };
    return Object.assign(params, this.scopeParams());
  }

  /** The scope as request params: the one place that decides an empty album or date is left out. */
  private scopeParams(): { album_id?: string; date_from?: string; date_to?: string } {
    const album = this.scopeAlbum();
    const from = this.scopeFrom();
    const to = this.scopeTo();
    return { ...(album ? { album_id: album } : {}), ...(from ? { date_from: from } : {}), ...(to ? { date_to: to } : {}) };
  }

  /** The same scope for the endpoints that take the album as a number. */
  private numericScopeParams(): { album_id?: number; date_from?: string; date_to?: string } {
    const { album_id, ...dates } = this.scopeParams();
    return { ...(album_id ? { album_id: Number(album_id) } : {}), ...dates };
  }

  /** Drop the loaded feed and its per-feed decisions, invalidating any load in flight. */
  resetFeed(): void {
    this.loadGenerationId++;
    // The superseded loadMore's finally no longer matches the generation, so it will not clear this itself.
    this.loadingMore.set(false);
    this.currentPage.set(1);
    this.groups.set([]);
    this.confirmedGroups.set(new Set());
    this.selectionsMap.set(new Map());
  }

  /** Reload the feed from page 1 under the current filters. */
  resetForReload(): void {
    this.resetFeed();
    this.clearAllPassTimers();
    void this.loadGroups();
  }

  async loadGroups(): Promise<void> {
    const gen = this.loadGenerationId;
    this.loading.set(true);
    try {
      const data = await firstValueFrom(
        this.api.get<CullingGroupsResponse>('/culling-groups', this.buildParams(1)),
      );
      if (gen !== this.loadGenerationId) return;
      this.groups.set(data.groups);
      this.totalGroups.set(data.total_groups);
      this.totalPages.set(data.total_pages);
      this.currentPage.set(1);
      this.selectionsMap.set(this.autoSelectBest(data.groups));
    } catch {
      if (gen !== this.loadGenerationId) return;
      this.notice$.next({ key: I18N.culling.error_loading, duration: 2000 });
    } finally {
      if (gen === this.loadGenerationId) this.loading.set(false);
    }
  }

  async loadMore(): Promise<void> {
    if (!this.hasMore() || this.loadingMore()) return;
    const gen = this.loadGenerationId;
    this.loadingMore.set(true);
    try {
      const nextPage = this.currentPage() + 1;
      const data = await firstValueFrom(
        this.api.get<CullingGroupsResponse>('/culling-groups', this.buildParams(nextPage)),
      );
      if (gen !== this.loadGenerationId) return;
      this.groups.update(existing => [...existing, ...data.groups]);
      this.totalPages.set(data.total_pages);
      this.currentPage.set(nextPage);
      this.selectionsMap.set(this.autoSelectBest(data.groups, this.selectionsMap()));
    } catch {
      if (gen !== this.loadGenerationId) return;
      this.notice$.next({ key: I18N.culling.error_loading, duration: 2000 });
    } finally {
      if (gen === this.loadGenerationId) this.loadingMore.set(false);
    }
  }

  /** Fetch the genre presets; null when the list cannot load. */
  async fetchCullProfiles(): Promise<CullProfile[] | null> {
    try {
      const data = await firstValueFrom(this.api.get<CullProfilesResponse>('/culling/profiles'));
      return data.profiles ?? [];
    } catch {
      return null;
    }
  }

  /** Fetch per-category comparison counts + threshold for the weight-tuning chip. */
  async refreshComparisonStats(): Promise<void> {
    try {
      const stats = await firstValueFrom(this.api.get<ComparisonStats>('/comparison/stats'));
      this.comparisonStats.set(stats);
    } catch {
      // Best-effort: the chip simply stays hidden if stats are unavailable.
    }
  }

  /** Fetch personal-ranker status for the "trains My Taste" chip (best-effort). */
  async refreshRankerStatus(): Promise<void> {
    try {
      const s = await firstValueFrom(
        this.api.get<{ trained: boolean; comparison_count: number }>('/ranker/status'),
      );
      this.rankerTrained.set(!!s.trained);
      this.rankerComparisons.set(s.comparison_count ?? null);
    } catch {
      // The chip is a nice-to-have; ignore status failures.
    }
  }

  private autoSelectBest(groups: CullingGroup[], base?: Map<number, Set<string>>): Map<number, Set<string>> {
    const map = base ? new Map(base) : new Map<number, Set<string>>();
    for (const group of groups) {
      if (!map.has(group.group_id)) {
        const kept = this.computeAutoKeep(group);
        if (kept.size > 0) {
          map.set(group.group_id, kept);
        }
      }
    }
    return map;
  }

  /**
   * Derive the auto-keep set for a group from the current strictness (0-100).
   * The best photo is always kept; additional photos whose burst_score falls
   * within a strictness-derived margin of the best are also kept. At strictness
   * 100 only the single best survives; at 0 everything within ~5 points stays.
   *
   * A bracket or a panorama is the exception and starts fully kept whatever the
   * strictness: their frames were shot to be merged, not to compete, so
   * proposing to drop the flanking exposures or half a sweep would be proposing
   * to destroy the set. Trimming a bracket stays available deliberately,
   * through auto-cull's `trim_brackets`, which first checks the base exposure
   * clips nothing.
   */
  private computeAutoKeep(group: CullingGroup): Set<string> {
    if (group.sequence_kind && SEQUENCE_KINDS_KEPT_WHOLE.includes(group.sequence_kind)) {
      return new Set<string>(group.photos.map(p => p.path));
    }
    const best = group.best_path || group.photos[0]?.path;
    if (!best) return new Set<string>();
    const kept = new Set<string>([best]);

    const bestScore = group.photos.find(p => p.path === best)?.burst_score
      ?? Math.max(0, ...group.photos.map(p => p.burst_score));
    // strictness 100 -> margin 0 (only the best); strictness 0 -> margin 5.
    const margin = (100 - this.strictness()) / 100 * 5;
    if (margin > 0) {
      for (const photo of group.photos) {
        if (bestScore - photo.burst_score <= margin) {
          kept.add(photo.path);
        }
      }
    }
    return kept;
  }

  /**
   * Re-derive the auto-keep selection for every loaded group from the current
   * strictness. Purely client-side over the burst_score values already
   * returned — no backend round-trip. Confirmed groups are left untouched.
   */
  reselectFromStrictness(): void {
    const confirmed = this.confirmedGroups();
    const map = new Map<number, Set<string>>();
    for (const group of this.groups()) {
      if (confirmed.has(this.groupKey(group))) {
        const existing = this.selectionsMap().get(group.group_id);
        if (existing) map.set(group.group_id, existing);
        continue;
      }
      const kept = this.computeAutoKeep(group);
      if (kept.size > 0) map.set(group.group_id, kept);
    }
    this.selectionsMap.set(map);
  }

  /** The one write behind every darkroom decision: the ↑ / ↓ keys, a swipe, and
   *  the per-pane buttons a compare grid needs. */
  setPhotoKept(group: CullingGroup, path: string, keep: boolean): void {
    const map = new Map(this.selectionsMap());
    const kept = new Set(map.get(group.group_id) ?? []);
    if (keep) kept.add(path); else kept.delete(path);
    map.set(group.group_id, kept);
    this.selectionsMap.set(map);
  }

  toggleSelection(path: string, group: CullingGroup): void {
    this.setPhotoKept(group, path, !(this.selectionsMap().get(group.group_id)?.has(path) ?? false));
  }

  /**
   * A bracket or a pan is a no-op here: its frames were shot to be merged, not
   * to compete (see SEQUENCE_KINDS_KEPT_WHOLE), and every other surface -- computeAutoKeep,
   * the hidden auto-cull button -- already protects that.
   */
  selectExclusive(path: string, group: CullingGroup): void {
    if (group.sequence_kind && SEQUENCE_KINDS_KEPT_WHOLE.includes(group.sequence_kind)) return;
    updateMapSignal(this.selectionsMap, group.group_id, new Set([path]));
  }

  /** The body of POST /culling-groups/confirm for one group. */
  private confirmBody(group: CullingGroup, keepPaths: string[]) {
    return {
      group_id: group.group_id,
      type: group.type,
      paths: group.photos.map(p => p.path),
      keep_paths: keepPaths,
    };
  }

  /**
   * Grey the group and start the cancellable cooldown; the commit only happens
   * when it elapses, so cancelling within the window fully reverts it. Returns
   * false when the group has nothing kept (nothing to confirm).
   */
  confirmGroup(group: CullingGroup): boolean {
    const kept = this.selectionsMap().get(group.group_id);
    if (!kept || kept.size === 0) return false;
    const key = this.groupKey(group);
    const keepPaths = [...kept];
    addToSetSignal(this.confirmedGroups, key);
    this.startCountdown(key, () => {
      void firstValueFrom(this.api.post('/culling-groups/confirm', this.confirmBody(group, keepPaths)))
        .then(() => {
          addToSetSignal(this.hiddenGroups, key);
          void this.refreshComparisonStats();
          void this.refreshRankerStatus();
        })
        .catch(() => {
          this.unconfirmGroup(key);
          this.notice$.next({ key: I18N.culling.error_confirming, duration: 2000 });
        });
    }, true);
    return true;
  }

  unconfirmGroup(key: string): void {
    this.confirmedGroups.update(s => {
      const next = new Set(s);
      next.delete(key);
      return next;
    });
  }

  /** Confirm every not-yet-confirmed group of `visible` that has a kept photo, five at a time. */
  async confirmAllRemaining(visible: CullingGroup[]): Promise<void> {
    this.confirming.set(true);
    try {
      const confirmed = this.confirmedGroups();
      const remaining = visible.filter(g => !confirmed.has(this.groupKey(g)));
      const toConfirm = remaining.filter(g => {
        const kept = this.selectionsMap().get(g.group_id);
        return kept && kept.size > 0;
      });
      // Process in batches of 5 to avoid overwhelming the server
      const batchSize = 5;
      for (let i = 0; i < toConfirm.length; i += batchSize) {
        const batch = toConfirm.slice(i, i + batchSize);
        await Promise.all(batch.map(g => {
          const kept = this.selectionsMap().get(g.group_id)!;
          return firstValueFrom(this.api.post('/culling-groups/confirm', this.confirmBody(g, [...kept])));
        }));
        this.confirmedGroups.update(s => {
          const next = new Set(s);
          for (const g of batch) next.add(this.groupKey(g));
          return next;
        });
      }
      const skipped = remaining.filter(g => !toConfirm.includes(g));
      this.confirmedGroups.update(s => {
        const next = new Set(s);
        for (const g of skipped) next.add(this.groupKey(g));
        return next;
      });
      this.notice$.next({ key: I18N.culling.confirmed, duration: 2000 });
    } catch {
      this.notice$.next({ key: I18N.culling.error_auto_select, duration: 2000 });
    } finally {
      this.confirming.set(false);
    }
  }

  skipGroup(group: CullingGroup): void {
    const key = this.groupKey(group);
    this.startCountdown(key, () => addToSetSignal(this.hiddenGroups, key));
  }

  cancelPass(group: CullingGroup): void {
    const key = this.groupKey(group);
    this.clearPassTimer(key);
    this.unconfirmGroup(key);
  }

  /**
   * Shared 7s cooldown: a per-second countdown in passingGroups plus a one-shot
   * timer that runs onElapsed (hide for skip; commit + hide for confirm). Cancel
   * via cancelPass before it fires fully reverts the action.
   */
  private startCountdown(key: string, onElapsed: () => void, commit = false): void {
    this.clearPassTimer(key);
    updateMapSignal(this.passingGroups, key, this.passCountdownSeconds);
    const intervalId = setInterval(() => {
      this.passingGroups.update(m => {
        const current = m.get(key);
        if (current === undefined) return m;
        const next = new Map(m);
        next.set(key, current - 1);
        return next;
      });
    }, 1000);
    const timeoutId = setTimeout(() => {
      this.clearPassTimer(key);
      onElapsed();
    }, this.passCountdownSeconds * 1000);
    this.passTimers.set(key, { timeoutId, intervalId, onElapsed, commit });
  }

  private clearPassTimer(key: string): void {
    const timers = this.passTimers.get(key);
    if (timers) {
      clearTimeout(timers.timeoutId);
      clearInterval(timers.intervalId);
      this.passTimers.delete(key);
    }
    deleteMapKey(this.passingGroups, key);
  }

  clearAllPassTimers(): void {
    // A confirm defers its server commit into the cooldown timer; cancelling
    // that timer on teardown/reload without running it would silently drop the
    // user's keep/reject decision. So flush pending confirm commits here (skip
    // timers only hide a group, nothing to persist). Explicit cancelPass goes
    // through clearPassTimer and is unaffected — an abort still aborts.
    const pendingCommits: (() => void)[] = [];
    for (const { timeoutId, intervalId, onElapsed, commit } of this.passTimers.values()) {
      clearTimeout(timeoutId);
      clearInterval(intervalId);
      if (commit) pendingCommits.push(onElapsed);
    }
    this.passTimers.clear();
    this.passingGroups.set(new Map());
    this.hiddenGroups.set(new Set());
    for (const commit of pendingCommits) commit();
  }

  /** Set one override value on the named frames, wherever they sit in the feed. */
  patchOverrides(paths: string[], value: string | null): void {
    this.restoreOverrides(new Map(paths.map(path => [path, value])));
  }

  /** Write back per-path override values (the undo path restores the old ones). */
  restoreOverrides(values: Map<string, string | null>): void {
    // `droppedApplied` is deliberately left untouched here: `rerunNeeded` unions it
    // with the pending-correction keys, so re-marking (or undoing the re-mark) a
    // group whose applied override was already dropped this session must not stop
    // it counting -- `photos` still holds the stale applied set either way.
    this.groups.update(groups => groups.map(group => (
      group.photos.some(p => values.has(p.path))
        ? {
            ...group,
            photos: group.photos.map(p => (
              values.has(p.path)
                ? {
                    ...p,
                    sequence_override: values.get(p.path) ?? null,
                    // Anything just written here is by definition unapplied: the
                    // detector is a batch pass, not a live query.
                    sequence_override_pending: values.get(p.path) ? 1 : null,
                  }
                : p
            )),
          }
        : group
    )));
  }

  /** Moving a knob by hand drops the preset label — the mix is now custom. */
  clearProfileSelection(): void {
    if (this.selectedProfile()) {
      this.selectedProfile.set('');
      localStorage.removeItem(CULL_PROFILE_KEY);
    }
  }

  // --- Genre culling profiles (preset selector + moment auto-suggest) ---

  /** Load the genre culling presets; re-apply the persisted one on open. */
  async loadCullProfiles(): Promise<void> {
    try {
      const profiles = await this.fetchCullProfiles();
      if (!profiles) return;
      this.cullProfiles.set(profiles);
      const stored = this.cullProfiles().find(p => p.id === this.selectedProfile());
      if (stored) {
        // A restored preset is a choice the user made, just in an earlier
        // session; a suggestion must not silently replace it.
        this.profileChosen.set(true);
        this.applyProfile(stored, false);
      } else {
        this.clearProfileSelection();
      }
    } catch {
      // Preset selector stays hidden when the list can't load.
    }
  }

  /**
   * Apply a preset: set strictness first (so a reload auto-selects with it) and
   * the similarity threshold, remember the choice, then re-derive the auto-keep
   * selection in place — or reload only when the threshold changed the grouping.
   */
  applyProfile(p: CullProfile, persist = true): void {
    this.selectedProfile.set(p.id);
    if (persist) {
      localStorage.setItem(CULL_PROFILE_KEY, p.id);
      this.profileChosen.set(true);
    }
    if (p.strictness != null) this.strictness.set(p.strictness);
    if (p.similarity_threshold != null && p.similarity_threshold !== this.similarityThreshold()) {
      this.similarityThreshold.set(p.similarity_threshold);
      this.resetForReload();
    } else if (p.strictness != null) {
      this.reselectFromStrictness();
    }
  }

  /** Identity of the current scope, so a scope change refetches its suggestion. */
  scopeKey(): string {
    const scope = this.scopeParams();
    return [scope.album_id ?? '', scope.date_from ?? '', scope.date_to ?? ''].join('|');
  }

  /** Drop a suggestion that answered for another scope. */
  resetProfileSuggestion(): void {
    this.suggestionScopeKey = null;
    this.suggestionApplied = false;
    this.profileSuggestion.set(null);
  }

  /**
   * Preselect the preset the scope's content argues for, at most once per scope.
   *
   * Fetched alongside the dry run rather than before it, so the dialog opens at
   * the same speed whether or not a suggestion arrives; one that lands while the
   * dialog is open — or while its dry run is still in flight — re-runs the
   * preview under the suggested knobs rather than leaving stale counts on
   * screen. An explicit choice — a preset click, a knob move, or one restored
   * from a previous session — is never overwritten.
   *
   * Refused outright once the destructive apply is in flight, and refused again
   * after the fetch, since that is the whole window this can resolve in. The
   * apply owns the knobs the same way it owns the snapshot: refusing only at the
   * dry run's door came after applyProfile() had already moved strictness and lit
   * the preset chip, so the user watched them jump under a request neither the
   * counts on screen nor the apply itself were computed from. Nothing is queued
   * for afterwards — the dialog a late suggestion would repaint is gone by then.
   */
  async applySuggestedProfile(): Promise<void> {
    if (this.profileChosen() || this.suggestionApplied || this.autoCullApplying()) return;
    const key = this.scopeKey();
    const suggestion = this.suggestionScopeKey === key
      ? this.profileSuggestion()
      : await this.fetchProfileSuggestion(key);
    const suggested = suggestion?.profile;
    if (!suggested || this.profileChosen() || this.autoCullApplying()) return;
    const profile = this.cullProfiles().find(p => p.id === suggested);
    if (!profile || profile.id === this.selectedProfile()) return;
    this.suggestionApplied = true;
    this.applyProfile(profile, false);
    if (this.autoCullPreview() || this.dryRunInFlight) {
      // Named only once the re-run published: a refused one (the apply owns the
      // dialog) leaves the counts exactly as they were, and the notice claims
      // they were recomputed under the preset it names.
      if (await this.openAutoCull() === 'landed') {
        this.autoCullSuggestionNotice.set(this.i18n.t(profile.label_key));
      }
    }
  }

  /** Ask the backend which preset this scope's stored content looks like. */
  async fetchProfileSuggestion(key: string): Promise<ProfileSuggestion | null> {
    const params: Record<string, string | number> = this.numericScopeParams();
    try {
      const data = await firstValueFrom(
        this.api.get<ProfileSuggestion>('/culling/suggest_profile', params),
      );
      this.suggestionScopeKey = key;
      this.profileSuggestion.set(data);
      return data;
    } catch {
      // No suggestion: the dialog keeps whatever preset is already active.
      return null;
    }
  }

  // --- Auto-cull (one-button cull under a keeper budget) ---

  /** Request body for POST /culling/auto, reusing the page's scope + strictness. */
  autoCullBody(dryRun: boolean, highlightsAlbum: string): AutoCullRequest {
    const body: AutoCullRequest = {
      group_by: this.groupBy(),
      strictness: this.strictness(),
      dry_run: dryRun,
      highlights_album: highlightsAlbum,
      trim_brackets: this.trimBrackets(),
    };
    const profile = this.selectedProfile();
    if (profile) body.profile = profile;
    return Object.assign(body, this.numericScopeParams());
  }

  /** Deterministic Highlights album name for the current scope and day. */
  highlightsAlbumName(): string {
    const scope = this.scopeLabel() ?? this.i18n.t(I18N.culling.scope_whole_library);
    const day = new Date().toISOString().slice(0, 10);
    return `${this.i18n.t(I18N.culling.auto_cull.highlights_name)} — ${scope} ${day}`;
  }

  /** True while this dry run is still the one the dialog answers to: no newer
   *  run took over, and the destructive apply does not own the snapshot. */
  ownsAutoCullDialog(run: number): boolean {
    return this.autoCullRun.isCurrent(run) && !this.autoCullApplying();
  }

  /**
   * Put the trim-brackets checkbox back to what the snapshot Apply sends carries.
   *
   * Called from the failure of whichever run owns the dialog, because that run is
   * the one the box has to agree with — not necessarily the one the user clicked.
   * A failed run never moved the snapshot, so a box left on the value that run
   * asked for promises a trim the apply would not perform.
   */
  reconcileTrimBrackets(): void {
    const applied = this.autoCullRequest();
    if (applied) this.trimBrackets.set(applied.trim_brackets);
  }

  /**
   * Dry-run the auto-cull for the current scope and open the confirm dialog.
   *
   * Refused outright while the apply is in flight, and its answer dropped if an
   * apply started under it: the apply sends the snapshot below verbatim, so a dry
   * run repainting it mid-flight would leave the dialog describing a request the
   * user never agreed to. The suggestion's re-run is fire-and-forget, so it can
   * arrive at any point — including over the destructive request.
   *
   * The outcome is for the callers that mirror the snapshot in their own state:
   * a bail-out is not this caller's run failing, and reconciling on it reverts to
   * a snapshot the newer run is about to replace.
   */
  async openAutoCull(): Promise<AutoCullRunOutcome> {
    if (this.autoCullApplying()) return 'superseded';
    // Only a fresh open clears the notices: the re-runs that raise them come back
    // through here, and clearing unconditionally would erase them on the way in —
    // including the re-run of a dry run whose preview has not landed yet.
    if (!this.autoCullPreview() && !this.dryRunInFlight) this.clearAutoCullNotices();
    const run = this.autoCullRun.next();
    this.dryRunInFlight = true;
    void this.applySuggestedProfile();
    const body = this.autoCullBody(true, this.highlightsAlbumName());
    this.autoCullLoading.set(true);
    try {
      const preview = await firstValueFrom(this.api.post<AutoCullResponse>('/culling/auto', body));
      if (!this.ownsAutoCullDialog(run)) return 'superseded';
      this.autoCullPreview.set(preview);
      this.autoCullRequest.set(body);
      return 'landed';
    } catch {
      if (!this.ownsAutoCullDialog(run)) return 'superseded';
      this.reconcileTrimBrackets();
      this.notice$.next({ key: I18N.culling.auto_cull.error, duration: 2000 });
      return 'failed';
    } finally {
      if (this.autoCullRun.isCurrent(run)) {
        this.dryRunInFlight = false;
        this.autoCullLoading.set(false);
      }
    }
  }

  /** Every dismissal lands here — the Cancel button, the backdrop and Escape.
   *  It is a no-op while the apply is in flight: the destructive request cannot
   *  be called off, so the dialog stays up with its spinner rather than pretend
   *  it was. */
  cancelAutoCull(): void {
    if (this.autoCullApplying()) return;
    this.closeAutoCull();
    this.clearAutoCullNotices();
  }

  /** Drop the dialog and the run behind it, so a dry run still in flight cannot
   *  reopen it with counts nobody asked for. Safe from the apply's own success
   *  path for the same reason the guard above exists: no dismissal can have
   *  reopened the dialog mid-apply, so the bump can only cancel a dry run whose
   *  preview this apply just made obsolete. */
  closeAutoCull(): void {
    this.autoCullRun.cancel();
    this.dryRunInFlight = false;
    this.autoCullPreview.set(null);
    this.autoCullRequest.set(null);
    this.autoCullLoading.set(false);
  }

  clearAutoCullNotices(): void {
    this.autoCullSuggestionNotice.set(null);
    this.trimBracketsUnchanged.set(false);
  }

  /** Trim-brackets changes the group set the dry run splits, so the preview
   *  counts must be re-fetched through the same path openAutoCull() uses.
   *
   *  A scope with no redundant exposures answers with the very same counts, which
   *  is indistinguishable from a dead toggle — so that case is stated. The
   *  identity check on the preview object keeps a failed re-run (which leaves the
   *  old preview in place) from being read as "nothing to trim".
   *
   *  Reverting the checkbox over a failed re-run is not this handler's to do: the
   *  run that fails is not always the one this call started. A superseded re-run
   *  reads from here exactly like its own failure, and the snapshot it would be
   *  reconciled against is the stale one the newer run has not replaced yet — so
   *  the box would be reverted to a value that run is about to contradict, and
   *  the newer run failing in turn would leave nobody to put it back. The run
   *  that owns the dialog reconciles the box, in openAutoCull(); this handler
   *  only reads the outcome. */
  async onTrimBracketsChange(value: boolean): Promise<void> {
    if (this.autoCullApplying()) return;
    const before = this.autoCullPreview();
    this.trimBrackets.set(value);
    this.trimBracketsUnchanged.set(false);
    if (await this.openAutoCull() !== 'landed') return;
    const after = this.autoCullPreview();
    this.trimBracketsUnchanged.set(
      value && !!before && !!after && after !== before
      && after.groups_processed === before.groups_processed
      && after.kept === before.kept
      && after.rejected === before.rejected,
    );
  }

  /**
   * Apply the previewed auto-cull (dry_run=false), then refresh the feed.
   *
   * The body is the dry run's own, not one rebuilt from the live signals: a
   * profile suggestion can land between the preview request and its answer, and
   * rebuilding here would then apply knobs the counts on screen never described.
   * Only the Highlights album is the dialog's to decide, being a checkbox the
   * user ticks after the preview.
   *
   * The `autoCullApplying` gate makes the click idempotent: a second one over
   * the same snapshot is refused rather than sent, since the two applies would
   * reject different sets — the first has already moved the state the second
   * would be computed from.
   *
   * `onApplied` runs once the apply landed, before the stats refresh: the caller
   * resets its own view state and reloads the feed there.
   */
  async confirmAutoCull(onApplied: () => void): Promise<void> {
    const previewed = this.autoCullRequest();
    if (!previewed || this.autoCullApplying()) return;
    this.autoCullApplying.set(true);
    this.autoCullLoading.set(true);
    try {
      const body: AutoCullRequest = {
        ...previewed,
        dry_run: false,
        highlights_album: this.autoCullHighlights() ? previewed.highlights_album : '',
      };
      const result = await firstValueFrom(this.api.post<AutoCullResponse>('/culling/auto', body));
      this.closeAutoCull();
      this.clearAutoCullNotices();
      this.notice$.next({
        key: I18N.culling.auto_cull.applied,
        params: { kept: result.kept, rejected: result.rejected },
        duration: 3000,
      });
      onApplied();
      void this.refreshComparisonStats();
      void this.refreshRankerStatus();
    } catch {
      this.notice$.next({ key: I18N.culling.auto_cull.error, duration: 2000 });
    } finally {
      this.autoCullApplying.set(false);
      this.autoCullLoading.set(false);
    }
  }
}
