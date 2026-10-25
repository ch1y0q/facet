import { createEnvironmentInjector, EnvironmentInjector, signal, ChangeDetectorRef, runInInjectionContext } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { ActivatedRoute, Event as RouterEvent, NavigationStart, NavigationCancel, NavigationError, NavigationEnd, Router, RouterOutlet } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatDialog } from '@angular/material/dialog';
import { MatBottomSheet } from '@angular/material/bottom-sheet';
import { LiveAnnouncer } from '@angular/cdk/a11y';
import { of, Subject } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { AlbumService } from '../../core/services/album.service';
import { I18nService } from '../../core/services/i18n.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { makePhoto } from '../../../testing/photo.fixture';
import { GalleryStore, PhotosResponse } from './gallery.store';
import { GalleryComponent } from './gallery.component';
import { CardActionsService } from './card-actions.service';
import { ScanService } from '../../core/services/scan.service';
import { PhotoActionsService } from '../../core/services/photo-actions.service';
import { UndoService } from '../../core/services/undo.service';
import { SequenceOverrideService } from '../../core/services/sequence-override.service';
import { HeaderSlotService } from '../../core/services/header-slot.service';
import { PageHelpService } from '../../core/services/page-help.service';

const EMPTY_PAGE: PhotosResponse = {
  photos: [], total: 0, page: 1, per_page: 64, total_pages: 1, has_more: false,
};
const COUNTS = { total: 10, undecided: 8, kept: 1, rejected: 1 };

describe('GalleryStore read cancellation with HttpClient', () => {
  let store: GalleryStore;
  let owner: EnvironmentInjector;
  let destroyed: boolean;
  let http: HttpTestingController;
  let identity: ReturnType<typeof signal<string>>;
  let events: Subject<RouterEvent>;
  let snack: ReturnType<typeof vi.fn>;
  let outlet: { attachEvents: Subject<unknown>; detachEvents: Subject<unknown> };

  function destroyStore(): void {
    owner.destroy();
    destroyed = true;
  }

  function request(url: string): TestRequest {
    return http.expectOne(r => r.url === `/api${url}`);
  }

  beforeEach(() => {
    identity = signal('alice');
    events = new Subject<RouterEvent>();
    snack = vi.fn();
    destroyed = false;
    outlet = { attachEvents: new Subject(), detachEvents: new Subject() };
    TestBed.configureTestingModule({ providers: [
      ApiService, provideHttpClient(withXhr()), provideHttpClientTesting(),
      { provide: AuthService, useValue: { identity, isEdition: () => false } },
      { provide: Router, useValue: { url: '/', events, navigate: vi.fn(), currentNavigation: () => null } },
      { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {}, paramMap: { get: () => null } } } },
      { provide: RouterOutlet, useValue: outlet },
      { provide: ChangeDetectorRef, useValue: { detectChanges: vi.fn() } },
      { provide: CardActionsService, useValue: { config: signal({}) } },
      { provide: ScanService, useValue: { canLaunch: signal(false) } },
      { provide: MatDialog, useValue: {} }, { provide: MatBottomSheet, useValue: {} },
      { provide: LiveAnnouncer, useValue: { announce: vi.fn() } },
      { provide: PhotoActionsService, useValue: {} }, { provide: UndoService, useValue: {} },
      { provide: SequenceOverrideService, useValue: {} },
      { provide: HeaderSlotService, useValue: { set: vi.fn(), clear: vi.fn() } },
      { provide: PageHelpService, useValue: { setDescription: vi.fn() } },
      { provide: AlbumService, useValue: { update: vi.fn(() => of({})) } },
      { provide: I18nService, useValue: { t: (key: string) => key } },
      { provide: MatSnackBar, useValue: { open: snack } },
      { provide: AssistantChangesService, useValue: { batch$: new Subject() } },
      { provide: UserActivityJournal, useValue: { record: vi.fn(), recordFilters: vi.fn() } },
    ] });
    http = TestBed.inject(HttpTestingController);
    owner = createEnvironmentInjector([GalleryStore], TestBed.inject(EnvironmentInjector));
    store = owner.get(GalleryStore);
    TestBed.tick();
  });

  afterEach(() => {
    if (!destroyed) destroyStore();
    http.verify();
  });

  it('bounds a burst of 30 filter changes to one active page and one progress request', async () => {
    const pages: TestRequest[] = [];
    const progress: TestRequest[] = [];
    const loads: Promise<void>[] = [];
    const activePages: number[] = [];
    const activeProgress: number[] = [];
    for (let i = 0; i < 30; i++) {
      loads.push(store.updateFilter('camera', `Camera ${i}`));
      pages.push(request('/photos'));
      progress.push(request('/photos/review_progress'));
      activePages.push(pages.filter(r => !r.cancelled).length);
      activeProgress.push(progress.filter(r => !r.cancelled).length);
    }
    expect(activePages).toEqual(Array(30).fill(1));
    expect(activeProgress).toEqual(Array(30).fill(1));
    expect(pages.slice(0, -1).every(r => r.cancelled)).toBe(true);
    expect(progress.slice(0, -1).every(r => r.cancelled)).toBe(true);
    expect(pages[29].request.params.get('camera')).toBe('Camera 29');
    pages[29].flush(EMPTY_PAGE);
    progress[29].flush(COUNTS);
    await Promise.all(loads);
    expect(store.reviewProgress()).toEqual(COUNTS);
    expect(store.loadError()).toBe(false);
    expect(store.loading()).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it.each(['pinned', 'similar'] as const)('cancels old progress when a %s view needs no aggregate request', async mode => {
    const oldLoad = store.loadPhotos();
    const oldPage = request('/photos');
    const oldProgress = request('/photos/review_progress');
    const newLoad = mode === 'pinned' ? store.showPaths(['/pin.jpg']) : store.updateFilter('similar_to', '/seed.jpg');
    const next = request(mode === 'pinned' ? '/photos/by_paths' : `/similar_photos/${encodeURIComponent('/seed.jpg')}`);
    expect(oldPage.cancelled).toBe(true);
    expect(oldProgress.cancelled).toBe(true);
    http.expectNone(r => r.url === '/api/photos/review_progress');
    next.flush(mode === 'pinned' ? { photos: [], total: 0, missing: [] } : { similar: [], total: 0, has_more: false });
    await Promise.all([oldLoad, newLoad]);
    expect(store.reviewProgress()).toBeNull();
    expect(store.loadError()).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it.each(['pinned', 'similar'] as const)('cancels the obsolete %s page read', async mode => {
    const oldLoad = mode === 'pinned' ? store.showPaths(['/pin.jpg']) : store.updateFilter('similar_to', '/seed.jpg');
    const oldPage = request(mode === 'pinned' ? '/photos/by_paths' : `/similar_photos/${encodeURIComponent('/seed.jpg')}`);
    const nextLoad = store.updateFilter('similar_to', '');
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    expect(oldPage.cancelled).toBe(true);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await Promise.all([oldLoad, nextLoad]);
    expect(store.loadError()).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it.each(['identity', 'navigation', 'destroy'] as const)('cancels reads on %s without a UI error', async change => {
    const loading = store.loadPhotos();
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    if (change === 'identity') { identity.set('bob'); TestBed.tick(); }
    else if (change === 'navigation') events.next(new NavigationStart(1, '/stats'));
    else destroyStore();
    expect(page.cancelled).toBe(true);
    expect(progress.cancelled).toBe(true);
    await loading;
    expect(store.loading()).toBe(false);
    expect(store.loadError()).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it('keeps a fresh new-principal read when the identity effect runs after it starts', async () => {
    const oldLoad = store.loadPhotos();
    const oldPage = request('/photos');
    const oldProgress = request('/photos/review_progress');
    identity.set('bob');
    const nextLoad = store.loadPhotos();
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    TestBed.tick();
    expect(oldPage.cancelled).toBe(true);
    expect(oldProgress.cancelled).toBe(true);
    expect(page.cancelled).toBe(false);
    expect(progress.cancelled).toBe(false);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await Promise.all([oldLoad, nextLoad]);
    expect(store.reviewProgress()).toEqual(COUNTS);
    expect(store.loadError()).toBe(false);
  });

  it('keeps the first page and progress read when initialization effects first run', async () => {
    destroyStore();
    owner = createEnvironmentInjector([GalleryStore], TestBed.inject(EnvironmentInjector));
    destroyed = false;
    store = owner.get(GalleryStore);
    const loading = store.loadPhotos();
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    TestBed.tick();
    expect(page.cancelled).toBe(false);
    expect(progress.cancelled).toBe(false);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await loading;
    expect(store.reviewProgress()).toEqual(COUNTS);
  });

  it.each(['/?camera=Canon', '/#gallery'])('keeps a new read across same-path URL synchronization to %s', async url => {
    const loading = store.updateFilter('camera', 'Canon');
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    events.next(new NavigationStart(1, url));
    TestBed.tick();
    expect(page.cancelled).toBe(false);
    expect(progress.cancelled).toBe(false);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await loading;
    expect(store.reviewProgress()).toEqual(COUNTS);
  });

  it.each(['ordinary', 'similar'] as const)('cancels an obsolete %s pagination request without reverting the new page or showing an error', async mode => {
    store.photos.set([makePhoto({ path: '/old.jpg' })]);
    store.hasMore.set(true);
    if (mode === 'similar') store.filters.update(f => ({ ...f, similar_to: '/seed.jpg' }));
    const paging = store.nextPage();
    const oldPage = request(mode === 'similar' ? `/similar_photos/${encodeURIComponent('/seed.jpg')}` : '/photos');
    const loading = store.updateFilters({ camera: 'Canon', similar_to: '' });
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    expect(oldPage.cancelled).toBe(true);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await Promise.all([paging, loading]);
    expect(store.filters().page).toBe(1);
    expect(store.photos()).toEqual([]);
    expect(store.loadError()).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it.each(['cancel', 'error'] as const)('recovers a cancelled initial listing when navigation ends with %s', async ending => {
    const loading = store.loadPhotos();
    const oldPage = request('/photos');
    const oldProgress = request('/photos/review_progress');
    events.next(new NavigationStart(1, '/stats'));
    events.next(ending === 'cancel' ? new NavigationCancel(1, '/stats', 'guard refused')
      : new NavigationError(1, '/stats', new Error('route failed')));
    const progress = request('/photos/review_progress');
    await Promise.resolve();
    const page = request('/photos');
    expect(oldPage.cancelled).toBe(true);
    expect(oldProgress.cancelled).toBe(true);
    page.flush({ ...EMPTY_PAGE, total: 1, photos: [makePhoto({ path: '/restored.jpg' })] });
    progress.flush(COUNTS);
    await loading;
    await Promise.resolve();
    request('/photos/keeper_hints').flush({});
    expect(store.photos().map(p => p.path)).toEqual(['/restored.jpg']);
    expect(store.loadError()).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it('resumes the real store through its own gallery outlet attach after photo navigation and Back', async () => {
    const gallery = runInInjectionContext(owner, () => new GalleryComponent());
    vi.spyOn(store, 'loadTypeCounts').mockResolvedValue();
    vi.spyOn(store, 'loadFilterOptions').mockResolvedValue();
    const initial = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, total: 1, has_more: true, photos: [makePhoto({ path: '/a.jpg' })] });
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    request('/photos/keeper_hints').flush({});
    store.selectedPaths.set(new Set(['/a.jpg']));
    events.next(new NavigationStart(1, '/photo?path=/a.jpg'));
    outlet.detachEvents.next(gallery);
    await store.refreshPaths(['/a.jpg']);
    http.expectNone(r => r.url === '/api/photos');
    outlet.attachEvents.next({});
    http.expectNone(r => r.url === '/api/photos/review_progress');
    outlet.attachEvents.next(gallery);
    request('/photos/review_progress').flush(COUNTS);
    await Promise.resolve();
    request('/photos').flush({ ...EMPTY_PAGE, total: 1, has_more: true, photos: [makePhoto({ path: '/a.jpg', is_favorite: true })] });
    await Promise.resolve();
    await Promise.resolve();
    request('/photos/keeper_hints').flush({});
    expect(store.selectedPaths()).toEqual(new Set(['/a.jpg']));
    expect(store.photos()[0].is_favorite).toBe(true);
    const paging = store.nextPage();
    request('/photos').flush({ ...EMPTY_PAGE, page: 2 });
    await paging;
    expect(store.filters().page).toBe(2);
  });

  it.each([false, true])('restores interrupted similarity pages on return (pagination=%s)', async pagination => {
    const firstLoad = store.updateFilter('similar_to', '/seed.jpg');
    const first = request(`/similar_photos/${encodeURIComponent('/seed.jpg')}`);
    let interrupted: Promise<void> = firstLoad;
    if (pagination) {
      first.flush({ similar: [makePhoto({ path: '/first.jpg' })], total: 2, has_more: true });
      await firstLoad;
      interrupted = store.nextPage();
      request(`/similar_photos/${encodeURIComponent('/seed.jpg')}`);
    }
    store.selectedPaths.set(new Set(['/first.jpg']));
    events.next(new NavigationStart(1, '/photo?path=/first.jpg'));
    store.parkListingReads();
    const resuming = store.resumeListingReads();
    const page = request(`/similar_photos/${encodeURIComponent('/seed.jpg')}`);
    expect(page.request.params.get('offset')).toBe('0');
    page.flush({ similar: [makePhoto({ path: '/first.jpg' })], total: 2, has_more: pagination });
    if (pagination) {
      await Promise.resolve();
      const tail = request(`/similar_photos/${encodeURIComponent('/seed.jpg')}`);
      expect(tail.request.params.get('offset')).toBe('64');
      tail.flush({ similar: [makePhoto({ path: '/second.jpg' })], total: 2, has_more: false });
    }
    await Promise.all([interrupted, resuming]);
    expect(store.photos().map(p => p.path)).toEqual(pagination ? ['/first.jpg', '/second.jpg'] : ['/first.jpg']);
    expect(store.selectedPaths()).toEqual(new Set(['/first.jpg']));
    expect(store.loadError()).toBe(false);
  });

  it('retains Undo for a confirmed Keep that removes a photo during the parked refresh', async () => {
    store.filters.update(f => ({ ...f, review_status: 'undecided' }));
    const initial = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, total: 1, photos: [makePhoto({ path: '/a.jpg' })] });
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    request('/photos/keeper_hints').flush({});
    const snapshot = new Map([['/a.jpg', { is_kept: false, is_rejected: false, is_favorite: false, star_rating: null }]]);
    const keeping = store.batchReview(['/a.jpg'], 'kept');
    const write = request('/photos/batch_review');
    events.next(new NavigationStart(1, '/photo?path=/a.jpg'));
    store.parkListingReads();
    write.flush({ count: 1 });
    await keeping;
    const resuming = store.resumeListingReads();
    request('/photos/review_progress').flush(COUNTS);
    await Promise.resolve();
    request('/photos').flush(EMPTY_PAGE);
    await resuming;
    expect(store.photos()).toEqual([]);
    const undo = store.restoreSnapshot(snapshot);
    let reset!: TestRequest;
    await vi.waitFor(() => { reset = request('/photos/batch_review'); });
    expect(reset.request.body).toEqual({ photo_paths: ['/a.jpg'], decision: 'undecided' });
    reset.flush({ count: 1 });
    let restored!: TestRequest;
    await vi.waitFor(() => { restored = request('/photos'); });
    for (const progress of http.match(r => r.url === '/api/photos/review_progress')) {
      if (!progress.cancelled) progress.flush(COUNTS);
    }
    restored.flush({ ...EMPTY_PAGE, total: 1, photos: [makePhoto({ path: '/a.jpg', is_kept: false })] });
    await undo;
    request('/photos/keeper_hints').flush({});
    expect(store.photos()[0].is_kept).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it('coalesces parked confirmed writes and assistant changes into one in-place refresh on return', async () => {
    const initial = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, total: 1, has_more: true, photos: [makePhoto({ path: '/a.jpg' })] });
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    request('/photos/keeper_hints').flush({});
    store.selectedPaths.set(new Set(['/a.jpg']));
    const selected = store.selectedPaths();
    const writing = store.setRating('/a.jpg', 4);
    const rating = request('/photo/set_rating');
    events.next(new NavigationStart(1, '/photo?path=/a.jpg'));
    store.parkListingReads();
    events.next(new NavigationEnd(1, '/photo?path=/a.jpg', '/photo?path=/a.jpg'));
    rating.flush({ success: true });
    await writing;
    await store.refreshPaths(['/a.jpg']);
    await store.refreshPaths(null);
    await store.refreshReviewResults();
    http.expectNone(r => r.url === '/api/photos' || r.url === '/api/photos/review_progress');
    // Back's NavigationEnd alone must not start work for another page.
    events.next(new NavigationEnd(2, '/stats', '/stats'));
    http.expectNone(r => r.url === '/api/photos');
    const resumed = store.resumeListingReads();
    const duplicateAttach = store.resumeListingReads();
    request('/photos/review_progress').flush(COUNTS);
    await Promise.resolve();
    request('/photos').flush({ ...EMPTY_PAGE, total: 1, has_more: true, photos: [makePhoto({ path: '/a.jpg', star_rating: 4 })] });
    await Promise.all([resumed, duplicateAttach]);
    request('/photos/keeper_hints').flush({});
    expect(store.selectedPaths()).toBe(selected);
    expect(store.photos()[0].star_rating).toBe(4);
    expect(store.loadError()).toBe(false);
    http.expectNone(r => r.url === '/api/photos');
    // Paging is live again without a filter change or a new gallery init.
    const paging = store.nextPage();
    request('/photos').flush({ ...EMPTY_PAGE, page: 2, total: 1 });
    await paging;
    expect(store.filters().page).toBe(2);
  });

  it('cancels a pending review tail refill before loading a new filter', async () => {
    store.filters.update(f => ({ ...f, review_status: 'undecided' }));
    store.photos.set([makePhoto({ path: '/kept.jpg', is_kept: true })]);
    const refill = store.refreshReviewResults();
    const oldPage = request('/photos');
    const oldProgress = request('/photos/review_progress');
    const loading = store.updateFilter('camera', 'Canon');
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    expect(oldPage.cancelled).toBe(true);
    expect(oldProgress.cancelled).toBe(true);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await Promise.all([refill, loading]);
    expect(store.loadError()).toBe(false);
  });

  it('cancels assistant page refreshes and discards queued refreshes after the view changes', async () => {
    const initial = store.loadPhotos();
    request('/photos').flush(EMPTY_PAGE);
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    store.filters.update(f => ({ ...f, page: 2 }));
    const refresh = store.refreshPaths(null);
    const oldProgress = request('/photos/review_progress');
    const queued = store.refreshPaths(null);
    const queuedProgress = request('/photos/review_progress');
    await Promise.resolve();
    const oldPage = request('/photos');
    const loading = store.updateFilter('camera', 'Canon');
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    expect(oldPage.cancelled).toBe(true);
    expect(oldProgress.cancelled).toBe(true);
    expect(queuedProgress.cancelled).toBe(true);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await Promise.all([refresh, queued, loading]);
    http.expectNone(r => r.url === '/api/photos');
    expect(store.loadError()).toBe(false);
  });

  it('cancels a read-only by-path refresh without cancelling a pending rating write', async () => {
    const initial = store.showPaths(['/pin.jpg']);
    request('/photos/by_paths').flush({ photos: [makePhoto({ path: '/pin.jpg' })], total: 1, missing: [] });
    await initial;
    const refreshing = store.refreshPaths(['/pin.jpg']);
    await Promise.resolve();
    const oldRead = request('/photos/by_paths');
    const writing = store.setRating('/pin.jpg', 4);
    const rating = request('/photo/set_rating');
    const loading = store.updateFilter('camera', 'Canon');
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    expect(oldRead.cancelled).toBe(true);
    expect(rating.cancelled).toBe(false);
    rating.flush({ success: true });
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await Promise.all([refreshing, writing, loading]);
    expect(store.loadError()).toBe(false);
    expect(snack).not.toHaveBeenCalled();
  });

  it('cancels obsolete keeper-hint reads after a replacement load', async () => {
    const initial = store.loadPhotos();
    request('/photos').flush({ ...EMPTY_PAGE, photos: [makePhoto({ path: '/old.jpg' })] });
    request('/photos/review_progress').flush(COUNTS);
    await initial;
    const hints = request('/photos/keeper_hints');
    const loading = store.updateFilter('camera', 'Canon');
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    expect(hints.cancelled).toBe(true);
    page.flush(EMPTY_PAGE);
    progress.flush(COUNTS);
    await loading;
    expect(snack).not.toHaveBeenCalled();
  });

  it.each(['navigation', 'destroy'] as const)('allows an already-submitted rating write to finish after %s', async change => {
    store.photos.set([makePhoto({ path: '/rated.jpg' })]);
    store.filters.update(f => ({ ...f, sort: 'star_rating' }));
    const writing = store.setRating('/rated.jpg', 4);
    const rating = request('/photo/set_rating');
    const loading = store.loadPhotos();
    const page = request('/photos');
    const progress = request('/photos/review_progress');
    if (change === 'navigation') events.next(new NavigationStart(1, '/stats'));
    else destroyStore();
    expect(page.cancelled).toBe(true);
    expect(progress.cancelled).toBe(true);
    expect(rating.cancelled).toBe(false);
    rating.flush({ success: true });
    await Promise.all([writing, loading]);
    // A write may finish, but a destroyed store must not start new reads.
    const followup = http.match(r => r.url === '/api/photos/review_progress');
    expect(followup).toHaveLength(0);
    for (const read of followup) read.flush(COUNTS);
    expect(snack).not.toHaveBeenCalled();
  });
});
