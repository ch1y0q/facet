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
  dry_run: true, preview: [], preview_truncated: false,
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
});
