import { LEVEL_RANK, agentLevel } from './agent-level';
import { Router } from '@angular/router';
import { AuthService } from '../services/auth.service';
import { GalleryStore } from '../../features/gallery/gallery.store';
import {
  DEFAULT_FILTERS,
  GalleryFilters,
  RANGE_AND_SELECT_KEYS,
  SEARCH_THRESHOLD_MAX,
  buildApiParams,
  seededSearchThreshold,
} from '../../features/gallery/gallery-filters.util';
import { CULL_DEFAULT_STRICTNESS, CULL_PROFILE_KEY } from '../../features/gallery/culling.store';
import { COMPARE_AB_TAB_INDEX, CompareFiltersService } from '../../features/comparison/compare-filters.service';
import { ViewActionRegistry } from './view-action-registry.service';
import { UserActivityJournal } from './user-activity-journal.service';
import { AssistantCullPlanService, type CullPlanRequest } from './assistant-cull-plan.service';
import type { CullPlanSnapshot } from './assistant-cull-plan.service';
import { UiActionRow, UiToolError, UiToolHandler } from './ui-tool.types';

export interface UiToolDeps {
  gallery: GalleryStore;
  router: Router;
  auth: AuthService;
  viewActions: ViewActionRegistry;
  /** The generated `actions` table (empty until the contract has loaded). */
  actions: () => readonly UiActionRow[];
  /** Category / strategy / tab state of the comparison page. */
  compareFilters: CompareFiltersService;
  /** What the user did in this tab; read by `ui_get_context`. */
  journal: UserActivityJournal;
  /** The assistant's culling plan: the pin `ui_show_culling_plan` sets and the read model `ui_get_context` reports. */
  plan: AssistantCullPlanService;
}

/** The contract's cap on `ui_show_photos` paths (api/agent/ui_tools.py MAX_SHOW_PATHS). */
const MAX_SHOW_PATHS = 200;

/**
 * The pages `ui_navigate` may open, read from the live router config so a new page
 * or a new edition-only flag cannot drift from a hand list: static top-level paths
 * only (no parameters, redirects, the login page or the public `shared/**` pages).
 */
function appRoutes(router: Router): { allowed: Set<string>; editionOnly: Set<string> } {
  const allowed = new Set<string>();
  const editionOnly = new Set<string>();
  for (const route of router.config) {
    const path = route.path;
    if (path === undefined || route.redirectTo !== undefined || /[:*]/.test(path)) continue;
    if (path === 'login' || path.startsWith('shared/')) continue;
    allowed.add(`/${path}`);
    if ((route.data as { edition?: boolean } | undefined)?.edition === true) editionOnly.add(`/${path}`);
  }
  return { allowed, editionOnly };
}

/** The contract names a filter the way the server's `GalleryParams` does; the tab stores a few under another name. */
const CONTRACT_TO_CLIENT_KEY: Record<string, keyof GalleryFilters> = {
  person: 'person_id',
  category: 'type',
  semantic_query: 'semanticQuery',
  semantic_threshold: 'search_threshold',
};

const CLIENT_TO_CONTRACT_KEY: Record<string, string> = {
  person_id: 'person',
  type: 'category',
  semanticQuery: 'semantic_query',
  search_threshold: 'semantic_threshold',
};

/** The contract speaks 0-1 fractions (like the MCP tools and the REST routes); the store keeps percent strings. */
const FRACTION_KEYS = new Set(['semantic_threshold', 'min_similarity']);
const SIMILARITY_MODES = ['visual', 'color', 'person'];

function fractionToPercent(key: string, value: unknown): string {
  const fraction = typeof value === 'number' ? value : Number(value);
  const max = key === 'semantic_threshold' ? SEARCH_THRESHOLD_MAX / 100 : 1;
  if (!Number.isFinite(fraction) || fraction < 0 || fraction > max) {
    throw new UiToolError('invalid_input', `${key} must be a number between 0 and ${max}.`);
  }
  return String(Number((fraction * 100).toFixed(4)));
}

function percentToFraction(percent: string): number {
  return Number((Number(percent) / 100).toFixed(6));
}

const SELECTION_PATH_LIMIT = 1000;
/** A selection frame must stay under the bridge's 256 KB limit, so its path lists share this budget. */
const SELECTION_BYTE_BUDGET = 200 * 1024;
const TEXT_ENCODER = new TextEncoder();
const WAIT_STEP_MS = 25;
const WAIT_TIMEOUT_MS = 10_000;

const COMPACT_KEYS = [
  'path', 'filename', 'date_taken', 'aggregate', 'aesthetic', 'comp_score', 'face_quality',
  'category', 'face_count', 'is_favorite', 'star_rating', 'is_rejected', 'sequence_kind',
] as const;

function delay(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitFor(condition: () => boolean, timeoutMs = WAIT_TIMEOUT_MS): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (!condition()) {
    if (Date.now() >= deadline) return false;
    await delay(WAIT_STEP_MS);
  }
  return true;
}

function pathOf(url: string): string {
  return url.split('?')[0].split('#')[0];
}

function isGalleryUrl(url: string): boolean {
  const path = pathOf(url);
  return path === '/' || path === '' || path.startsWith('/album/');
}

function toBoolean(key: string, value: unknown): boolean {
  if (typeof value === 'boolean') return value;
  if (value === 1 || value === '1' || value === 'true') return true;
  if (value === 0 || value === '0' || value === 'false') return false;
  throw new UiToolError('invalid_input', `${key} must be a boolean`);
}

/** The longest prefix of `paths` (at most `limit`) that fits `budget` bytes once JSON-encoded. */
function fitPaths(paths: readonly string[], budget: number, limit = SELECTION_PATH_LIMIT): string[] {
  const kept: string[] = [];
  let used = 0;
  for (const path of paths) {
    used += TEXT_ENCODER.encode(JSON.stringify(path)).length + 1;
    if (kept.length >= limit || used > budget) break;
    kept.push(path);
  }
  return kept;
}

/**
 * The facts of a tab's state; the same rules as the server's `actions.facts_for`, so the
 * generated `actions` table means the same thing on both sides.
 */
export function actionFacts(route: string, selectionCount: number, pinned: boolean): Set<string> {
  const path = pathOf(route) || '/';
  const facts = new Set(['any']);
  if (path === '/' || path.startsWith('/album/')) facts.add('gallery');
  if (path === '/photo') facts.add('detail');
  if (path === '/culling') facts.add('culling');
  if (path === '/persons' || path === '/merge-suggestions') facts.add('persons');
  if (path === '/albums' || path.startsWith('/album/')) facts.add('albums');
  if (selectionCount > 0) facts.add('selection');
  if (pinned) facts.add('pinned');
  return facts;
}

/** The jobs that apply to `facts` for a session at `level`; tools above the level are left out. */
export function applicableActions(
  rows: readonly UiActionRow[], facts: ReadonlySet<string>, level: string,
): { id: string; summary: string; tools: string[] }[] {
  const rank = LEVEL_RANK[level] ?? -1;
  const out: { id: string; summary: string; tools: string[] }[] = [];
  for (const row of rows) {
    if (!row.when.includes('any') && !row.when.some(fact => facts.has(fact))) continue;
    const tools = row.tools.filter(tool => (LEVEL_RANK[tool.required_level] ?? Infinity) <= rank).map(tool => tool.name);
    if (tools.length) out.push({ id: row.id, summary: row.summary, tools });
  }
  return out;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

export function createUiToolHandlers(deps: UiToolDeps): Record<string, UiToolHandler> {
  const { gallery, router, auth, viewActions, actions, compareFilters, journal, plan } = deps;

  const requireGalleryView = (): void => {
    if (!isGalleryUrl(router.url)) {
      throw new UiToolError('no_active_view', `The gallery is not open (the tab shows ${pathOf(router.url) || '/'}). Use ui_navigate to "/" first.`);
    }
  };

  /**
   * Bring the tab to the gallery and wait until its first load has settled, so a
   * filter patch is not overwritten by the page's own init. The signal is the
   * store's mount counter (bumped when the gallery page initialises), never a delay.
   */
  const ensureGalleryView = async (): Promise<void> => {
    if (!isGalleryUrl(router.url)) {
      const mounts = gallery.galleryMounts();
      const ok = await router.navigate(['/']);
      if (!ok) throw new UiToolError('forbidden_level', 'The tab could not open the gallery.');
      if (!await waitFor(() => gallery.galleryMounts() > mounts)) {
        throw new UiToolError('upstream_error', 'The gallery did not open.');
      }
    }
    const settled = await waitFor(() => !gallery.initializing() && gallery.config() !== null);
    if (!settled) throw new UiToolError('upstream_error', 'The gallery did not finish loading.');
  };

  /** Leave an album page for the plain gallery, so a view change is never saved as that album's smart filter. */
  const leaveAlbum = async (): Promise<void> => {
    if (!pathOf(router.url).startsWith('/album/')) return;
    const mounts = gallery.galleryMounts();
    if (!await router.navigate(['/'])) throw new UiToolError('forbidden_level', 'The tab could not leave the album.');
    if (!await waitFor(() => gallery.galleryMounts() > mounts)) throw new UiToolError('upstream_error', 'The gallery did not open.');
  };

  const filterDefault = (key: keyof GalleryFilters): GalleryFilters[keyof GalleryFilters] => {
    const configured = gallery.config()?.defaults as Record<string, unknown> | undefined;
    const fromConfig = configured?.[key];
    return fromConfig !== undefined && typeof fromConfig === typeof DEFAULT_FILTERS[key]
      ? fromConfig as GalleryFilters[keyof GalleryFilters]
      : DEFAULT_FILTERS[key];
  };

  const clearedFilters = (): Partial<GalleryFilters> => {
    const keys: (keyof GalleryFilters)[] = [
      ...RANGE_AND_SELECT_KEYS, 'album_id', 'favorites_only', 'is_monochrome', 'similar_to', 'semanticQuery',
      'hide_blinks', 'hide_bursts', 'hide_duplicates', 'hide_brackets', 'hide_panoramas', 'hide_rejected',
      'sequence_group_id', 'sequence_kind', 'burst_group_id', 'duplicate_group_id',
    ];
    const cleared: Record<string, unknown> = {};
    for (const key of keys) cleared[key] = filterDefault(key);
    return cleared as Partial<GalleryFilters>;
  };

  /** Contract patch -> the tab's filter shape. An unknown or doubled key refuses the whole patch, never half applies it. */
  const patchToUpdates = (patch: Record<string, unknown>): Partial<GalleryFilters> => {
    const updates: Record<string, unknown> = {};
    for (const [contractKey, value] of Object.entries(patch)) {
      const key = Object.hasOwn(CONTRACT_TO_CLIENT_KEY, contractKey) ? CONTRACT_TO_CLIENT_KEY[contractKey] : contractKey;
      if (!Object.hasOwn(DEFAULT_FILTERS, key)) {
        throw new UiToolError('invalid_input', `This tab has no filter named ${contractKey}.`);
      }
      if (Object.hasOwn(updates, key)) {
        throw new UiToolError('invalid_input', `${CLIENT_TO_CONTRACT_KEY[key] ?? key} was given twice (as category and type, or person and person_id).`);
      }
      const clientKey = key as keyof GalleryFilters;
      if (value === null) {
        updates[clientKey] = clientKey === 'search_threshold'
          ? seededSearchThreshold(gallery.config()?.search_threshold_default)
          : filterDefault(clientKey);
      } else if (FRACTION_KEYS.has(contractKey)) {
        updates[clientKey] = fractionToPercent(contractKey, value);
      } else if (clientKey === 'similarity_mode') {
        if (!SIMILARITY_MODES.includes(String(value))) {
          throw new UiToolError('invalid_input', `similarity_mode must be one of ${SIMILARITY_MODES.join(', ')}.`);
        }
        updates[clientKey] = String(value);
      } else if (typeof DEFAULT_FILTERS[clientKey] === 'boolean') {
        updates[clientKey] = toBoolean(contractKey, value);
      } else if (clientKey === 'sort_direction') {
        updates[clientKey] = String(value).toUpperCase();
      } else {
        updates[clientKey] = String(value);
      }
    }
    if (updates['similar_to'] && updates['semanticQuery']) {
      throw new UiToolError('invalid_input', 'similar_to and semantic_query cannot be combined (the tab ranks by one of them).');
    }
    return updates as Partial<GalleryFilters>;
  };

  const viewFilters = (): Record<string, string | number | boolean> => {
    const f = gallery.filters();
    const params = buildApiParams(f, gallery.currentAlbum()?.is_smart ?? false);
    delete params['page'];
    delete params['per_page'];
    const out: Record<string, string | number | boolean> = {};
    for (const [key, value] of Object.entries(params)) out[Object.hasOwn(CLIENT_TO_CONTRACT_KEY, key) ? CLIENT_TO_CONTRACT_KEY[key] : key] = value;
    if (f.semanticQuery) {
      out['semantic_query'] = f.semanticQuery;
      if (f.search_threshold) out['semantic_threshold'] = percentToFraction(f.search_threshold);
    }
    if (f.similar_to) {
      out['similar_to'] = f.similar_to;
      out['similarity_mode'] = f.similarity_mode;
      out['min_similarity'] = percentToFraction(f.min_similarity);
    }
    return out;
  };

  const selectionSnapshot = (): Record<string, unknown> => {
    if (gallery.viewScopeSelected()) {
      const filters = gallery.filterPayload();
      const excluded = [...gallery.excludedPaths()];
      const kept = fitPaths(excluded, SELECTION_BYTE_BUDGET - TEXT_ENCODER.encode(JSON.stringify(filters)).length);
      return {
        scope: 'view',
        count: gallery.selectionCount(),
        filters,
        excluded_paths: kept,
        excluded_count: excluded.length,
        excluded_truncated: kept.length < excluded.length,
      };
    }
    const paths = [...gallery.selectedPaths()];
    const kept = fitPaths(paths, SELECTION_BYTE_BUDGET);
    return {
      scope: 'paths',
      count: paths.length,
      paths: kept,
      ...(kept.length < paths.length ? { truncated: true } : {}),
    };
  };

  /** The session level this tab carries, as the server's bridge records it. */
  const sessionLevel = (): string => agentLevel({ authenticated: auth.isAuthenticated(), multi_user: auth.isMultiUser(), edition_authenticated: auth.isEdition() });

  return {
    ui_navigate: async args => {
      const route = args['route'] as string;
      const { allowed, editionOnly } = appRoutes(router);
      if (!allowed.has(route)) throw new UiToolError('invalid_input', `${String(route).slice(0, 80)} is not a page of this app.`);
      if (editionOnly.has(route) && !auth.isEdition()) {
        throw new UiToolError('forbidden_level', `${route} needs an edition session.`);
      }
      const query = (args['query'] ?? {}) as Record<string, string | number | boolean>;
      const queryParams = Object.fromEntries(Object.entries(query).map(([k, v]) => [k, String(v)]));
      const ok = await router.navigate([route], { queryParams, onSameUrlNavigation: 'reload' });
      if (!ok) throw new UiToolError('forbidden_level', `The tab refused to open ${route}.`);
      return { route: pathOf(router.url) || '/' };
    },

    ui_set_gallery_filters: async args => {
      const patch = (args['patch'] ?? {}) as Record<string, unknown>;
      patchToUpdates(patch);
      // On an album page the store saves every filter change as that album's smart filter (edition sessions),
      // which a readonly-granted agent must never cause: leave the album for any change, not only a replace.
      await leaveAlbum();
      await ensureGalleryView();
      // Built after the gallery is up: the cleared state and null resets use the configured defaults, which load with it.
      await gallery.updateFilters({ ...(args['replace'] === true ? clearedFilters() : {}), ...patchToUpdates(patch) });
      if (gallery.loadError()) throw new UiToolError('upstream_error', 'The gallery could not load photos for these filters.');
      return {
        applied: Object.keys(patch),
        total: gallery.total(),
        loaded: gallery.photos().length,
        filters: viewFilters(),
      };
    },

    ui_show_photos: async args => {
      const paths = stringList(args['paths']);
      if (paths.length === 0 || paths.length > MAX_SHOW_PATHS) {
        throw new UiToolError('invalid_input', `Give 1 to ${MAX_SHOW_PATHS} paths.`);
      }
      await leaveAlbum();
      await ensureGalleryView();
      const missing = await gallery.showPaths(paths);
      if (gallery.loadError()) throw new UiToolError('upstream_error', 'The gallery could not load these photos.');
      return {
        shown: gallery.photos().length,
        missing: missing.slice(0, 50),
        total: gallery.total(),
      };
    },

    ui_get_gallery_view: async args => {
      requireGalleryView();
      const limit = typeof args['limit'] === 'number' ? args['limit'] : 50;
      const photos = gallery.photos().slice(0, limit).map(photo => {
        const row = photo as unknown as Record<string, unknown>;
        return Object.fromEntries(COMPACT_KEYS.map(key => [key, row[key] ?? null]));
      });
      return {
        route: pathOf(router.url) || '/',
        filters: viewFilters(),
        sort: gallery.filters().sort,
        sort_direction: gallery.filters().sort_direction,
        total: gallery.total(),
        loaded: gallery.photos().length,
        has_more: gallery.hasMore(),
        photos,
        selection_count: gallery.selectionCount(),
        hidden_summary: gallery.hiddenSummary(),
        loading: gallery.loading(),
      };
    },

    ui_open_photo: async args => {
      const path = args['path'] as string;
      const ok = await router.navigate(['/photo'], { queryParams: { path }, onSameUrlNavigation: 'reload' });
      if (!ok) throw new UiToolError('not_found', 'The tab could not open that photo.');
      return { route: '/photo', path };
    },

    ui_select_photos: async args => {
      const paths = args['paths'] === undefined ? undefined : stringList(args['paths']);
      const selectView = args['select_view'] === true;
      const mode = (args['mode'] ?? 'replace') as 'replace' | 'add' | 'remove';
      if (selectView === (paths !== undefined && paths.length > 0)) {
        throw new UiToolError('invalid_input', 'Give exactly one of a non-empty `paths` and `select_view: true`.');
      }
      if (selectView) {
        if (mode === 'remove') throw new UiToolError('invalid_input', '`select_view` cannot be combined with mode "remove".');
        requireGalleryView();
        if (!gallery.canScopeSelectionToView()) {
          throw new UiToolError('invalid_input', 'This view (similar-photo, semantic search or an assistant-chosen list) cannot be selected as a whole.');
        }
        gallery.selectWholeView();
        return selectionSnapshot();
      }
      const wanted = paths ?? [];
      if (mode === 'replace') {
        gallery.restoreSelection(wanted);
        return selectionSnapshot();
      }
      // Under a view-scoped selection the edited set is the exclusion list, so adding a photo takes it OUT of that set.
      const viewScoped = gallery.viewScopeSelected();
      const edited = new Set(viewScoped ? gallery.excludedPaths() : gallery.selectedPaths());
      const insert = viewScoped ? mode === 'remove' : mode === 'add';
      const inView = new Set(gallery.photos().map(photo => photo.path));
      const notInView: string[] = [];
      for (const path of wanted) {
        if (viewScoped && insert && !inView.has(path)) notInView.push(path);
        else if (insert) edited.add(path);
        else edited.delete(path);
      }
      if (!viewScoped) {
        gallery.restoreSelection(edited);
      } else {
        gallery.excludedPaths.set(edited);
        // An exclusion outside the view would shrink the count below the number of photos actually selected.
        if (notInView.length) return { ...selectionSnapshot(), not_in_view: notInView.slice(0, SELECTION_PATH_LIMIT) };
      }
      return selectionSnapshot();
    },

    ui_clear_selection: async () => {
      gallery.clearSelection();
      return selectionSnapshot();
    },

    ui_get_selection: async () => selectionSnapshot(),

    ui_get_context: async args => {
      const route = pathOf(router.url) || '/';
      const inGallery = isGalleryUrl(router.url);
      const albumMatch = /^\/album\/(\d+)$/.exec(route);
      const params = new URLSearchParams(router.url.split('#')[0].split('?')[1] ?? '');
      const selection = selectionSnapshot();
      const pinned = gallery.pinnedPaths() !== null;
      const level = sessionLevel();
      const since = typeof args['activity_since'] === 'number' ? args['activity_since'] : 0;
      const focusedPath = inGallery
        ? gallery.focusedPath()
        : route === '/photo'
          ? params.get('path')
          : route === '/culling'
            ? journal.darkroomFocus()
            : null;
      return {
        route,
        focused: focusedPath ? { path: focusedPath } : null,
        user_activity: journal.since(since),
        ...(route === '/photo' && params.get('path') ? { query_path: params.get('path') } : {}),
        ...(albumMatch ? { album_id: Number(albumMatch[1]) } : {}),
        selection: { scope: selection['scope'], count: selection['count'] },
        gallery: inGallery
          ? { total: gallery.total(), loaded: gallery.photos().length, has_more: gallery.hasMore(), pinned }
          : null,
        culling: capCullingSnapshot(plan.snapshot()),
        culling_defaults: { profile: localStorage.getItem(CULL_PROFILE_KEY) || null, strictness: CULL_DEFAULT_STRICTNESS },
        mounted_actions: viewActions.names(),
        level,
        actions: applicableActions(actions(), actionFacts(route, gallery.selectionCount(), pinned), level),
      };
    },

    ui_next_page: async () => {
      requireGalleryView();
      const before = gallery.photos().length;
      if (gallery.hasMore()) await gallery.nextPage();
      return {
        loaded: gallery.photos().length,
        added: gallery.photos().length - before,
        total: gallery.total(),
        has_more: gallery.hasMore(),
      };
    },

    /**
     * Puts the compare page on the A/B tab for the user to answer. It only sets the page's own
     * state through the service: it never submits a comparison and sends no key event, so the
     * answer stays the user's click (ArrowLeft / ArrowRight / T are the page's answer shortcuts).
     */
    ui_show_comparison: async args => {
      if (!auth.isEdition()) throw new UiToolError('forbidden_level', 'The comparison page needs an edition session.');
      const category = typeof args['category'] === 'string' ? args['category'] : '';
      const strategy = typeof args['strategy'] === 'string' ? args['strategy'] : '';
      if (category) compareFilters.selectedCategory.set(category);
      if (strategy) compareFilters.strategy.set(strategy);
      compareFilters.activeTab.set(COMPARE_AB_TAB_INDEX);
      // Already there: navigating to the same URL resolves false, which is not a refusal.
      if (router.url.split(/[?#]/)[0] !== '/compare') {
        const ok = await router.navigate(['/compare']);
        if (!ok) throw new UiToolError('forbidden_level', 'The tab refused to open the comparison page.');
      }
      return {
        route: '/compare',
        category: compareFilters.selectedCategory() || null,
        strategy: compareFilters.strategy() || null,
        tab: 'ab',
      };
    },

    ui_show_culling_group: async args => {
      if (!auth.isEdition()) throw new UiToolError('forbidden_level', 'The darkroom needs an edition session.');
      const name = 'ui_show_culling_group';
      if (!viewActions.get(name)) {
        const ok = await router.navigate(['/culling']);
        if (!ok) throw new UiToolError('forbidden_level', 'The tab refused to open the darkroom.');
        await waitFor(() => viewActions.get(name) !== undefined);
      }
      const action = viewActions.get(name);
      if (!action) throw new UiToolError('no_active_view', 'The darkroom did not open.');
      return action(args);
    },

    /**
     * Pins the assistant's culling plan and opens /culling on it. The tab reproduces the plan itself (the
     * store posts `request` and `plan_digest` to `/culling/plan`), so no group data crosses the bridge.
     * The same digest as the held pin only moves the focus: nothing is re-fetched or re-seeded. A different
     * digest replaces the plan, which would throw away what the user decided but has not committed, so it
     * is refused with `unsaved_decisions` first. A plan the library has moved past is `plan_changed`.
     */
    ui_show_culling_plan: async args => {
      if (!auth.isEdition()) throw new UiToolError('forbidden_level', 'The darkroom needs an edition session.');
      const digest = args['plan_digest'] as string;
      const focus = typeof args['focus'] === 'number' ? args['focus'] : undefined;
      if (plan.pin()?.digest === digest) {
        if (focus !== undefined) plan.setFocus(focus);
      } else {
        if (plan.hasUnsavedDecisions()) {
          throw new UiToolError('unsaved_decisions', 'The user has decisions on the darkroom they have not confirmed; ask them to confirm or leave them first.');
        }
        plan.setPin({ digest, request: args['request'] as CullPlanRequest, focusNumber: focus });
      }
      const name = 'ui_show_culling_group';
      if (pathOf(router.url) !== '/culling' || !viewActions.get(name)) {
        if (!await router.navigate(['/culling'])) {
          plan.clear();
          throw new UiToolError('forbidden_level', 'The tab refused to open the darkroom.');
        }
        await waitFor(() => viewActions.get(name) !== undefined);
      }
      const loaded = (): boolean => plan.pin()?.digest !== digest || plan.snapshot()?.plan_digest === digest;
      if (!await waitFor(loaded)) throw new UiToolError('upstream_error', 'The plan did not load.');
      const snapshot = plan.snapshot();
      if (plan.pin()?.digest !== digest || !snapshot) {
        if (plan.loadFailure(digest) === 'failed') {
          throw new UiToolError('plan_load_failed', 'The tab could not load the plan; try again.');
        }
        throw new UiToolError('plan_changed', 'The library changed since the plan was previewed; preview again.');
      }
      return { route: '/culling', plan_digest: digest, groups_total: snapshot.groups_total };
    },
  };
}

/**
 * Byte budget of the `culling` block in `ui_get_context`. The bridge replaces a whole result above
 * 250 KiB with `too_large`, so the block is cut here, well under that, and the rest (activity,
 * actions) keeps its room.
 */
export const CULLING_BLOCK_BUDGET = 100 * 1024;

const CULLING_LISTS = ['confirmed', 'pending', 'changed'] as const;

/**
 * Trim the snapshot's lists from the tail until its JSON fits `CULLING_BLOCK_BUDGET`. The biggest list is
 * halved each round. A cut records the true size of every list in `<name>_count` (the fields the server's
 * `fit_culling` emits) and sets `truncated`; `groups_total` and `untouched` stay true. `plan_truncated`
 * is the plan's own cap and is never touched.
 */
export function capCullingSnapshot(snapshot: CullPlanSnapshot | null, budget = CULLING_BLOCK_BUDGET): Record<string, unknown> | null {
  if (!snapshot) return null;
  const size = (value: unknown): number => new TextEncoder().encode(JSON.stringify(value)).length;
  if (size(snapshot) <= budget) return { ...snapshot };
  const out: Record<string, unknown> = {
    ...snapshot,
    confirmed_count: snapshot.confirmed.length,
    pending_count: snapshot.pending.length,
    changed_count: snapshot.changed.length,
    truncated: true,
  };
  while (size(out) > budget) {
    let biggest: (typeof CULLING_LISTS)[number] | null = null;
    let biggestSize = 0;
    for (const name of CULLING_LISTS) {
      const list = out[name] as unknown[];
      const listSize = list.length ? size(list) : 0;
      if (listSize > biggestSize) {
        biggest = name;
        biggestSize = listSize;
      }
    }
    if (!biggest) break;
    const list = out[biggest] as unknown[];
    out[biggest] = list.slice(0, Math.floor(list.length / 2));
  }
  return out;
}
