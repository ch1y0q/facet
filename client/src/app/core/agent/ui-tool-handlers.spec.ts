import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router, provideRouter } from '@angular/router';
import { Component } from '@angular/core';
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
import { applicableActions, createUiToolHandlers } from './ui-tool-handlers';
import { ViewActionRegistry } from './view-action-registry.service';
import contractFile from './ui-tools.schema.json';
import { UI_TOOL_ERROR_CODES, UiToolContractFile, UiToolEnvelope } from './ui-tool.types';

@Component({ selector: 'app-stub-page', template: '' })
class StubPage {}

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
  let multiUser: boolean;
  let viewActions: ViewActionRegistry;

  const run = (name: string, args: unknown = {}): Promise<UiToolEnvelope> => registry.execute(name, args);
  /** The handlers without the registry's schema gate, to prove each one defends itself. */
  const direct = (): ReturnType<typeof createUiToolHandlers> => createUiToolHandlers({
    gallery: store, router: router as unknown as Router,
    auth: { isEdition: () => edition } as unknown as AuthService, viewActions, actions: () => [],
  });

  beforeEach(async () => {
    edition = false;
    multiUser = false;
    apiGet = vi.fn(() => of(photosResponse(['/a.jpg', '/b.jpg', '/c.jpg'])));
    navigate = vi.fn(() => Promise.resolve(true));
    router = { navigate, url: '/', events: of(), config: routes };
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { get: apiGet, post: vi.fn(() => of({})) } },
        { provide: Router, useValue: router },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
        { provide: AuthService, useValue: { isEdition: () => edition, isMultiUser: () => multiUser, isAuthenticated: () => true } },
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
        auth: { isEdition: () => edition } as unknown as AuthService, viewActions, actions: () => [],
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
      const rename: Record<string, string> = { person: 'person_id', category: 'type', semantic_query: 'semanticQuery', semantic_threshold: 'search_threshold' };
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

  describe('ui_navigate against the real client routes', () => {
    const contractRoutes = (): string[] => {
      const tool = (contractFile as unknown as UiToolContractFile).tools.find(t => t.name === 'ui_navigate');
      return (tool?.inputSchema.properties?.['route'] as { enum?: string[] } | undefined)?.enum ?? [];
    };

    it('every route the contract offers is a static path the app router defines', () => {
      const defined = new Set(routes.filter(r => r.path !== undefined && r.redirectTo === undefined).map(r => `/${r.path}`));
      expect(contractRoutes().length).toBeGreaterThan(10);
      expect(contractRoutes().filter(route => !defined.has(route))).toEqual([]);
    });

    it('a same-URL navigation resolves true on a real router instead of being skipped', async () => {
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [provideRouter([{ path: 'stats', component: StubPage }, { path: '', component: StubPage }])],
      });
      const realRouter = TestBed.inject(Router);
      await realRouter.navigateByUrl('/stats');
      const handlers = createUiToolHandlers({
        gallery: store, router: realRouter, auth: { isEdition: () => false } as unknown as AuthService, viewActions, actions: () => [],
      });
      await expect(handlers['ui_navigate']({ route: '/stats' })).resolves.toEqual({ route: '/stats' });
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

  describe('semantic and similar views', () => {
    it('maps a 0-1 semantic threshold to the percent string the store keeps', async () => {
      const result = await run('ui_set_gallery_filters', { patch: { semantic_query: 'red sunset', semantic_threshold: 0.25 }, replace: true });
      expect(result.ok).toBe(true);
      expect(store.filters()).toMatchObject({ semanticQuery: 'red sunset', search_threshold: '25' });
    });

    it('maps similar_to with its mode and a 0-1 floor to a percent string', async () => {
      await run('ui_set_gallery_filters', { patch: { similar_to: '/a.jpg', similarity_mode: 'color', min_similarity: 0.8 }, replace: true });
      expect(store.filters()).toMatchObject({ similar_to: '/a.jpg', similarity_mode: 'color', min_similarity: '80' });
    });

    it('keeps a fractional percent without rounding loss', async () => {
      await run('ui_set_gallery_filters', { patch: { similar_to: '/a.jpg', min_similarity: 0.855 } });
      expect(store.filters().min_similarity).toBe('85.5');
    });

    it('refuses similar_to together with semantic_query, applying nothing', async () => {
      const result = await run('ui_set_gallery_filters', { patch: { similar_to: '/a.jpg', semantic_query: 'x' } });
      expect(result).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(store.filters()).toMatchObject({ similar_to: '', semanticQuery: '' });
    });

    it('refuses a threshold above the slider ceiling and an unknown mode', async () => {
      expect(await direct()['ui_set_gallery_filters']({ patch: { semantic_query: 'x', semantic_threshold: 0.7 } }).catch((e: unknown) => e))
        .toMatchObject({ code: 'invalid_input' });
      expect(await direct()['ui_set_gallery_filters']({ patch: { similar_to: '/a.jpg', similarity_mode: 'nope' } }).catch((e: unknown) => e))
        .toMatchObject({ code: 'invalid_input' });
    });

    it('null puts the knobs back to the seeded or default values', async () => {
      await run('ui_set_gallery_filters', { patch: { semantic_query: 'x', semantic_threshold: 0.3 } });
      await run('ui_set_gallery_filters', { patch: { semantic_threshold: null, semantic_query: null } });
      expect(store.filters()).toMatchObject({ semanticQuery: '', search_threshold: '15' });
    });

    it('echoes the new keys in the view under contract names and 0-1 units', async () => {
      await run('ui_set_gallery_filters', { patch: { similar_to: '/a.jpg', similarity_mode: 'color', min_similarity: 0.8 } });
      let data = ((await run('ui_get_gallery_view', {})) as { data: { filters: Record<string, unknown> } }).data;
      expect(data.filters).toMatchObject({ similar_to: '/a.jpg', similarity_mode: 'color', min_similarity: 0.8 });
      await run('ui_set_gallery_filters', { patch: { semantic_query: 'x', semantic_threshold: 0.25 }, replace: true });
      data = ((await run('ui_get_gallery_view', {})) as { data: { filters: Record<string, unknown> } }).data;
      expect(data.filters).toMatchObject({ semantic_query: 'x', semantic_threshold: 0.25 });
      expect(data.filters).not.toHaveProperty('search_threshold');
    });
  });

  describe('replace on an album page', () => {
    it('leaves the album before applying, so no smart filter is saved for it', async () => {
      router.url = '/album/7';
      navigate.mockImplementationOnce(async () => {
        router.url = '/';
        store.galleryMounts.update(n => n + 1);
        return true;
      });
      const update = vi.spyOn(store, 'updateFilters');
      const result = await run('ui_set_gallery_filters', { patch: { camera: 'Canon' }, replace: true });
      expect(result.ok).toBe(true);
      expect(navigate).toHaveBeenCalledWith(['/']);
      expect(navigate.mock.invocationCallOrder[0]).toBeLessThan(update.mock.invocationCallOrder[0]);
      expect(TestBed.inject(AlbumService).update).not.toHaveBeenCalled();
    });

    it('does not navigate for a patch without replace', async () => {
      router.url = '/album/7';
      await run('ui_set_gallery_filters', { patch: { camera: 'Canon' } });
      expect(navigate).not.toHaveBeenCalledWith(['/']);
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

  describe('ui_show_photos', () => {
    const byPaths = (shown: string[], missing: string[]) => {
      const post = TestBed.inject(ApiService).post as unknown as Mock;
      post.mockImplementation(() => of({ photos: shown.map(path => makePhoto({ path })), total: shown.length, missing }));
      return post;
    };

    it('pins the list, reports what was missing, and leaves the filters alone', async () => {
      const post = byPaths(['/a.jpg', '/b.jpg', '/c.jpg'], ['/x.jpg', '/y.jpg']);
      const before = JSON.stringify(store.filters());
      const result = await run('ui_show_photos', { paths: ['/a.jpg', '/b.jpg', '/c.jpg', '/x.jpg', '/y.jpg'] });
      expect(result).toMatchObject({ ok: true, data: { shown: 3, missing: ['/x.jpg', '/y.jpg'], total: 3 } });
      expect(post).toHaveBeenCalledWith('/photos/by_paths', { paths: ['/a.jpg', '/b.jpg', '/c.jpg', '/x.jpg', '/y.jpg'] });
      expect(store.pinnedPaths()).toHaveLength(5);
      expect(JSON.stringify(store.filters())).toBe(before);
    });

    it('leaves an album page first, without saving a smart filter', async () => {
      byPaths(['/a.jpg'], []);
      router.url = '/album/3';
      navigate.mockImplementationOnce(async () => {
        router.url = '/';
        store.galleryMounts.update(n => n + 1);
        return true;
      });
      const result = await run('ui_show_photos', { paths: ['/a.jpg'] });
      expect(result.ok).toBe(true);
      expect(navigate).toHaveBeenCalledWith(['/']);
      expect(TestBed.inject(AlbumService).update).not.toHaveBeenCalled();
    });

    it('rejects an empty list and 201 paths before touching the gallery', async () => {
      const post = byPaths([], []);
      expect(await run('ui_show_photos', { paths: [] })).toMatchObject({ ok: false, error: 'invalid_input' });
      const tooMany = Array.from({ length: 201 }, (_, n) => `/p${n}.jpg`);
      expect(await run('ui_show_photos', { paths: tooMany })).toMatchObject({ ok: false, error: 'invalid_input' });
      expect(post).not.toHaveBeenCalled();
    });

    it('refuses selecting the whole view while the list is pinned', async () => {
      byPaths(['/a.jpg'], []);
      await run('ui_show_photos', { paths: ['/a.jpg'] });
      expect(await run('ui_select_photos', { select_view: true })).toMatchObject({ ok: false, error: 'invalid_input' });
    });

    it('is reported as pinned by ui_get_context', async () => {
      byPaths(['/a.jpg'], []);
      await run('ui_show_photos', { paths: ['/a.jpg'] });
      expect(await run('ui_get_context')).toMatchObject({ ok: true, data: { gallery: { pinned: true } } });
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

  describe('selection snapshot bounds', () => {
    beforeEach(async () => {
      await store.loadPhotos();
    });

    it('flags 1001 exclusions and reports the real count', async () => {
      await run('ui_select_photos', { select_view: true });
      store.excludedPaths.set(new Set(Array.from({ length: 1001 }, (_, i) => `/x${i}.jpg`)));
      const data = ((await run('ui_get_selection')) as { data: Record<string, unknown> }).data;
      expect(data['excluded_count']).toBe(1001);
      expect(data['excluded_truncated']).toBe(true);
      expect((data['excluded_paths'] as string[]).length).toBe(1000);
    });

    it('does not flag a view selection whose exclusions all fit', async () => {
      await run('ui_select_photos', { select_view: true });
      store.excludedPaths.set(new Set(['/x.jpg']));
      const data = ((await run('ui_get_selection')) as { data: Record<string, unknown> }).data;
      expect(data).toMatchObject({ excluded_count: 1, excluded_truncated: false });
    });

    it('measures paths as JSON-escaped encoded bytes, so escapes cannot overflow the frame', async () => {
      const paths = Array.from({ length: 300 }, (_, i) => `/${'"'.repeat(3000)}/${i}.jpg`);
      store.restoreSelection(paths);
      const data = ((await run('ui_get_selection')) as { data: Record<string, unknown> }).data;
      expect(data['truncated']).toBe(true);
      expect(new TextEncoder().encode(JSON.stringify(data)).length).toBeLessThan(200 * 1024);
    });

    it('cuts 3000 long paths to a 200 KB frame and marks the selection truncated', async () => {
      const paths = Array.from({ length: 3000 }, (_, i) => `/${'d'.repeat(3000)}/${i}.jpg`);
      store.restoreSelection(paths);
      const data = ((await run('ui_get_selection')) as { data: Record<string, unknown> }).data;
      expect(data['truncated']).toBe(true);
      expect(data['count']).toBe(3000);
      expect(JSON.stringify(data).length).toBeLessThan(200 * 1024);
      expect((data['paths'] as string[]).length).toBeLessThan(1000);
    });
  });

  describe('ui_get_context', () => {
    const context = async (): Promise<Record<string, unknown>> =>
      ((await run('ui_get_context')) as { data: Record<string, unknown> }).data;
    const jobIds = (data: Record<string, unknown>): string[] => (data['actions'] as { id: string }[]).map(a => a.id);

    it('reports the open photo of the detail route', async () => {
      router.url = '/photo?path=a.jpg';
      expect(await context()).toMatchObject({ route: '/photo', query_path: 'a.jpg', gallery: null });
    });

    it('reports the album id on an album page', async () => {
      router.url = '/album/7';
      expect(await context()).toMatchObject({ route: '/album/7', album_id: 7, gallery: { pinned: false } });
    });

    it('answers off the gallery with gallery null instead of throwing', async () => {
      router.url = '/stats';
      const data = await context();
      expect(data['gallery']).toBeNull();
      expect(data['selection']).toEqual({ scope: 'paths', count: 0 });
    });

    it('reports scope and count of a view selection and nothing else about it', async () => {
      await store.loadPhotos();
      await run('ui_select_photos', { select_view: true });
      const data = await context();
      expect(data['selection']).toEqual({ scope: 'view', count: 120 });
      expect(data['gallery']).toMatchObject({ total: 120, loaded: 3, has_more: false, pinned: false });
    });

    it('lists the registered page actions by name', async () => {
      const off = viewActions.register('ui_show_culling_group', async () => ({}));
      expect((await context())['mounted_actions']).toEqual(['ui_show_culling_group']);
      off();
      expect((await context())['mounted_actions']).toEqual([]);
    });

    it('lists the jobs that apply to the gallery and drops the tools above the session level', async () => {
      const data = await context();
      expect(data['level']).toBe('readonly');
      const ids = jobIds(data);
      expect(ids).toContain('steer_gallery');
      expect(ids).not.toContain('work_darkroom');
      expect(ids).not.toContain('edit_many');
      const rate = (data['actions'] as { id: string; tools: string[] }[]).find(a => a.id === 'rate_photos');
      expect(rate).toBeUndefined();
    });

    it('lists the editing jobs for an edition session once photos are selected', async () => {
      edition = true;
      await store.loadPhotos();
      store.restoreSelection(['/a.jpg']);
      const data = await context();
      expect(data['level']).toBe('edition');
      const edit = (data['actions'] as { id: string; tools: string[] }[]).find(a => a.id === 'edit_many');
      expect(edit?.tools).toContain('batch_set_rating');
      expect(jobIds(data)).toContain('cull_or_delete');
    });

    it('reports the user level of a signed-in multi-user session', async () => {
      multiUser = true;
      const data = await context();
      expect(data['level']).toBe('user');
      const rate = (data['actions'] as { id: string; tools: string[] }[]).find(a => a.id === 'rate_photos');
      expect(rate?.tools).toEqual(['set_rating', 'set_favorite', 'set_rejected']);
    });

    it('lists the darkroom job on /culling and not the selection jobs', async () => {
      edition = true;
      router.url = '/culling';
      const ids = jobIds(await context());
      expect(ids).toContain('work_darkroom');
      expect(ids).not.toContain('edit_many');
    });

    it('carries exactly the jobs of the generated table for the same facts', async () => {
      edition = true;
      router.url = '/stats';
      const rows = (contractFile as unknown as UiToolContractFile).actions;
      const expected = rows.filter(row => row.when.includes('any')).map(row => row.id);
      expect(jobIds(await context())).toEqual(expected);
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

describe('applicableActions', () => {
  const rows = [{ id: 'a', summary: 's', when: ['any'], tools: [{ name: 'read', required_level: 'readonly' }, { name: 'odd', required_level: 'mystery' }] }];

  it('fails closed on an unknown required level', () => {
    expect(applicableActions(rows, new Set(), 'edition')[0].tools).toEqual(['read']);
  });

  it('lists nothing for an unknown session level', () => {
    expect(applicableActions(rows, new Set(), 'mystery')).toEqual([]);
  });
});
