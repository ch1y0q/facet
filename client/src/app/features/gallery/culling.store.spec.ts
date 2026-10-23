import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { Subject, of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import {
  CULL_DEFAULT_STRICTNESS, CULL_PROFILE_KEY, CULL_REPLAN_DEBOUNCE_MS, CULL_STRICTNESS_KEY,
  CullingStore, CullingNotice, readStoredStrictness, type CullProfile,
} from './culling.store';
import type { CullingGroup } from './burst-culling.pipes';
import { HttpErrorResponse } from '@angular/common/http';
import { AssistantCullPlanService, type CullPlanPin } from '../../core/agent/assistant-cull-plan.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';

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
  let journalRecord: Mock;

  beforeEach(() => {
    journalRecord = vi.fn();
    localStorage.clear();
    api = {
      get: vi.fn((path: string) => of(path === '/culling-groups' ? GROUPS_RESPONSE : {})),
      post: vi.fn(() => of({})),
    };
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: api },
        { provide: I18nService, useValue: { t: vi.fn((key: string) => key) } },
        { provide: UserActivityJournal, useValue: { record: journalRecord } },
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
      expect([...store.selectionsMap().get('1_burst') ?? []]).toEqual(['/a.jpg']);
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
      expect(store.selectionsMap().has('1_burst')).toBe(true);
      expect(store.selectionsMap().has('3_burst')).toBe(true);
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
      store.selectionsMap.set(new Map([['1_burst', new Set<string>()]]));
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
      store.selectionsMap.set(new Map([['1_burst', new Set(['/a.jpg', '/b.jpg'])]]));
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

        const kept = store.selectionsMap().get('1_burst');
        expect(kept?.has('/photo2.jpg')).toBe(true);
      });

      it('should remove a photo from the selection when already selected', () => {
        const group = store.groups()[0];
        // photo1.jpg is auto-selected as best_path
        store.toggleSelection('/photo1.jpg', group);

        const kept = store.selectionsMap().get('1_burst');
        expect(kept?.has('/photo1.jpg')).toBe(false);
      });

      it('should allow multiple photos to be selected', () => {
        const group = store.groups()[0];
        store.toggleSelection('/photo2.jpg', group);
        store.toggleSelection('/photo3.jpg', group);

        const kept = store.selectionsMap().get('1_burst');
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
          new Map([[store.groupKey(group), new Set(group.photos.map(p => p.path))]]),
        );

        store.selectExclusive('/kw1.jpg', group as never);

        const kept = store.selectionsMap().get(store.groupKey(group));
        expect(kept?.size).toBe(3);
        expect([...(kept ?? [])].sort()).toEqual(['/kw0.jpg', '/kw1.jpg', '/kw2.jpg']);
      });

      it('refuses to reduce a panorama set to a single frame', () => {
        const group = buildKeepWholeGroup('panorama');
        store.groups.set([group] as never);
        store.selectionsMap.set(
          new Map([[store.groupKey(group), new Set(group.photos.map(p => p.path))]]),
        );

        store.selectExclusive('/kw1.jpg', group as never);

        const kept = store.selectionsMap().get(store.groupKey(group));
        expect(kept?.size).toBe(3);
        expect([...(kept ?? [])].sort()).toEqual(['/kw0.jpg', '/kw1.jpg', '/kw2.jpg']);
      });

      it('refuses to reduce an hdr_panorama set to a single frame', () => {
        const group = buildKeepWholeGroup('hdr_panorama');
        store.groups.set([group] as never);
        store.selectionsMap.set(
          new Map([[store.groupKey(group), new Set(group.photos.map(p => p.path))]]),
        );

        store.selectExclusive('/kw1.jpg', group as never);

        const kept = store.selectionsMap().get(store.groupKey(group));
        expect(kept?.size).toBe(3);
        expect([...(kept ?? [])].sort()).toEqual(['/kw0.jpg', '/kw1.jpg', '/kw2.jpg']);
      });

      it('still collapses an ordinary burst to the single double-clicked frame', async () => {
        await store.loadGroups();
        const group = store.groups()[0]; // type: 'burst', no sequence_kind

        store.selectExclusive('/photo2.jpg', group);

        const kept = store.selectionsMap().get(store.groupKey(group));
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
      expect(store.selectionsMap().get('1_burst')?.has('/b.jpg') ?? false).toBe(false);
      expect(store.groups()[1].photos).toHaveLength(0);
      expect(store.hiddenGroups().has(store.groupKey(store.groups()[1]))).toBe(true);
      expect(store.selectionsMap().get('2_similar')?.size ?? 0).toBe(0);
    });

    it('a null batch with a user decision keeps state, raises pendingReload and does not reload', async () => {
      store.setPhotoKept(store.groups()[0], '/b.jpg', true);
      expect(store.pendingReload()).toBe(false);
      await store.applyExternalChanges(null);
      expect(api.get).not.toHaveBeenCalled();
      expect(store.pendingReload()).toBe(true);
      expect(notices).toHaveLength(0);
      store.resetForReload();
      await Promise.resolve();
      expect(store.pendingReload()).toBe(false);
      expect(api.get).toHaveBeenCalledWith('/culling-groups', expect.anything());
    });

    it('a path batch after a null batch leaves pendingReload raised', async () => {
      store.setPhotoKept(store.groups()[0], '/b.jpg', true);
      await store.applyExternalChanges(null);
      api.post.mockReturnValue(of({ photos: [fresh('/a.jpg', { star_rating: 3 })], total: 1, missing: [] }));
      await store.applyExternalChanges(['/a.jpg']);
      expect(store.pendingReload()).toBe(true);
    });

    it('a null batch with the lightbox open raises pendingReload', async () => {
      await store.applyExternalChanges(null, { lightboxOpen: true });
      expect(api.get).not.toHaveBeenCalled();
      expect(store.pendingReload()).toBe(true);
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

    it('replaces the selections map instead of mutating it when a selected photo goes missing', async () => {
      const before = store.selectionsMap();
      expect(before.get('1_burst')?.has('/a.jpg')).toBe(true);
      api.post.mockReturnValue(of({ photos: [], total: 0, missing: ['/a.jpg'] }));
      await store.applyExternalChanges(['/a.jpg']);
      expect(store.selectionsMap()).not.toBe(before);
      expect(before.get('1_burst')?.has('/a.jpg')).toBe(true);
      expect(store.selectionsMap().get('1_burst')?.has('/a.jpg')).toBe(false);
    });

    it('does not merge rows fetched before a reload into the new feed', async () => {
      const slow = new Subject<{ photos: unknown[] }>();
      api.post.mockReturnValue(slow);
      const pending = store.applyExternalChanges(['/a.jpg']);
      await new Promise(resolve => setTimeout(resolve));
      expect(api.post).toHaveBeenCalledTimes(1);
      store.resetForReload();
      await Promise.resolve();
      await Promise.resolve();
      slow.next({ photos: [fresh('/a.jpg', { is_rejected: 1, star_rating: 5 })] });
      slow.complete();
      await pending;
      const a = store.groups()[0].photos[0];
      expect(a.is_rejected ?? 0).toBe(0);
      expect(a.star_rating ?? 0).toBe(0);
    });

    it('lands overlapping batches in arrival order (a slow older one never overwrites a newer one)', async () => {
      const older = new Subject<{ photos: unknown[] }>();
      api.post.mockReturnValueOnce(older).mockReturnValueOnce(of({ photos: [fresh('/a.jpg', { is_rejected: 0, star_rating: 4 })] }));
      const first = store.applyExternalChanges(['/a.jpg']);
      const second = store.applyExternalChanges(['/a.jpg']);
      await Promise.resolve();
      older.next({ photos: [fresh('/a.jpg', { is_rejected: 1, star_rating: 1 })] });
      older.complete();
      await Promise.all([first, second]);
      const a = store.groups()[0].photos[0];
      expect(a.is_rejected).toBe(0);
      expect(a.star_rating).toBe(4);
    });

    it('a failed batch does not block the next one', async () => {
      api.post.mockReturnValueOnce(throwError(() => ({ status: 500 }))).mockReturnValueOnce(of({ photos: [fresh('/a.jpg', { star_rating: 2 })] }));
      await store.applyExternalChanges(['/a.jpg']);
      await store.applyExternalChanges(['/a.jpg']);
      expect(store.groups()[0].photos[0].star_rating).toBe(2);
    });

    it('a failed refresh keeps the rows as they were', async () => {
      const before = store.groups();
      api.post.mockReturnValue(throwError(() => ({ status: 500 })));
      await store.applyExternalChanges(['/a.jpg']);
      expect(store.groups()).toBe(before);
    });
  });

  describe('stored strictness', () => {
    it('reads a stored integer in 0..100', () => {
      localStorage.setItem(CULL_STRICTNESS_KEY, '35');
      expect(readStoredStrictness()).toBe(35);
      localStorage.setItem(CULL_STRICTNESS_KEY, '0');
      expect(readStoredStrictness()).toBe(0);
    });

    it.each(['abc', '-5', '150', '3.5', '', ' 40'])('falls back to the default for %j', raw => {
      localStorage.setItem(CULL_STRICTNESS_KEY, raw);
      expect(readStoredStrictness()).toBe(CULL_DEFAULT_STRICTNESS);
    });

    it('falls back to the default with nothing stored or a localStorage that throws', () => {
      expect(readStoredStrictness()).toBe(100);
      const spy = vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
      try {
        expect(readStoredStrictness()).toBe(100);
      } finally {
        spy.mockRestore();
      }
    });

    it('a fresh store restores the stored value', () => {
      localStorage.setItem(CULL_STRICTNESS_KEY, '45');
      const fresh = TestBed.runInInjectionContext(() => new CullingStore());
      expect(fresh.strictness()).toBe(45);
    });

    it('a stored preset loaded in manual mode keeps the stored slider value over the preset\'s own', async () => {
      localStorage.setItem(CULL_PROFILE_KEY, 'wedding');
      localStorage.setItem(CULL_STRICTNESS_KEY, '60');
      const wedding: CullProfile = {
        id: 'wedding', label_key: 'x', strictness: 35, eyes_closed_max: null, poor_expression_min: null,
        keep_min_per_group: 1, similarity_threshold: null,
      };
      api.get.mockImplementation((path: string) =>
        of(path === '/culling/profiles' ? { profiles: [wedding], default: 'general' } : GROUPS_RESPONSE));
      const fresh = TestBed.runInInjectionContext(() => new CullingStore());
      await fresh.loadCullProfiles();
      expect(fresh.strictness()).toBe(60);
      expect(localStorage.getItem(CULL_STRICTNESS_KEY)).toBe('60');
      expect(fresh.selectedProfile()).toBe('wedding');
    });

    it('a stored preset with no stored slider value loads the preset\'s own strictness', async () => {
      localStorage.setItem(CULL_PROFILE_KEY, 'wedding');
      const wedding: CullProfile = {
        id: 'wedding', label_key: 'x', strictness: 35, eyes_closed_max: null, poor_expression_min: null,
        keep_min_per_group: 1, similarity_threshold: null,
      };
      api.get.mockImplementation((path: string) =>
        of(path === '/culling/profiles' ? { profiles: [wedding], default: 'general' } : GROUPS_RESPONSE));
      const fresh = TestBed.runInInjectionContext(() => new CullingStore());
      await fresh.loadCullProfiles();
      expect(fresh.strictness()).toBe(35);
    });

    it('setStrictness sets the signal and stores the value', () => {
      store.setStrictness(65);
      expect(store.strictness()).toBe(65);
      expect(localStorage.getItem(CULL_STRICTNESS_KEY)).toBe('65');
    });

    it('applying a preset stores its strictness', () => {
      store.applyProfile({
        id: 'sports', label_key: 'x', strictness: 70, eyes_closed_max: null, poor_expression_min: null,
        keep_min_per_group: 1, similarity_threshold: null,
      });
      expect(localStorage.getItem(CULL_STRICTNESS_KEY)).toBe('70');
    });
  });

  describe('plan mode', () => {
    const planGroup = (id: number, type: string, paths: string[], keep: string[], number: number) => ({
      ...makeGroup(id, type, paths, paths[0]),
      plan: { number, keep_paths: keep, group_reason: { key: 'burst', params: {} } },
    });
    const planResponse = (groups: unknown[], extra: Record<string, unknown> = {}) => ({
      groups, total_groups: groups.length, plan_digest: 'dg', truncated: false, oversize_groups: 0, ...extra,
    });
    const PLAN = planResponse([
      planGroup(5, 'burst', ['/a.jpg', '/b.jpg'], ['/b.jpg'], 1),
      planGroup(5, 'similar', ['/c.jpg', '/d.jpg'], ['/c.jpg', '/d.jpg'], 2),
    ]);
    const pin = { digest: 'dg', request: { group_by: 'all' as const, strictness: 80 } };
    let plan: AssistantCullPlanService;

    beforeEach(() => {
      plan = TestBed.inject(AssistantCullPlanService);
      plan.setPin(pin);
      api.post.mockImplementation((path: string) => of(path === '/culling/plan' ? PLAN : {}));
    });

    it('posts the request with expected_digest and seeds selections from plan.keep_paths, not autoSelectBest', async () => {
      expect(await store.enterPlan(pin)).toBe('landed');
      expect(api.post).toHaveBeenCalledWith('/culling/plan', { group_by: 'all', strictness: 80, expected_digest: 'dg' });
      expect(store.planActive()).toBe(true);
      expect([...store.selectionsMap().get('5_burst') ?? []]).toEqual(['/b.jpg']);
      expect([...store.selectionsMap().get('5_similar') ?? []]).toEqual(['/c.jpg', '/d.jpg']);
    });

    it('keeps burst 5 and similar 5 apart under their groupKey', async () => {
      await store.enterPlan(pin);
      expect([...store.selectionsMap().keys()]).toEqual(['5_burst', '5_similar']);
      store.toggleSelection('/a.jpg', store.groups()[0]);
      expect(store.selectionsMap().get('5_burst')?.has('/a.jpg')).toBe(true);
      expect(store.selectionsMap().get('5_similar')?.has('/a.jpg')).toBe(false);
    });

    it('sets scope and group_by from the request and never calls the feed', async () => {
      await store.enterPlan({ digest: 'dg', request: { group_by: 'burst', album_id: 9, date_from: '2025-04-16', date_to: '2025-04-16' } });
      expect(store.groupBy()).toBe('burst');
      expect(store.scopeAlbum()).toBe('9');
      expect(store.scopeFrom()).toBe('2025-04-16');
      expect(api.get).not.toHaveBeenCalledWith('/culling-groups', expect.anything());
    });

    it('412 exits plan mode, drops the pin, notifies out_of_date and reloads the manual feed', async () => {
      api.post.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 412 })));
      expect(await store.enterPlan(pin)).toBe('out_of_date');
      expect(store.planActive()).toBe(false);
      expect(plan.pin()).toBeNull();
      expect(notices).toEqual([{ key: 'culling.plan.out_of_date', duration: 4000 }]);
      expect(api.get).toHaveBeenCalledWith('/culling-groups', expect.anything());
    });

    it('records why the load failed so the tool handler can tell a 412 from the rest', async () => {
      api.post.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 412 })));
      await store.enterPlan(pin);
      expect(plan.loadFailure('dg')).toBe('out_of_date');
      plan.setPin({ digest: 'dg2', request: pin.request });
      api.post.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 500 })));
      await store.enterPlan({ ...pin, digest: 'dg2' });
      expect(plan.loadFailure('dg2')).toBe('failed');
    });

    it('re-entering the same digest after a confirm rebuilds the plan from the held response without posting', async () => {
      vi.useFakeTimers();
      await store.enterPlan(pin);
      store.toggleSelection('/a.jpg', store.groups()[1]);
      store.confirmGroup(store.groups()[0]);
      await vi.advanceTimersByTimeAsync(7000);
      expect(plan.snapshot()?.confirmed).toEqual([1]);
      api.post.mockClear();
      expect(await store.enterPlan(pin)).toBe('landed');
      expect(api.post).not.toHaveBeenCalled();
      expect(store.planActive()).toBe(true);
      expect(store.confirmedGroups()).toEqual(new Set(['5_burst']));
      expect(store.hiddenGroups()).toEqual(new Set(['5_burst']));
      expect(store.totalGroups()).toBe(2);
      expect(plan.snapshot()?.confirmed).toEqual([1]);
      expect(plan.snapshot()?.groups_total).toBe(2);
    });

    it('re-entry keeps an unconfirmed flip and hides a skipped group', async () => {
      vi.useFakeTimers();
      await store.enterPlan(pin);
      store.toggleSelection('/a.jpg', store.groups()[0]);
      store.skipGroup(store.groups()[1]);
      await vi.advanceTimersByTimeAsync(7000);
      expect(await store.enterPlan(pin)).toBe('landed');
      expect([...store.selectionsMap().get('5_burst') ?? []].sort()).toEqual(['/a.jpg', '/b.jpg']);
      expect(store.hiddenGroups()).toEqual(new Set(['5_similar']));
      expect(plan.snapshot()?.pending).toEqual([1]);
    });

    it('any other error exits plan mode with the generic load error', async () => {
      api.post.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 500 })));
      expect(await store.enterPlan(pin)).toBe('failed');
      expect(store.planActive()).toBe(false);
      expect(notices).toEqual([{ key: 'culling.error_loading', duration: 2000 }]);
    });

    it('a grouping or scope change (resetForReload) leaves plan mode and drops the pin', async () => {
      await store.enterPlan(pin);
      store.resetForReload();
      expect(store.planActive()).toBe(false);
      expect(plan.pin()).toBeNull();
      expect(plan.snapshot()).toBeNull();
      expect(api.get).toHaveBeenCalledWith('/culling-groups', expect.anything());
    });

    it('loadGroups (scope exit) also leaves plan mode', async () => {
      await store.enterPlan(pin);
      await store.loadGroups();
      expect(store.planActive()).toBe(false);
      expect(plan.pin()).toBeNull();
    });

    it('reveals 20 groups at a time through loadMore', async () => {
      const many = Array.from({ length: 45 }, (_, i) => planGroup(i + 1, 'burst', [`/p${i}a.jpg`, `/p${i}b.jpg`], [`/p${i}a.jpg`], i + 1));
      api.post.mockImplementation(() => of(planResponse(many)));
      await store.enterPlan(pin);
      expect(store.groups()).toHaveLength(20);
      expect(store.hasMore()).toBe(true);
      await store.loadMore();
      expect(store.groups()).toHaveLength(40);
      await store.loadMore();
      expect(store.groups()).toHaveLength(45);
      expect(store.hasMore()).toBe(false);
      expect(store.totalGroups()).toBe(45);
    });

    it('does not re-select from strictness', async () => {
      await store.enterPlan(pin);
      store.setStrictness(0);
      store.reselectFromStrictness();
      expect([...store.selectionsMap().get('5_burst') ?? []]).toEqual(['/b.jpg']);
    });

    it('confirm posts the plan group unchanged and journals only once the commit lands', async () => {
      vi.useFakeTimers();
      await store.enterPlan(pin);
      const group = store.groups()[0];
      api.post.mockClear();
      expect(store.confirmGroup(group)).toBe(true);
      expect(api.post).not.toHaveBeenCalled();
      expect(journalRecord).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(7000);
      expect(api.post).toHaveBeenCalledWith('/culling-groups/confirm', {
        group_id: 5, type: 'burst', paths: ['/a.jpg', '/b.jpg'], keep_paths: ['/b.jpg'],
      });
      expect(journalRecord).toHaveBeenCalledWith('cull_confirm', ['/b.jpg'], expect.objectContaining({ type: 'burst', group_id: 5 }));
      expect(plan.snapshot()?.confirmed).toEqual([1]);
    });

    it('an undone confirm records no cull_confirm', async () => {
      vi.useFakeTimers();
      await store.enterPlan(pin);
      const group = store.groups()[0];
      api.post.mockClear();
      store.confirmGroup(group);
      store.cancelPass(group);
      await vi.advanceTimersByTimeAsync(8000);
      expect(api.post).not.toHaveBeenCalled();
      expect(journalRecord).not.toHaveBeenCalled();
      expect(plan.snapshot()?.confirmed).toEqual([]);
    });

    it('confirm then Exit inside the cooldown still commits but hides nothing and journals nothing', async () => {
      vi.useFakeTimers();
      await store.enterPlan(pin);
      const group = store.groups()[0];
      api.post.mockClear();
      store.confirmGroup(group);
      store.resetForReload();
      await vi.advanceTimersByTimeAsync(0);
      expect(api.post).toHaveBeenCalledWith('/culling-groups/confirm', expect.objectContaining({ group_id: 5, type: 'burst' }));
      await vi.advanceTimersByTimeAsync(8000);
      expect(store.hiddenGroups().size).toBe(0);
      expect(journalRecord).not.toHaveBeenCalled();
    });

    it('a skip journals cull_skip only when the cooldown elapses', async () => {
      vi.useFakeTimers();
      await store.enterPlan(pin);
      const group = store.groups()[1];
      store.skipGroup(group);
      expect(journalRecord).not.toHaveBeenCalled();
      await vi.advanceTimersByTimeAsync(7000);
      expect(journalRecord).toHaveBeenCalledWith('cull_skip', ['/c.jpg', '/d.jpg'], expect.objectContaining({ group_id: 5, type: 'similar' }));
    });

    it('does not journal in manual mode', async () => {
      vi.useFakeTimers();
      await store.loadGroups();
      store.confirmGroup(store.groups()[0]);
      await vi.advanceTimersByTimeAsync(7000);
      expect(journalRecord).not.toHaveBeenCalled();
    });

    it('reports a flipped keep to the plan service as pending and changed', async () => {
      await store.enterPlan(pin);
      store.toggleSelection('/a.jpg', store.groups()[0]);
      expect(plan.snapshot()).toEqual(expect.objectContaining({
        pending: [1],
        changed: [{ type: 'burst', group_id: 5, number: 1, keep_paths: ['/a.jpg', '/b.jpg'], reject_paths: [] }],
      }));
    });

    it('treats a null assistant batch as pending reload rather than silently leaving the plan', async () => {
      await store.enterPlan(pin);
      await store.applyExternalChanges(null);
      expect(store.planActive()).toBe(true);
      expect(store.pendingReload()).toBe(true);
    });
    describe('adopting the plan knobs', () => {
      const profile = (id: string, strictness: number | null, threshold: number | null): CullProfile => ({
        id, label_key: `culling.profiles.${id}`, strictness, eyes_closed_max: null, poor_expression_min: null,
        keep_min_per_group: 1, similarity_threshold: threshold,
      });
      const PROFILES = [profile('wedding', 35, 90), profile('sports', 70, 80)];

      it('an explicit strictness moves and stores the slider and clears the stored preset', async () => {
        localStorage.setItem(CULL_PROFILE_KEY, 'sports');
        store.selectedProfile.set('sports');
        await store.enterPlan({ digest: 'dg', request: { group_by: 'all', strictness: 35 } });
        expect(store.strictness()).toBe(35);
        expect(localStorage.getItem(CULL_STRICTNESS_KEY)).toBe('35');
        expect(store.selectedProfile()).toBe('');
        expect(localStorage.getItem(CULL_PROFILE_KEY)).toBeNull();
      });

      it('a strictness beside a preset stores both: slider on the strictness, the preset kept for its other knobs', async () => {
        await store.enterPlan({ digest: 'dg', request: { group_by: 'all', strictness: 60, profile: 'wedding' } });
        expect(store.strictness()).toBe(60);
        expect(localStorage.getItem(CULL_STRICTNESS_KEY)).toBe('60');
        expect(store.selectedProfile()).toBe('wedding');
        expect(localStorage.getItem(CULL_PROFILE_KEY)).toBe('wedding');
      });

      it('a preset list loading later does not move the slider off the strictness the plan carries', async () => {
        api.get.mockImplementation((path: string) => of(path === '/culling/profiles' ? { profiles: PROFILES, default: 'general' } : GROUPS_RESPONSE));
        const both: CullPlanPin = { digest: 'dg', request: { group_by: 'all', strictness: 60, profile: 'wedding' } };
        plan.setPin(both);
        await store.enterPlan(both);
        await store.loadCullProfiles();
        expect(store.strictness()).toBe(60);
        expect(store.selectedProfile()).toBe('wedding');
      });

      it('a preset alone moves the slider to its strictness and becomes the stored preset', async () => {
        store.cullProfiles.set(PROFILES);
        await store.enterPlan({ digest: 'dg', request: { group_by: 'all', profile: 'sports' } });
        expect(store.strictness()).toBe(70);
        expect(localStorage.getItem(CULL_STRICTNESS_KEY)).toBe('70');
        expect(store.selectedProfile()).toBe('sports');
        expect(localStorage.getItem(CULL_PROFILE_KEY)).toBe('sports');
        expect(store.profileChosen()).toBe(true);
      });

      it('a preset whose list loads after the plan moves the slider without reloading the feed', async () => {
        api.get.mockImplementation((path: string) => of(path === '/culling/profiles' ? { profiles: PROFILES, default: 'general' } : GROUPS_RESPONSE));
        await store.enterPlan({ digest: 'dg', request: { group_by: 'all', profile: 'wedding' } });
        expect(store.strictness()).toBe(CULL_DEFAULT_STRICTNESS);
        await store.loadCullProfiles();
        expect(store.planActive()).toBe(true);
        expect(api.get).not.toHaveBeenCalledWith('/culling-groups', expect.anything());
        expect(store.similarityThreshold()).toBe(85);
        expect(store.strictness()).toBe(35);
        expect(store.selectedProfile()).toBe('wedding');
      });

      it('neither strictness nor preset leaves the slider alone', async () => {
        store.setStrictness(45);
        await store.enterPlan({ digest: 'dg', request: { group_by: 'all' } });
        expect(store.strictness()).toBe(45);
      });

      it('re-entering a held plan adopts too', async () => {
        await store.enterPlan({ digest: 'dg', request: { group_by: 'all', strictness: 35 } });
        store.setStrictness(90);
        api.post.mockClear();
        expect(await store.enterPlan({ digest: 'dg', request: { group_by: 'all', strictness: 35 } })).toBe('landed');
        expect(api.post).not.toHaveBeenCalled();
        expect(store.strictness()).toBe(35);
      });

      it('leaving the plan keeps the stored value', async () => {
        await store.enterPlan({ digest: 'dg', request: { group_by: 'all', strictness: 35 } });
        store.resetForReload();
        expect(store.planActive()).toBe(false);
        expect(store.strictness()).toBe(35);
        expect(localStorage.getItem(CULL_STRICTNESS_KEY)).toBe('35');
      });
    });

    describe('re-planning from the slider', () => {
      const NEW_PLAN = planResponse([
        planGroup(7, 'burst', ['/a.jpg', '/b.jpg'], ['/a.jpg'], 1),
        planGroup(3, 'similar', ['/c.jpg', '/d.jpg'], ['/c.jpg'], 2),
      ], { plan_digest: 'dg2' });
      const planCalls = () => api.post.mock.calls.filter(c => c[0] === '/culling/plan');
      /** What the component's onStrictnessChange does in plan mode: the stored preset stays. */
      const move = (value: number) => {
        store.setStrictness(value);
        store.scheduleReplan();
      };
      const settle = async () => {
        for (let i = 0; i < 5; i++) await vi.advanceTimersByTimeAsync(0);
      };
      const routePlan = (...answers: unknown[]) => {
        const queue = [...answers];
        api.post.mockImplementation((path: string) => {
          if (path !== '/culling/plan') return of({});
          const next = queue.shift();
          return next instanceof Subject ? next : of(next);
        });
      };

      beforeEach(async () => {
        vi.useFakeTimers();
        await store.enterPlan(pin);
        api.post.mockClear();
      });

      it('debounces three moves into one POST at the final value, without digest, keeping the preset and the assistant overrides', async () => {
        const overridden: CullPlanPin = { digest: 'dg', request: { group_by: 'all', strictness: 80, profile: 'wedding', keep_paths: ['/a.jpg'] } };
        plan.setPin(overridden);
        routePlan(NEW_PLAN);
        move(50);
        await vi.advanceTimersByTimeAsync(100);
        move(55);
        await vi.advanceTimersByTimeAsync(100);
        move(60);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS - 1);
        expect(planCalls()).toHaveLength(0);
        await vi.advanceTimersByTimeAsync(1);
        await settle();
        expect(planCalls()).toHaveLength(1);
        const body = planCalls()[0][1] as Record<string, unknown>;
        expect(body).toEqual({ group_by: 'all', strictness: 60, profile: 'wedding', keep_paths: ['/a.jpg'] });
        expect(body).not.toHaveProperty('expected_digest');
        // The preset still supplies its keeper floor server-side; the explicit strictness wins over its own.
        expect(body).toHaveProperty('profile', 'wedding');
        expect(store.planDigest()).toBe('dg2');
        expect(plan.pin()).toEqual({ digest: 'dg2', request: body });
        expect(store.loading()).toBe(false);
      });

      it('drops an answer whose re-plan a newer slider move superseded before it fired', async () => {
        const slow = new Subject<unknown>();
        routePlan(slow, { ...NEW_PLAN, plan_digest: 'dg3' });
        move(50);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        move(60);
        slow.next(NEW_PLAN);
        slow.complete();
        await settle();
        expect(store.planDigest()).toBe('dg');
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        expect(store.planDigest()).toBe('dg3');
        expect((planCalls()[1][1] as { strictness: number }).strictness).toBe(60);
      });

      it('ignores a slow earlier answer that lands after a later one', async () => {
        const slow = new Subject<unknown>();
        routePlan(slow, { ...NEW_PLAN, plan_digest: 'dg3' });
        move(50);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        move(60);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        expect(store.planDigest()).toBe('dg3');
        slow.next(NEW_PLAN);
        slow.complete();
        await settle();
        expect(store.planDigest()).toBe('dg3');
        expect(plan.pin()?.digest).toBe('dg3');
      });

      it('a late failure of a superseded re-plan does not restore the slider', async () => {
        const slow = new Subject<unknown>();
        routePlan(slow, { ...NEW_PLAN, plan_digest: 'dg3' });
        move(50);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        move(60);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        slow.error(new HttpErrorResponse({ status: 500 }));
        await settle();
        expect(store.strictness()).toBe(60);
        expect(localStorage.getItem(CULL_STRICTNESS_KEY)).toBe('60');
        expect(notices).toEqual([]);
        expect(store.planDigest()).toBe('dg3');
      });

      it('carries an open flip over to the group with the same photos, against the new keepers', async () => {
        store.toggleSelection('/a.jpg', store.groups()[0]);
        routePlan(NEW_PLAN);
        move(50);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        expect([...store.selectionsMap().get('7_burst') ?? []].sort()).toEqual(['/a.jpg', '/b.jpg']);
        expect([...store.selectionsMap().get('3_similar') ?? []]).toEqual(['/c.jpg']);
        expect(plan.snapshot()).toEqual(expect.objectContaining({
          plan_digest: 'dg2',
          pending: [1],
          changed: [{ type: 'burst', group_id: 7, number: 1, keep_paths: ['/a.jpg', '/b.jpg'], reject_paths: [] }],
        }));
        expect(notices).toEqual([]);
      });

      it('drops a flip whose group is gone and says how many', async () => {
        store.toggleSelection('/a.jpg', store.groups()[0]);
        routePlan(planResponse([planGroup(3, 'similar', ['/c.jpg', '/d.jpg'], ['/c.jpg'], 1)], { plan_digest: 'dg2' }));
        move(50);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        expect(plan.snapshot()?.changed).toEqual([]);
        expect(notices).toEqual([{ key: 'culling.plan.replan_flips_dropped', params: { count: 1 }, duration: 4000 }]);
      });

      it('resets the page decision sets, so a new group reusing a confirmed key renders unconfirmed', async () => {
        store.confirmGroup(store.groups()[0]);
        await vi.advanceTimersByTimeAsync(7000);
        expect(store.confirmedGroups().has('5_burst')).toBe(true);
        expect(store.hiddenGroups().has('5_burst')).toBe(true);
        // The server leaves the confirmed photos out; similar ids are positional, so 5_burst comes back for other photos.
        routePlan(planResponse([planGroup(5, 'burst', ['/e.jpg', '/f.jpg'], ['/e.jpg'], 1)], { plan_digest: 'dg2' }));
        move(50);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        expect(store.groups().flatMap(g => g.photos.map(p => p.path))).toEqual(['/e.jpg', '/f.jpg']);
        expect(store.confirmedGroups().size).toBe(0);
        expect(store.touchedGroups().size).toBe(0);
        expect(store.hiddenGroups().size).toBe(0);
        expect(plan.snapshot()?.confirmed).toEqual([]);
      });

      it.each([400, 500])('a %i keeps the old plan and puts the slider and the preset back', async status => {
        store.cullProfiles.set([{
          id: 'sports', label_key: 'x', strictness: 70, eyes_closed_max: null, poor_expression_min: null,
          keep_min_per_group: 1, similarity_threshold: 80,
        }]);
        const sportsPin: CullPlanPin = { digest: 'dg', request: { group_by: 'all', profile: 'sports' } };
        plan.setPin(sportsPin);
        await store.enterPlan(sportsPin);
        expect(store.strictness()).toBe(70);
        const before = store.groups();
        api.post.mockImplementation((path: string) => path === '/culling/plan'
          ? throwError(() => new HttpErrorResponse({ status })) : of({}));
        move(30);
        expect(localStorage.getItem(CULL_PROFILE_KEY)).toBe('sports');
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        expect(store.planActive()).toBe(true);
        expect(store.planDigest()).toBe('dg');
        expect(store.groups()).toBe(before);
        expect(store.strictness()).toBe(70);
        expect(localStorage.getItem(CULL_STRICTNESS_KEY)).toBe('70');
        expect(store.selectedProfile()).toBe('sports');
        expect(localStorage.getItem(CULL_PROFILE_KEY)).toBe('sports');
        expect(notices).toEqual([{ key: 'culling.error_loading', duration: 2000 }]);
        expect(plan.loadFailure('dg')).toBeNull();
      });

      it('commits a confirm still counting down before it asks for the new plan', async () => {
        routePlan(NEW_PLAN);
        store.confirmGroup(store.groups()[1]);
        move(50);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        expect(api.post.mock.calls.map(c => c[0])).toEqual(['/culling-groups/confirm', '/culling/plan']);
        expect(api.post.mock.calls[0][1]).toEqual(expect.objectContaining({ group_id: 5, type: 'similar' }));
      });

      it('waits for a confirm commit already in flight before it asks for the new plan', async () => {
        const commit = new Subject<unknown>();
        api.post.mockImplementation((path: string) => (path === '/culling-groups/confirm' ? commit : of(NEW_PLAN)));
        store.confirmGroup(store.groups()[1]);
        await vi.advanceTimersByTimeAsync(7000);
        move(50);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        expect(planCalls()).toHaveLength(0);
        commit.next({});
        commit.complete();
        await settle();
        expect(api.post.mock.calls.map(c => c[0])).toEqual(['/culling-groups/confirm', '/culling/plan']);
      });

      it('leaving the plan inside the debounce window cancels the re-plan', async () => {
        routePlan(NEW_PLAN);
        move(50);
        store.resetForReload();
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS * 2);
        expect(planCalls()).toHaveLength(0);
      });

      it('a new assistant pin inside the debounce window cancels the re-plan', async () => {
        routePlan(NEW_PLAN, { ...NEW_PLAN, plan_digest: 'dgX' });
        move(50);
        const next: CullPlanPin = { digest: 'dgX', request: { group_by: 'all', strictness: 20 } };
        plan.setPin(next);
        await store.enterPlan(next);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS * 2);
        expect(planCalls()).toHaveLength(1);
        expect(planCalls()[0][1]).toEqual({ group_by: 'all', strictness: 20, expected_digest: 'dgX' });
        expect(store.strictness()).toBe(20);
      });

      it('keeps the paged depth and never cuts the new plan', async () => {
        const many = (prefix: string, n: number) =>
          Array.from({ length: n }, (_, i) => planGroup(i + 1, 'burst', [`/${prefix}${i}a.jpg`, `/${prefix}${i}b.jpg`], [`/${prefix}${i}a.jpg`], i + 1));
        api.post.mockImplementation(() => of(planResponse(many('p', 65))));
        const deep: CullPlanPin = { digest: 'dgDeep', request: { group_by: 'all', strictness: 80 } };
        plan.setPin(deep);
        await store.enterPlan(deep);
        await store.loadMore();
        await store.loadMore();
        expect(store.groups()).toHaveLength(60);
        routePlan(planResponse(many('q', 65), { plan_digest: 'dg2' }));
        move(50);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        expect(store.planDigest()).toBe('dg2');
        expect(store.groups()).toHaveLength(60);
        expect(store.currentPage()).toBe(3);
        expect(store.groups()[0].photos[0].path).toBe('/q0a.jpg');
        await store.loadMore();
        expect(store.groups()).toHaveLength(65);
        expect(store.totalGroups()).toBe(65);
        expect(plan.snapshot()?.groups_total).toBe(65);
      });

      it('brings a confirmed scene group back confirmed and hidden with the user keepers when it returns smaller', async () => {
        const scenePin: CullPlanPin = { digest: 'dgS', request: { group_by: 'scene', strictness: 80 } };
        api.post.mockImplementation((path: string) => of(path === '/culling/plan' ? planResponse([
          planGroup(3, 'scene', ['/a.jpg', '/b.jpg', '/c.jpg'], ['/a.jpg'], 1),
          planGroup(4, 'scene', ['/x.jpg', '/y.jpg'], ['/x.jpg'], 2),
        ], { plan_digest: 'dgS' }) : {}));
        plan.setPin(scenePin);
        await store.enterPlan(scenePin);
        store.toggleSelection('/b.jpg', store.groups()[0]);
        store.confirmGroup(store.groups()[0]);
        await vi.advanceTimersByTimeAsync(7000);
        expect(plan.snapshot()?.confirmed).toEqual([1]);
        // Scene confirms are not marked reviewed: the group comes back, renumbered, without its rejected /c.jpg.
        routePlan(planResponse([
          planGroup(9, 'scene', ['/x.jpg', '/y.jpg'], ['/x.jpg'], 1),
          planGroup(8, 'scene', ['/a.jpg', '/b.jpg'], ['/a.jpg'], 2),
        ], { plan_digest: 'dgS2' }));
        api.post.mockClear();
        move(50);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        await vi.advanceTimersByTimeAsync(8000);
        expect(store.planDigest()).toBe('dgS2');
        expect(api.post.mock.calls.map(c => c[0])).toEqual(['/culling/plan']);
        expect([...store.selectionsMap().get('8_scene') ?? []].sort()).toEqual(['/a.jpg', '/b.jpg']);
        expect(store.confirmedGroups()).toEqual(new Set(['8_scene']));
        expect(store.hiddenGroups()).toEqual(new Set(['8_scene']));
        const snap = plan.snapshot();
        expect(snap?.confirmed).toEqual([2]);
        expect(snap?.pending).toEqual([]);
        expect(snap?.changed).toEqual([{ type: 'scene', group_id: 8, number: 2, keep_paths: ['/a.jpg', '/b.jpg'], reject_paths: [] }]);
        // Carried, not re-confirmed: nothing more is journalled.
        expect(journalRecord.mock.calls.filter(c => c[0] === 'cull_confirm')).toHaveLength(1);
      });

      it('a group that only overlaps a confirmed one is not carried as confirmed', async () => {
        store.confirmGroup(store.groups()[0]);
        await vi.advanceTimersByTimeAsync(7000);
        routePlan(planResponse([planGroup(2, 'similar', ['/a.jpg', '/e.jpg'], ['/a.jpg'], 1)], { plan_digest: 'dg2' }));
        move(50);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        expect(store.confirmedGroups().size).toBe(0);
        expect(plan.snapshot()?.confirmed).toEqual([]);
      });

      it('pauses confirm, skip and confirm-all from the flush until the answer lands', async () => {
        const slow = new Subject<unknown>();
        routePlan(slow);
        move(50);
        expect(store.replanning()).toBe(false);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        expect(store.replanning()).toBe(true);
        const [first, second] = store.groups();
        expect(store.confirmGroup(first)).toBe(false);
        store.skipGroup(second);
        await store.confirmAllRemaining(store.groups());
        expect(store.passingGroups().size).toBe(0);
        expect(store.confirmedGroups().size).toBe(0);
        expect(store.touchedGroups().size).toBe(0);
        await vi.advanceTimersByTimeAsync(8000);
        expect(api.post.mock.calls.map(c => c[0])).toEqual(['/culling/plan']);
        slow.next(NEW_PLAN);
        slow.complete();
        await settle();
        expect(store.replanning()).toBe(false);
        expect(store.planDigest()).toBe('dg2');
        expect(store.confirmGroup(store.groups()[0])).toBe(true);
      });

      it('lifts the pause when the re-plan fails or is cancelled', async () => {
        const slow = new Subject<unknown>();
        routePlan(slow, slow);
        move(50);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        expect(store.replanning()).toBe(true);
        slow.error(new HttpErrorResponse({ status: 500 }));
        await settle();
        expect(store.replanning()).toBe(false);
        const pending = new Subject<unknown>();
        routePlan(pending);
        move(60);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        expect(store.replanning()).toBe(true);
        store.resetForReload();
        expect(store.replanning()).toBe(false);
      });

      it('waits for a confirm-all still committing before it asks for the new plan', async () => {
        const commit = new Subject<unknown>();
        api.post.mockImplementation((path: string) => (path === '/culling-groups/confirm' ? commit : of(NEW_PLAN)));
        const all = store.confirmAllRemaining(store.groups());
        move(50);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        expect(planCalls()).toHaveLength(0);
        commit.next({});
        commit.complete();
        await all;
        await settle();
        expect(api.post.mock.calls.map(c => c[0])).toEqual(['/culling-groups/confirm', '/culling-groups/confirm', '/culling/plan']);
        expect(store.planDigest()).toBe('dg2');
      });

      it('drops the answer when the assistant pinned another plan while it was in flight', async () => {
        const slow = new Subject<unknown>();
        routePlan(slow);
        move(50);
        await vi.advanceTimersByTimeAsync(CULL_REPLAN_DEBOUNCE_MS);
        await settle();
        plan.setPin({ digest: 'D2', request: { group_by: 'all' } });
        slow.next(NEW_PLAN);
        slow.complete();
        await settle();
        expect(plan.pin()?.digest).toBe('D2');
        expect(store.planDigest()).toBe('dg');
        expect(store.groups().map(g => store.groupKey(g))).toEqual(['5_burst', '5_similar']);
      });
    });
  });
});
