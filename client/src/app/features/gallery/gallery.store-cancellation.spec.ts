import { createEnvironmentInjector, EnvironmentInjector, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting, TestRequest } from '@angular/common/http/testing';
import { ActivatedRoute, Event as RouterEvent, NavigationStart, Router } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';
import { of, Subject } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { AlbumService } from '../../core/services/album.service';
import { I18nService } from '../../core/services/i18n.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { makePhoto } from '../../../testing/photo.fixture';
import { GalleryStore, PhotosResponse } from './gallery.store';

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
    TestBed.configureTestingModule({ providers: [
      ApiService, provideHttpClient(withXhr()), provideHttpClientTesting(),
      { provide: AuthService, useValue: { identity, isEdition: () => false } },
      { provide: Router, useValue: { url: '/', events, navigate: vi.fn(), currentNavigation: () => null } },
      { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {} } } },
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
