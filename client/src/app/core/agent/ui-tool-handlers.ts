import { Router } from '@angular/router';
import { AuthService } from '../services/auth.service';
import { GalleryStore } from '../../features/gallery/gallery.store';
import {
  DEFAULT_FILTERS,
  GalleryFilters,
  RANGE_AND_SELECT_KEYS,
  buildApiParams,
} from '../../features/gallery/gallery-filters.util';
import { ViewActionRegistry } from './view-action-registry.service';
import { UiToolError, UiToolHandler } from './ui-tool.types';

export interface UiToolDeps {
  gallery: GalleryStore;
  router: Router;
  auth: AuthService;
  viewActions: ViewActionRegistry;
}

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
};

const CLIENT_TO_CONTRACT_KEY: Record<string, string> = { person_id: 'person', type: 'category' };

const SELECTION_PATH_LIMIT = 1000;
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

function stringList(value: unknown): string[] {
  return Array.isArray(value) ? value.filter((v): v is string => typeof v === 'string') : [];
}

export function createUiToolHandlers(deps: UiToolDeps): Record<string, UiToolHandler> {
  const { gallery, router, auth, viewActions } = deps;

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
        updates[clientKey] = filterDefault(clientKey);
      } else if (typeof DEFAULT_FILTERS[clientKey] === 'boolean') {
        updates[clientKey] = toBoolean(contractKey, value);
      } else if (clientKey === 'sort_direction') {
        updates[clientKey] = String(value).toUpperCase();
      } else {
        updates[clientKey] = String(value);
      }
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
    if (f.semanticQuery) out['semantic_query'] = f.semanticQuery;
    if (f.similar_to) out['similar_to'] = f.similar_to;
    return out;
  };

  const selectionSnapshot = (): Record<string, unknown> => {
    if (gallery.viewScopeSelected()) {
      return {
        scope: 'view',
        count: gallery.selectionCount(),
        filters: gallery.filterPayload(),
        excluded_paths: [...gallery.excludedPaths()].slice(0, SELECTION_PATH_LIMIT),
      };
    }
    const paths = [...gallery.selectedPaths()];
    return {
      scope: 'paths',
      count: paths.length,
      paths: paths.slice(0, SELECTION_PATH_LIMIT),
      ...(paths.length > SELECTION_PATH_LIMIT ? { truncated: true } : {}),
    };
  };

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
      const ok = await router.navigate([route], { queryParams });
      if (!ok) throw new UiToolError('forbidden_level', `The tab refused to open ${route}.`);
      return { route: pathOf(router.url) || '/' };
    },

    ui_set_gallery_filters: async args => {
      const patch = (args['patch'] ?? {}) as Record<string, unknown>;
      patchToUpdates(patch);
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
      const ok = await router.navigate(['/photo'], { queryParams: { path } });
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
          throw new UiToolError('invalid_input', 'This view (similar-photo or semantic search) cannot be selected as a whole.');
        }
        gallery.selectWholeView();
        return selectionSnapshot();
      }
      const wanted = paths ?? [];
      if (gallery.viewScopeSelected()) {
        // Under a view-scoped selection, adding/removing photos edits the exclusion list.
        if (mode === 'replace') {
          gallery.restoreSelection(wanted);
        } else {
          const excluded = new Set(gallery.excludedPaths());
          const inView = new Set(gallery.photos().map(photo => photo.path));
          const notInView: string[] = [];
          for (const path of wanted) {
            if (mode === 'add') excluded.delete(path);
            else if (inView.has(path)) excluded.add(path);
            else notInView.push(path);
          }
          gallery.excludedPaths.set(excluded);
          // An exclusion outside the view would shrink the count below the number of photos actually selected.
          return notInView.length ? { ...selectionSnapshot(), not_in_view: notInView.slice(0, SELECTION_PATH_LIMIT) } : selectionSnapshot();
        }
        return selectionSnapshot();
      }
      if (mode === 'replace') {
        gallery.restoreSelection(wanted);
      } else {
        const next = new Set(gallery.selectedPaths());
        for (const path of wanted) {
          if (mode === 'add') next.add(path);
          else next.delete(path);
        }
        gallery.restoreSelection(next);
      }
      return selectionSnapshot();
    },

    ui_clear_selection: async () => {
      gallery.clearSelection();
      return selectionSnapshot();
    },

    ui_get_selection: async () => selectionSnapshot(),

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
  };
}
