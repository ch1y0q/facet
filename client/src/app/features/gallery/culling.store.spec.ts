import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { Subject, of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { CullingStore, CullingNotice } from './culling.store';
import type { CullingGroup } from './burst-culling.pipes';

function makeGroup(id: number, type: string, paths: string[], best: string): CullingGroup {
  return {
    group_id: id,
    type,
    reason: '',
    photos: paths.map((path, i) => ({
      path, filename: path.slice(1), aggregate: 8, aesthetic: 7, tech_sharpness: 6,
      is_blink: 0, is_burst_lead: i === 0 ? 1 : 0, date_taken: '2024-01-01', burst_score: 9 - i,
    })),
    best_path: best,
    count: paths.length,
  } as unknown as CullingGroup;
}

const GROUPS_RESPONSE = {
  groups: [
    makeGroup(1, 'burst', ['/a.jpg', '/b.jpg'], '/a.jpg'),
    makeGroup(2, 'similar', ['/c.jpg', '/d.jpg'], '/c.jpg'),
  ],
  total_groups: 2, page: 1, per_page: 20, total_pages: 1,
};

const PREVIEW = {
  groups_processed: 2, kept: 2, rejected: 2, highlights_added: 0,
  dry_run: true, preview: [], next_cursor: null, plan_digest: 'digest',
};

// The component spec's original feed, kept verbatim so the moved tests read the same.
const PHOTO_GROUP_FEED = {
  groups: [
    {
      group_id: 1, type: 'burst', reason: '0.8s apart', best_path: '/photo1.jpg', count: 3,
      photos: [
        { path: '/photo1.jpg', filename: 'photo1.jpg', aggregate: 8.5, aesthetic: 7.0, tech_sharpness: 6.0, is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-01', burst_score: 9.0 },
        { path: '/photo2.jpg', filename: 'photo2.jpg', aggregate: 7.0, aesthetic: 6.5, tech_sharpness: 5.5, is_blink: 0, is_burst_lead: 0, date_taken: '2024-01-01', burst_score: 7.0 },
        { path: '/photo3.jpg', filename: 'photo3.jpg', aggregate: 5.0, aesthetic: 5.0, tech_sharpness: 4.0, is_blink: 1, is_burst_lead: 0, date_taken: '2024-01-01', burst_score: 4.0 },
      ],
    },
    {
      group_id: 2, type: 'similar', reason: '85% similar', best_path: '/photo4.jpg', count: 2,
      photos: [
        { path: '/photo4.jpg', filename: 'photo4.jpg', aggregate: 9.0, aesthetic: 8.5, tech_sharpness: 7.0, is_blink: 0, is_burst_lead: 1, date_taken: '2024-01-02', burst_score: 9.5 },
        { path: '/photo5.jpg', filename: 'photo5.jpg', aggregate: 6.0, aesthetic: 5.0, tech_sharpness: 5.0, is_blink: 0, is_burst_lead: 0, date_taken: '2024-01-02', burst_score: 5.5 },
      ],
    },
  ],
  total_groups: 2, page: 1, per_page: 20, total_pages: 1,
};

describe('CullingStore', () => {
  let store: CullingStore;
  let api: { get: Mock; post: Mock };
  let notices: CullingNotice[];

  beforeEach(() => {
    localStorage.clear();
    api = {
      get: vi.fn((path: string) => of(path === '/culling-groups' ? GROUPS_RESPONSE : {})),
      post: vi.fn(() => of({})),
    };
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: api },
        { provide: I18nService, useValue: { t: vi.fn((key: string) => key) } },
      ],
    });
    store = TestBed.inject(CullingStore);
    notices = [];
    store.notice$.subscribe(n => notices.push(n));
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  describe('group loading', () => {
    it('loads page 1 with the feed params and auto-selects the best frame', async () => {
      await store.loadGroups();
      expect(api.get).toHaveBeenCalledWith('/culling-groups', expect.objectContaining({
        page: 1, per_page: 20, sort: 'easiest', group_by: 'all', exclude_rejected: true,
      }));
      expect(store.groups()).toHaveLength(2);
      expect(store.totalGroups()).toBe(2);
      expect(store.loading()).toBe(false);
      expect([...store.selectionsMap().get(1) ?? []]).toEqual(['/a.jpg']);
    });

    it('reports a failed load as a notice and leaves the feed untouched', async () => {
      api.get.mockReturnValue(throwError(() => new Error('boom')));
      await store.loadGroups();
      expect(notices).toEqual([{ key: 'culling.error_loading', duration: 2000 }]);
      expect(store.groups()).toEqual([]);
      expect(store.loading()).toBe(false);
    });

    it('drops a response that a feed reset overtook', async () => {
      const late = new Subject<typeof GROUPS_RESPONSE>();
      api.get.mockReturnValue(late);
      const pending = store.loadGroups();
      store.resetFeed();
      late.next(GROUPS_RESPONSE);
      late.complete();
      await pending;
      expect(store.groups()).toEqual([]);
      expect(store.selectionsMap().size).toBe(0);
    });

    it('stays silent about a failure that a feed reset overtook', async () => {
      const late = new Subject<typeof GROUPS_RESPONSE>();
      api.get.mockReturnValue(late);
      const pending = store.loadGroups();
      store.resetFeed();
      late.error(new Error('late'));
      await pending;
      expect(notices).toEqual([]);
    });

    it('appends the next page and keeps the earlier selections', async () => {
      await store.loadGroups();
      store.totalPages.set(2);
      api.get.mockReturnValue(of({
        ...GROUPS_RESPONSE, groups: [makeGroup(3, 'burst', ['/e.jpg'], '/e.jpg')], total_pages: 2,
      }));
      await store.loadMore();
      expect(store.groups().map(g => g.group_id)).toEqual([1, 2, 3]);
      expect(store.currentPage()).toBe(2);
      expect(store.selectionsMap().has(1)).toBe(true);
      expect(store.selectionsMap().has(3)).toBe(true);
    });

    it('clears loadingMore when a feed reset overtakes a page request, so scrolling works again', async () => {
      await store.loadGroups();
      store.totalPages.set(3);
      const late = new Subject<typeof GROUPS_RESPONSE>();
      api.get.mockReturnValue(late);
      const pending = store.loadMore();
      expect(store.loadingMore()).toBe(true);
      store.resetFeed();
      expect(store.loadingMore()).toBe(false);
      late.next(GROUPS_RESPONSE);
      late.complete();
      await pending;
      expect(store.loadingMore()).toBe(false);
      expect(store.groups()).toEqual([]);
    });

    it('does not start a second page request while one is in flight', async () => {
      await store.loadGroups();
      store.totalPages.set(3);
      const pending = new Subject<typeof GROUPS_RESPONSE>();
      api.get.mockClear();
      api.get.mockReturnValue(pending);
      const first = store.loadMore();
      await store.loadMore();
      expect(api.get).toHaveBeenCalledTimes(1);
      pending.next({ ...GROUPS_RESPONSE, groups: [], total_pages: 3 });
      pending.complete();
      await first;
      expect(store.currentPage()).toBe(2);
    });
  });

  describe('confirming groups', () => {
    beforeEach(async () => {
      await store.loadGroups();
    });

    it('refuses a group with nothing kept', () => {
      store.selectionsMap.set(new Map([[1, new Set<string>()]]));
      expect(store.confirmGroup(store.groups()[0])).toBe(false);
      expect(api.post).not.toHaveBeenCalled();
    });

    it('posts the group identity, every path and the kept paths once the cooldown elapses', async () => {
      vi.useFakeTimers();
      expect(store.confirmGroup(store.groups()[0])).toBe(true);
      expect(store.confirmedGroups().has('1_burst')).toBe(true);
      expect(api.post).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(store.passCountdownSeconds * 1000);
      expect(api.post).toHaveBeenCalledWith('/culling-groups/confirm', {
        group_id: 1, type: 'burst', paths: ['/a.jpg', '/b.jpg'], keep_paths: ['/a.jpg'],
      });
      expect(store.hiddenGroups().has('1_burst')).toBe(true);
    });

    it('commits nothing when the cooldown is cancelled', async () => {
      vi.useFakeTimers();
      const group = store.groups()[0];
      store.confirmGroup(group);
      store.cancelPass(group);
      await vi.advanceTimersByTimeAsync(store.passCountdownSeconds * 1000);
      expect(api.post).not.toHaveBeenCalled();
      expect(store.confirmedGroups().has('1_burst')).toBe(false);
    });

    it('flushes a pending confirm instead of dropping it when the timers are cleared', () => {
      vi.useFakeTimers();
      store.confirmGroup(store.groups()[0]);
      store.clearAllPassTimers();
      expect(api.post).toHaveBeenCalledWith('/culling-groups/confirm', expect.objectContaining({ group_id: 1 }));
    });

    it('un-confirms the group and notifies when the commit fails', async () => {
      vi.useFakeTimers();
      api.post.mockReturnValue(throwError(() => new Error('nope')));
      store.confirmGroup(store.groups()[0]);
      await vi.advanceTimersByTimeAsync(store.passCountdownSeconds * 1000);
      expect(store.confirmedGroups().has('1_burst')).toBe(false);
      expect(notices).toEqual([{ key: 'culling.error_confirming', duration: 2000 }]);
    });

    it('confirms all remaining groups with their own payloads and marks the unkept ones done', async () => {
      store.selectionsMap.set(new Map([[1, new Set(['/a.jpg', '/b.jpg'])]]));
      await store.confirmAllRemaining(store.groups());
      expect(api.post).toHaveBeenCalledTimes(1);
      expect(api.post).toHaveBeenCalledWith('/culling-groups/confirm', {
        group_id: 1, type: 'burst', paths: ['/a.jpg', '/b.jpg'], keep_paths: ['/a.jpg', '/b.jpg'],
      });
      expect([...store.confirmedGroups()].sort()).toEqual(['1_burst', '2_similar']);
      expect(store.confirming()).toBe(false);
      expect(notices).toEqual([{ key: 'culling.confirmed', duration: 2000 }]);
    });

    it('reports a failed batch and stops confirming', async () => {
      api.post.mockReturnValue(throwError(() => new Error('nope')));
      await store.confirmAllRemaining(store.groups());
      expect(notices).toEqual([{ key: 'culling.error_auto_select', duration: 2000 }]);
      expect(store.confirming()).toBe(false);
      expect(store.confirmedGroups().size).toBe(0);
    });
  });

  describe('auto-cull', () => {
    const autoCalls = () => api.post.mock.calls.filter(c => c[0] === '/culling/auto');

    beforeEach(() => {
      api.post.mockImplementation((path: string) => of(path === '/culling/auto' ? PREVIEW : {}));
    });

    it('previews with dry_run true and publishes the preview with its request snapshot', async () => {
      expect(await store.openAutoCull()).toBe('landed');
      expect(autoCalls()).toHaveLength(1);
      expect(autoCalls()[0][1]).toMatchObject({
        dry_run: true, group_by: 'all', strictness: 100, trim_brackets: false,
      });
      expect(store.autoCullPreview()).toEqual(PREVIEW);
      expect(store.autoCullRequest()).toBe(autoCalls()[0][1]);
      expect(store.autoCullLoading()).toBe(false);
    });

    it('applies nothing when no preview was agreed to', async () => {
      const applied = vi.fn();
      await store.confirmAutoCull(applied);
      expect(autoCalls()).toHaveLength(0);
      expect(applied).not.toHaveBeenCalled();
    });

    it('applies the preview verbatim with dry_run flipped, after the preview, then hands control back', async () => {
      await store.openAutoCull();
      const previewBody = autoCalls()[0][1];
      const applied = vi.fn(() => {
        expect(store.autoCullPreview()).toBeNull();
      });
      await store.confirmAutoCull(applied);
      expect(autoCalls()).toHaveLength(2);
      expect(autoCalls()[1][1]).toEqual({ ...previewBody, dry_run: false, highlights_album: '' });
      expect(applied).toHaveBeenCalledTimes(1);
      expect(store.autoCullApplying()).toBe(false);
      expect(notices).toEqual([{
        key: 'culling.auto_cull.applied', params: { kept: 2, rejected: 2 }, duration: 3000,
      }]);
    });

    it('keeps the highlights album name only when the checkbox is ticked', async () => {
      await store.openAutoCull();
      const album = (autoCalls()[0][1] as { highlights_album: string }).highlights_album;
      expect(album).not.toBe('');
      store.autoCullHighlights.set(true);
      await store.confirmAutoCull(() => {});
      expect((autoCalls()[1][1] as { highlights_album: string }).highlights_album).toBe(album);
    });

    it('refuses a second apply while the first is in flight', async () => {
      await store.openAutoCull();
      const response = new Subject<typeof PREVIEW>();
      api.post.mockReturnValue(response);
      const first = store.confirmAutoCull(() => {});
      expect(store.autoCullApplying()).toBe(true);
      await store.confirmAutoCull(() => {});
      expect(autoCalls()).toHaveLength(2);
      response.next({ ...PREVIEW, dry_run: false });
      response.complete();
      await first;
      expect(autoCalls()).toHaveLength(2);
    });

    it('ignores cancel while the apply is in flight', async () => {
      await store.openAutoCull();
      const response = new Subject<typeof PREVIEW>();
      api.post.mockReturnValue(response);
      const applying = store.confirmAutoCull(() => {});
      store.cancelAutoCull();
      expect(store.autoCullPreview()).not.toBeNull();
      response.next(PREVIEW);
      response.complete();
      await applying;
      expect(store.autoCullPreview()).toBeNull();
    });

    it('keeps the dialog and reports when the apply fails', async () => {
      await store.openAutoCull();
      api.post.mockReturnValue(throwError(() => new Error('nope')));
      const applied = vi.fn();
      await store.confirmAutoCull(applied);
      expect(applied).not.toHaveBeenCalled();
      expect(store.autoCullPreview()).not.toBeNull();
      expect(store.autoCullApplying()).toBe(false);
      expect(notices).toEqual([{ key: 'culling.auto_cull.error', duration: 2000 }]);
    });

    it('drops a superseded dry run so the newer preview wins', async () => {
      const first = new Subject<typeof PREVIEW>();
      api.post.mockReturnValueOnce(first);
      const stale = store.openAutoCull();
      api.post.mockReturnValueOnce(of({ ...PREVIEW, kept: 9 }));
      expect(await store.openAutoCull()).toBe('landed');
      first.next({ ...PREVIEW, kept: 1 });
      first.complete();
      expect(await stale).toBe('superseded');
      expect(store.autoCullPreview()?.kept).toBe(9);
    });
  });


  // Moved from burst-culling.component.spec.ts: these drove the store through the
  // component's pass-through members and never touched the component itself.
  describe('selection and paging on the three-photo feed', () => {
    beforeEach(() => {
      api.get.mockReturnValue(of(PHOTO_GROUP_FEED));
    });

    describe('initial state', () => {
      it('should have loading as a signal function', () => {
        expect(typeof store.loading).toBe('function');
      });

      it('should start with confirming false', () => {
        expect(store.confirming()).toBe(false);
      });
    });

    describe('loadMore', () => {
      it('should append groups from the next page', async () => {
        await store.loadGroups();
        store.totalPages.set(2);

        const page2Response = {
          groups: [{ group_id: 3, type: 'burst', reason: '1s apart', photos: [], best_path: '', count: 0 }],
          total_groups: 3, page: 2, per_page: 20, total_pages: 2,
        };
        api.get.mockReturnValue(of(page2Response));

        await store.loadMore();

        expect(store.groups()).toHaveLength(3);
        expect(store.currentPage()).toBe(2);
      });

      it('should not load if no more pages', async () => {
        await store.loadGroups();
        api.get.mockClear();

        await store.loadMore();

        expect(api.get).not.toHaveBeenCalled();
      });
    });

    describe('toggleSelection', () => {
      beforeEach(async () => {
        await store.loadGroups();
      });

      it('should add a photo to the selection when not already selected', () => {
        const group = store.groups()[0];
        store.toggleSelection('/photo2.jpg', group);

        const kept = store.selectionsMap().get(1);
        expect(kept?.has('/photo2.jpg')).toBe(true);
      });

      it('should remove a photo from the selection when already selected', () => {
        const group = store.groups()[0];
        // photo1.jpg is auto-selected as best_path
        store.toggleSelection('/photo1.jpg', group);

        const kept = store.selectionsMap().get(1);
        expect(kept?.has('/photo1.jpg')).toBe(false);
      });

      it('should allow multiple photos to be selected', () => {
        const group = store.groups()[0];
        store.toggleSelection('/photo2.jpg', group);
        store.toggleSelection('/photo3.jpg', group);

        const kept = store.selectionsMap().get(1);
        expect(kept?.has('/photo1.jpg')).toBe(true); // auto-selected
        expect(kept?.has('/photo2.jpg')).toBe(true);
        expect(kept?.has('/photo3.jpg')).toBe(true);
      });

      it('should not mutate original map', () => {
        const originalMap = store.selectionsMap();
        const group = store.groups()[0];
        store.toggleSelection('/photo2.jpg', group);
        const newMap = store.selectionsMap();

        expect(newMap).not.toBe(originalMap);
      });
    });

    // Double-click on a tile. For an ordinary burst/similar/scene it is the
    // fast "keep only this one" gesture the feature exists for. For a bracket
    // or a pan the frames were shot to be merged, not to compete -- the same
    // reason computeAutoKeep starts every frame of those kinds KEPT and the
    // auto-cull button hides in that granularity -- so it must be a no-op there.
    describe('selectExclusive (double-click)', () => {
      const buildKeepWholeGroup = (kind: 'bracket' | 'panorama' | 'hdr_panorama') => ({
        group_id: 42,
        type: kind,
        reason: '3 frames',
        sequence_kind: kind,
        best_path: '/kw0.jpg',
        count: 3,
        photos: [0, 1, 2].map(i => ({
          path: `/kw${i}.jpg`, filename: `kw${i}.jpg`, aggregate: 5, aesthetic: 5,
          tech_sharpness: 5, is_blink: 0, is_burst_lead: 0, date_taken: '2025-04-15',
          burst_score: 5, sequence_kind: kind,
        })),
      });

      it('refuses to reduce a bracket set to a single frame', () => {
        const group = buildKeepWholeGroup('bracket');
        store.groups.set([group] as never);
        store.selectionsMap.set(
          new Map([[group.group_id, new Set(group.photos.map(p => p.path))]]),
        );

        store.selectExclusive('/kw1.jpg', group as never);

        const kept = store.selectionsMap().get(group.group_id);
        expect(kept?.size).toBe(3);
        expect([...(kept ?? [])].sort()).toEqual(['/kw0.jpg', '/kw1.jpg', '/kw2.jpg']);
      });

      it('refuses to reduce a panorama set to a single frame', () => {
        const group = buildKeepWholeGroup('panorama');
        store.groups.set([group] as never);
        store.selectionsMap.set(
          new Map([[group.group_id, new Set(group.photos.map(p => p.path))]]),
        );

        store.selectExclusive('/kw1.jpg', group as never);

        const kept = store.selectionsMap().get(group.group_id);
        expect(kept?.size).toBe(3);
        expect([...(kept ?? [])].sort()).toEqual(['/kw0.jpg', '/kw1.jpg', '/kw2.jpg']);
      });

      it('refuses to reduce an hdr_panorama set to a single frame', () => {
        const group = buildKeepWholeGroup('hdr_panorama');
        store.groups.set([group] as never);
        store.selectionsMap.set(
          new Map([[group.group_id, new Set(group.photos.map(p => p.path))]]),
        );

        store.selectExclusive('/kw1.jpg', group as never);

        const kept = store.selectionsMap().get(group.group_id);
        expect(kept?.size).toBe(3);
        expect([...(kept ?? [])].sort()).toEqual(['/kw0.jpg', '/kw1.jpg', '/kw2.jpg']);
      });

      it('still collapses an ordinary burst to the single double-clicked frame', async () => {
        await store.loadGroups();
        const group = store.groups()[0]; // type: 'burst', no sequence_kind

        store.selectExclusive('/photo2.jpg', group);

        const kept = store.selectionsMap().get(group.group_id);
        expect(kept?.size).toBe(1);
        expect(kept?.has('/photo2.jpg')).toBe(true);
      });
    });

    describe('hasMore', () => {
      beforeEach(async () => {
        await store.loadGroups();
      });

      it('should return false on single page', () => {
        expect(store.hasMore()).toBe(false);
      });

      it('should return true when more pages exist', () => {
        store.totalPages.set(2);
        expect(store.hasMore()).toBe(true);
      });
    });
  });
  describe('applyExternalChanges', () => {
    const fresh = (path: string, extra: Record<string, unknown>) => ({ path, is_rejected: 0, is_favorite: 0, star_rating: 0, ...extra });

    beforeEach(async () => {
      await store.loadGroups();
      api.get.mockClear();
    });

    it('patches rating/favorite/reject in place, leaving selections and confirmations untouched', async () => {
      const selections = store.selectionsMap();
      const confirmed = store.confirmedGroups();
      api.post.mockReturnValue(of({ photos: [fresh('/a.jpg', { is_rejected: 1, star_rating: 2, is_favorite: 1 })], total: 1, missing: [] }));
      await store.applyExternalChanges(['/a.jpg']);
      const a = store.groups()[0].photos[0];
      expect(a.is_rejected).toBe(1);
      expect(a.star_rating).toBe(2);
      expect(a.is_favorite).toBe(1);
      expect(store.groups()[0].photos[1].path).toBe('/b.jpg');
      expect(store.selectionsMap()).toBe(selections);
      expect(store.confirmedGroups()).toBe(confirmed);
      expect(api.post).toHaveBeenCalledWith('/photos/by_paths', { paths: ['/a.jpg'] });
    });

    it('chunks requests at 500 paths and ignores paths that are not loaded', async () => {
      api.post.mockReturnValue(of({ photos: [], total: 0, missing: [] }));
      await store.applyExternalChanges(['/not-loaded.jpg']);
      expect(api.post).not.toHaveBeenCalled();
      const many = Array.from({ length: 1200 }, (_, i) => `/x${i}.jpg`);
      store.groups.set([makeGroup(9, 'burst', many, '/x0.jpg')]);
      await store.applyExternalChanges(many);
      expect(api.post.mock.calls.map(c => (c[1] as { paths: string[] }).paths.length)).toEqual([500, 500, 200]);
    });

    it('removes a missing path from its group and selection, and hides an emptied group', async () => {
      api.post.mockReturnValue(of({ photos: [], total: 0, missing: ['/c.jpg', '/d.jpg', '/b.jpg'] }));
      await store.applyExternalChanges(['/b.jpg', '/c.jpg', '/d.jpg']);
      expect(store.groups()[0].photos.map(p => p.path)).toEqual(['/a.jpg']);
      expect(store.selectionsMap().get(1)?.has('/b.jpg') ?? false).toBe(false);
      expect(store.groups()[1].photos).toHaveLength(0);
      expect(store.hiddenGroups().has(store.groupKey(store.groups()[1]))).toBe(true);
      expect(store.selectionsMap().get(2)?.size ?? 0).toBe(0);
    });

    it('a null batch with a user decision keeps state, emits a reload notice and does not reload', async () => {
      store.setPhotoKept(store.groups()[0], '/b.jpg', true);
      await store.applyExternalChanges(null);
      expect(api.get).not.toHaveBeenCalled();
      expect(notices).toHaveLength(1);
      expect(notices[0].action).toBeTruthy();
      notices[0].action!.run();
      await Promise.resolve();
      expect(api.get).toHaveBeenCalledWith('/culling-groups', expect.anything());
    });

    it('a null batch with the lightbox open is treated as a decision', async () => {
      await store.applyExternalChanges(null, { lightboxOpen: true });
      expect(api.get).not.toHaveBeenCalled();
      expect(notices[0].action).toBeTruthy();
    });

    it('a null batch with no user-touched group reloads the feed (the auto-selection does not count)', async () => {
      expect(store.selectionsMap().size).toBeGreaterThan(0);
      await store.applyExternalChanges(null);
      expect(api.get).toHaveBeenCalledWith('/culling-groups', expect.anything());
      expect(notices).toHaveLength(0);
    });

    it('counts selectExclusive and confirm as user-touched', async () => {
      store.selectExclusive('/a.jpg', store.groups()[0]);
      expect(store.hasUserDecisions()).toBe(true);
    });

    it('a failed refresh keeps the rows as they were', async () => {
      const before = store.groups();
      api.post.mockReturnValue(throwError(() => ({ status: 500 })));
      await store.applyExternalChanges(['/a.jpg']);
      expect(store.groups()).toBe(before);
    });
  });
});
