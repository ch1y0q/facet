import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';
import { of } from 'rxjs';
import { ApiService } from '../services/api.service';
import { AuthService } from '../services/auth.service';
import { AlbumService } from '../services/album.service';
import { I18nService } from '../services/i18n.service';
import { GalleryStore, PhotosResponse, ViewerConfig } from '../../features/gallery/gallery.store';
import { makePhoto } from '../../../testing/photo.fixture';
import { contractHandlerMismatch, WebMcpToolRegistry } from './webmcp-registry.service';
import { routes } from '../../app.routes';
import { DEFAULT_FILTERS } from '../../features/gallery/gallery-filters.util';
import { createUiToolHandlers } from './ui-tool-handlers';
import { ViewActionRegistry } from './view-action-registry.service';
import contractFile from './ui-tools.schema.json';
import { UI_TOOL_ERROR_CODES, UiToolContractFile, UiToolEnvelope } from './ui-tool.types';

const CONFIG = {
  pagination: { default_per_page: 64 },
  defaults: { type: '', sort: 'aggregate', sort_direction: 'DESC', hide_blinks: true, hide_bursts: true, hide_duplicates: true, hide_brackets: true, hide_panoramas: true, hide_details: true, tooltip_mode: 'hover', panel_activation: 'both', hide_rejected: true },
  display: { tags_per_photo: 5, card_width_px: 300, image_width_px: 640 },
  sort_options_grouped: null,
  features: {},
  quality_thresholds: { good: 6, great: 7, excellent: 8, best: 9 },
  search_threshold_default: 0.15,
} as unknown as ViewerConfig;

function photosResponse(paths: string[], hasMore = false): PhotosResponse {
  return {
    photos: paths.map(path => makePhoto({ path, filename: path.slice(1) })),
    total: 120, page: 1, per_page: 64, total_pages: 2, has_more: hasMore,
  };
}

describe('UI tool registry and handlers', () => {
  let registry: WebMcpToolRegistry;
  let store: GalleryStore;
  let apiGet: Mock;
  let navigate: Mock;
  let router: { navigate: Mock; url: string; events: unknown; config: unknown };
  let edition: boolean;
  let viewActions: ViewActionRegistry;

  const run = (name: string, args: unknown = {}): Promise<UiToolEnvelope> => registry.execute(name, args);
  /** The handlers without the registry's schema gate, to prove each one defends itself. */
  const direct = (): ReturnType<typeof createUiToolHandlers> => createUiToolHandlers({
    gallery: store, router: router as unknown as Router,
    auth: { isEdition: () => edition } as unknown as AuthService, viewActions,
  });

  beforeEach(async () => {
    edition = false;
    apiGet = vi.fn(() => of(photosResponse(['/a.jpg', '/b.jpg', '/c.jpg'])));
    navigate = vi.fn(() => Promise.resolve(true));
    router = { navigate, url: '/', events: of(), config: routes };
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { get: apiGet, post: vi.fn(() => of({})) } },
        { provide: Router, useValue: router },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
        { provide: AuthService, useValue: { isEdition: () => edition } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })), update: vi.fn(() => of({})) } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: (k: string) => k } },
      ],
    });
    store = TestBed.inject(GalleryStore);
    store.config.set(CONFIG);
    viewActions = TestBed.inject(ViewActionRegistry);
    registry = TestBed.inject(WebMcpToolRegistry);
    await registry.load();
  });

  describe('registry', () => {
    it('has a handler for every contract entry and a contract entry for every handler', () => {
      const handlers = createUiToolHandlers({
        gallery: store, router: router as unknown as Router,
        auth: { isEdition: () => edition } as unknown as AuthService, viewActions,
      });
      const mismatch = contractHandlerMismatch((contractFile as unknown as UiToolContractFile).tools, handlers);
      expect(mismatch).toEqual({ missingHandlers: [], missingContract: [] });
      expect(registry.toolNames.length).toBe((contractFile as unknown as UiToolContractFile).tools.length);
    });

    it('reports the error codes the server lets a tab use', () => {
      expect([...UI_TOOL_ERROR_CODES].sort()).toEqual((contractFile as unknown as UiToolContractFile).error_codes);
    });

    it('answers invalid_input for an enum violation and never throws', async () => {
      const result = await run('ui_navigate', { route: '/admin' });
      expect(result).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(navigate).not.toHaveBeenCalled();
    });

    it('rejects unknown properties and answers not_found for an unknown tool', async () => {
      expect(await run('ui_clear_selection', { surprise: 1 })).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(await run('ui_nope')).toMatchObject({ ok: false, error: 'not_found' });
    });

    it('reports a handler failure as upstream_error rather than throwing', async () => {
      navigate.mockRejectedValueOnce(new Error('boom'));
      expect(await run('ui_navigate', { route: '/stats' })).toMatchObject({ ok: false, error: 'upstream_error', message: 'boom' });
    });
  });

  describe('ui_navigate', () => {
    it('navigates to an allowed route with the query', async () => {
      const result = await run('ui_navigate', { route: '/stats', query: { year: 2024 } });
      expect(result.ok).toBe(true);
      expect(navigate).toHaveBeenCalledWith(['/stats'], { queryParams: { year: '2024' }, onSameUrlNavigation: 'reload' });
    });

    it('refuses edition-only routes for a non-edition session', async () => {
      for (const route of ['/culling', '/junk', '/compare', '/merge-suggestions']) {
        expect(await run('ui_navigate', { route })).toMatchObject({ ok: false, error: 'forbidden_level' });
      }
      expect(navigate).not.toHaveBeenCalled();
    });

    it('allows edition-only routes for an edition session', async () => {
      edition = true;
      expect((await run('ui_navigate', { route: '/culling' })).ok).toBe(true);
    });

    it('reports a refused navigation as forbidden_level', async () => {
      navigate.mockResolvedValueOnce(false);
      expect(await run('ui_navigate', { route: '/stats' })).toMatchObject({ ok: false, error: 'forbidden_level' });
    });
  });

  describe('prototype names', () => {
    it('are refused as filter keys by the schema and by the handler itself', async () => {
      for (const key of ['constructor', 'hasOwnProperty', 'toString', '__proto__']) {
        const patch = JSON.parse(`{"${key}":"x"}`);
        expect(await run('ui_set_gallery_filters', { patch })).toMatchObject({ ok: false, error: 'invalid_input' });
        await expect(direct()['ui_set_gallery_filters']({ patch })).rejects.toMatchObject({ code: 'invalid_input' });
      }
      expect(Object.hasOwn(store.filters(), 'constructor')).toBe(false);
      expect(Object.hasOwn(store.filters(), 'hasOwnProperty')).toBe(false);
    });
  });

  describe('contract parity', () => {
    it('every ui_set_gallery_filters patch key lands on a key of DEFAULT_FILTERS', () => {
      const tool = (contractFile as unknown as UiToolContractFile).tools.find(t => t.name === 'ui_set_gallery_filters');
      const patchKeys = Object.keys(tool?.inputSchema.properties?.['patch'].properties ?? {});
      const rename: Record<string, string> = { person: 'person_id', category: 'type' };
      expect(patchKeys.length).toBeGreaterThan(50);
      const orphans = patchKeys.filter(key => !Object.hasOwn(DEFAULT_FILTERS, rename[key] ?? key));
      expect(orphans).toEqual([]);
    });

    it('rejects category together with type, whichever comes first', async () => {
      expect(await run('ui_set_gallery_filters', { patch: { category: 'macro', type: 'portrait' } })).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(await run('ui_set_gallery_filters', { patch: { type: 'portrait', category: 'macro' } })).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(store.filters().type).toBe('');
    });

    it('echoes the contract names in the view, category rather than type', async () => {
      await run('ui_set_gallery_filters', { patch: { category: 'macro' } });
      const data = ((await run('ui_get_gallery_view', {})) as { data: { filters: Record<string, unknown> } }).data;
      expect(data.filters['category']).toBe('macro');
      expect(data.filters).not.toHaveProperty('type');
    });
  });

  describe('ui_navigate route restriction', () => {
    it('refuses anything that is not a static app route, before navigating', async () => {
      for (const route of ['//evil.example', 'https://evil.example', 'javascript:alert(1)', '/login', '/shared/album/1', '/album/3', '/nope', 'stats']) {
        await expect(direct()['ui_navigate']({ route })).rejects.toMatchObject({ code: 'invalid_input' });
      }
      expect(navigate).not.toHaveBeenCalled();
    });

    it('derives the edition-only pages from the route data, not a hand list', async () => {
      const editionRoutes = routes.filter(r => (r.data as { edition?: boolean } | undefined)?.edition).map(r => `/${r.path}`);
      expect(editionRoutes.length).toBeGreaterThan(0);
      for (const route of editionRoutes) {
        await expect(direct()['ui_navigate']({ route })).rejects.toMatchObject({ code: 'forbidden_level' });
      }
      expect(navigate).not.toHaveBeenCalled();
    });
  });

  describe('ui_set_gallery_filters', () => {
    it('writes the store filters and syncs the URL', async () => {
      const result = await run('ui_set_gallery_filters', { patch: { min_aesthetic: '7' } });
      expect(result).toMatchObject({ ok: true });
      expect(store.filters().min_aesthetic).toBe('7');
      expect(navigate).toHaveBeenCalledWith([], expect.objectContaining({
        queryParams: expect.objectContaining({ min_aesthetic: '7' }),
      }));
      expect(apiGet).toHaveBeenCalledWith('/photos', expect.objectContaining({ min_aesthetic: '7', page: 1 }));
    });

    it('stringifies numbers, renames person and upper-cases the sort direction', async () => {
      await run('ui_set_gallery_filters', { patch: { min_score: 8.5, person: 12, sort: 'date_taken', sort_direction: 'asc' } });
      expect(store.filters()).toMatchObject({ min_score: '8.5', person_id: '12', sort: 'date_taken', sort_direction: 'ASC' });
    });

    it('clears a filter with null', async () => {
      await run('ui_set_gallery_filters', { patch: { camera: 'Canon' } });
      await run('ui_set_gallery_filters', { patch: { camera: null } });
      expect(store.filters().camera).toBe('');
    });

    it('coerces booleans', async () => {
      await run('ui_set_gallery_filters', { patch: { hide_bursts: false, favorites_only: '1' } });
      expect(store.filters()).toMatchObject({ hide_bursts: false, favorites_only: true });
    });

    it('replace starts from no filters', async () => {
      await run('ui_set_gallery_filters', { patch: { camera: 'Canon', min_iso: 100 } });
      await run('ui_set_gallery_filters', { patch: { lens: '50mm' }, replace: true });
      expect(store.filters()).toMatchObject({ camera: '', min_iso: '', lens: '50mm' });
    });

    it('replace also lifts a set scope the user opened', async () => {
      await store.updateFilters({ sequence_group_id: '4', sequence_kind: 'burst', burst_group_id: '4', duplicate_group_id: '2' });
      await run('ui_set_gallery_filters', { patch: { lens: '50mm' }, replace: true });
      expect(store.filters()).toMatchObject({ sequence_group_id: '', sequence_kind: '', burst_group_id: '', duplicate_group_id: '' });
    });

    it('refuses a filter the tab cannot show, without applying the rest', async () => {
      const result = await run('ui_set_gallery_filters', { patch: { camera: 'Canon', junk_kind: 'blurry' } });
      expect(result).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(store.filters().camera).toBe('');
    });

    it('opens the gallery first when another page is showing', async () => {
      router.url = '/stats';
      navigate.mockImplementationOnce(async () => {
        router.url = '/';
        store.galleryMounts.update(n => n + 1);
        return true;
      });
      const pending = run('ui_set_gallery_filters', { patch: { camera: 'Canon' } });
      expect((await pending).ok).toBe(true);
      expect(navigate).toHaveBeenCalledWith(['/']);
    });
  });

  describe('ui_get_gallery_view', () => {
    it('returns filters, the visible rows and the selection count', async () => {
      await run('ui_set_gallery_filters', { patch: { min_aesthetic: '7', person: '3' } });
      const result = await run('ui_get_gallery_view', { limit: 2 });
      expect(result.ok).toBe(true);
      const data = (result as { data: Record<string, unknown> }).data;
      expect((data['photos'] as { path: string }[]).map(p => p.path)).toEqual(['/a.jpg', '/b.jpg']);
      expect(data['total']).toBe(120);
      expect(data['filters']).toMatchObject({ min_aesthetic: '7', person: '3' });
      expect(data['filters']).not.toHaveProperty('page');
      expect(data['route']).toBe('/');
    });

    it('answers no_active_view away from the gallery', async () => {
      router.url = '/stats';
      expect(await run('ui_get_gallery_view', {})).toMatchObject({ ok: false, error: 'no_active_view' });
    });
  });

  describe('ui_open_photo', () => {
    it('navigates to /photo?path=', async () => {
      await run('ui_open_photo', { path: '/x/y.jpg' });
      expect(navigate).toHaveBeenCalledWith(['/photo'], { queryParams: { path: '/x/y.jpg' }, onSameUrlNavigation: 'reload' });
    });
  });

  describe('selection', () => {
    beforeEach(async () => {
      await store.loadPhotos();
    });

    it('requires exactly one of paths and select_view', async () => {
      expect(await run('ui_select_photos', {})).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(await run('ui_select_photos', { paths: [] })).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(await run('ui_select_photos', { paths: ['/a.jpg'], select_view: true })).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(store.selectionCount()).toBe(0);
    });

    it('rejects select_view with mode remove', async () => {
      expect(await run('ui_select_photos', { select_view: true, mode: 'remove' })).toMatchObject({ ok: false, error: 'invalid_input' });
    });

    it('replaces, adds and removes explicit paths', async () => {
      await run('ui_select_photos', { paths: ['/a.jpg', '/b.jpg'] });
      expect([...store.selectedPaths()]).toEqual(['/a.jpg', '/b.jpg']);
      await run('ui_select_photos', { paths: ['/c.jpg'], mode: 'add' });
      expect(store.selectionCount()).toBe(3);
      await run('ui_select_photos', { paths: ['/a.jpg'], mode: 'remove' });
      expect([...store.selectedPaths()].sort()).toEqual(['/b.jpg', '/c.jpg']);
    });

    it('selects the whole view in view scope, and remove then excludes paths', async () => {
      const result = await run('ui_select_photos', { select_view: true });
      expect(store.selectionScope()).toBe('view');
      expect(result).toMatchObject({ ok: true, data: { scope: 'view', count: 120 } });
      await run('ui_select_photos', { paths: ['/a.jpg'], mode: 'remove' });
      expect([...store.excludedPaths()]).toEqual(['/a.jpg']);
      const selection = await run('ui_get_selection');
      expect(selection).toMatchObject({ ok: true, data: { scope: 'view', count: 119, excluded_paths: ['/a.jpg'] } });
      expect((selection as { data: { filters: unknown } }).data.filters).toMatchObject({ hide_bursts: 'true' });
      await run('ui_select_photos', { paths: ['/a.jpg'], mode: 'add' });
      expect(store.excludedPaths().size).toBe(0);
    });

    it('remove under view scope ignores paths that are not in the view, so the count stays right', async () => {
      await run('ui_select_photos', { select_view: true });
      const result = await run('ui_select_photos', { paths: ['/zzz.jpg', '/a.jpg'], mode: 'remove' });
      expect([...store.excludedPaths()]).toEqual(['/a.jpg']);
      expect(store.selectionCount()).toBe(119);
      expect(result).toMatchObject({ ok: true, data: { count: 119, not_in_view: ['/zzz.jpg'] } });
    });

    it('refuses select_view when the view cannot be a filter', async () => {
      store.filters.update(f => ({ ...f, semanticQuery: 'sunset' }));
      expect(await run('ui_select_photos', { select_view: true })).toMatchObject({ ok: false, error: 'invalid_input' });
    });

    it('clears the selection', async () => {
      await run('ui_select_photos', { select_view: true });
      await run('ui_clear_selection');
      expect(store.selectionScope()).toBe('paths');
      expect(store.selectionCount()).toBe(0);
    });
  });

  describe('ui_next_page', () => {
    it('loads the next page', async () => {
      apiGet.mockReturnValue(of(photosResponse(['/a.jpg'], true)));
      await store.loadPhotos();
      apiGet.mockReturnValue(of(photosResponse(['/d.jpg'], false)));
      const result = await run('ui_next_page');
      expect(result).toMatchObject({ ok: true, data: { added: 1, loaded: 2, has_more: false } });
    });

    it('answers no_active_view away from the gallery', async () => {
      router.url = '/albums';
      expect(await run('ui_next_page')).toMatchObject({ ok: false, error: 'no_active_view' });
    });
  });

  describe('ui_show_culling_group', () => {
    it('is refused for a non-edition session', async () => {
      expect(await run('ui_show_culling_group', { type: 'burst', group_id: 1 })).toMatchObject({ ok: false, error: 'forbidden_level' });
    });

    it('calls the registered darkroom action with the group identity', async () => {
      edition = true;
      const action = vi.fn(async () => ({ shown: true }));
      const unregister = viewActions.register('ui_show_culling_group', action);
      const result = await run('ui_show_culling_group', { type: 'scene', group_id: 4 });
      expect(result).toEqual({ ok: true, data: { shown: true } });
      expect(action).toHaveBeenCalledWith({ type: 'scene', group_id: 4 });
      expect(navigate).not.toHaveBeenCalled();
      unregister();
      expect(viewActions.get('ui_show_culling_group')).toBeUndefined();
    });

    it('answers no_active_view when the darkroom never registers', async () => {
      edition = true;
      vi.useFakeTimers();
      try {
        const pending = run('ui_show_culling_group', { type: 'burst', group_id: 1 });
        await vi.advanceTimersByTimeAsync(11_000);
        expect(await pending).toMatchObject({ ok: false, error: 'no_active_view' });
        expect(navigate).toHaveBeenCalledWith(['/culling']);
      } finally {
        vi.useRealTimers();
      }
    });
  });
});
