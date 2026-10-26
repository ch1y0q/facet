import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { NavigationEnd, Router, provideRouter } from '@angular/router';
import { MatSnackBar } from '@angular/material/snack-bar';
import { NEVER, filter, firstValueFrom, take } from 'rxjs';
import { AuthService, AuthStatus } from '../../core/services/auth.service';
import { AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from './gallery.store';
import { DEFAULT_FILTERS } from './gallery-filters.util';
import { readReviewQueue, saveReviewQueue } from './review-queue.util';

@Component({ template: '' })
class QueueTestPage {}

const status: AuthStatus = {
  authenticated: false, multi_user: false, edition_enabled: true, edition_authenticated: true,
  edition_password_required: true, login_password_required: false, user_id: null,
  user_role: null, display_name: null, features: {}, download_profiles: [],
};
const privateFilters = { ...DEFAULT_FILTERS, review_status: 'undecided' as const,
  search: 'private query', person_id: '17', path_prefix: '/private/trip/', album_id: '23' };

describe('review queue logout privacy', () => {
  let auth: AuthService;
  let store: GalleryStore;
  let router: Router;
  let http: HttpTestingController;

  beforeEach(async () => {
    localStorage.clear();
    TestBed.configureTestingModule({ providers: [
      GalleryStore, provideHttpClient(withXhr()), provideHttpClientTesting(),
      provideRouter([{ path: '', component: QueueTestPage }, { path: 'login', component: QueueTestPage },
        { path: 'photo', component: QueueTestPage }]),
      { provide: MatSnackBar, useValue: { open: vi.fn() } },
      { provide: I18nService, useValue: { t: (key: string) => key } },
      { provide: AssistantChangesService, useValue: { batch$: NEVER } },
    ] });
    auth = TestBed.inject(AuthService);
    auth.status.set(status);
    router = TestBed.inject(Router);
    await router.navigateByUrl('/');
    store = TestBed.inject(GalleryStore);
    http = TestBed.inject(HttpTestingController);
    TestBed.tick();
  });

  afterEach(() => {
    http.verify();
    vi.restoreAllMocks();
    localStorage.clear();
  });

  const loggedOut = () => firstValueFrom(router.events.pipe(filter(event => event instanceof NavigationEnd), take(1)));

  it.each([null, 'alice'])('clears all private bookmarks and the active bookmark on logout (user %s)', async user => {
    auth.status.set(user ? { ...status, authenticated: true, multi_user: true, user_id: user } : status);
    const owner = auth.identity();
    saveReviewQueue(owner, privateFilters);
    saveReviewQueue('1|bob', privateFilters);
    localStorage.setItem('facet_last_sort', 'date_taken');
    expect(store.reviewBookmark()?.filters).toMatchObject(privateFilters);
    const navigation = loggedOut();
    auth.logout();
    http.expectOne('/api/auth/logout').flush({}, { status: 503, statusText: 'Unavailable' });
    // Logout is synchronous even if server-side cookie cleanup fails.
    expect(localStorage.getItem('facet_review_queues_v1')).toBeNull();
    expect(store.reviewBookmark()).toBeNull();
    expect(readReviewQueue('1|bob')).toBeNull();
    expect(localStorage.getItem('facet_last_sort')).toBe('date_taken');
    await navigation;
    expect(router.url).toBe('/login');
    // A later session with the same identity must not recover the old private scope.
    const checking = auth.checkStatus();
    http.expectOne('/api/auth/status').flush(user ? { ...status, authenticated: true, multi_user: true, user_id: user } : status);
    await checking;
    expect(auth.identity()).toBe(owner);
    expect(store.reviewBookmark()).toBeNull();
  });

  it('does not recreate a cleared bookmark when a single-user response was queued before logout', async () => {
    const owner = auth.identity();
    saveReviewQueue(owner, privateFilters);
    expect(store.reviewBookmark()).not.toBeNull();
    store.filters.set(privateFilters);
    const loading = store.loadPhotos();
    http.expectOne(req => req.url === '/api/photos/review_progress').flush({ total: 0, undecided: 0, kept: 0, rejected: 0 });
    // Queue the promise continuation before NavigationStart can cancel the request.
    http.expectOne(req => req.url === '/api/photos').flush({ photos: [], total: 0, has_more: false });
    const navigation = loggedOut();
    auth.logout();
    http.expectOne('/api/auth/logout').flush({ ok: true });
    expect(auth.identity()).toBe(owner); // The single-user sentinel is unchanged.
    await loading;
    await navigation;
    expect(localStorage.getItem('facet_review_queues_v1')).toBeNull();
    expect(store.reviewBookmark()).toBeNull();
  });

  it('invalidates a queued single-user response when another tab clears review bookmarks', async () => {
    saveReviewQueue(auth.identity(), privateFilters);
    expect(store.reviewBookmark()).not.toBeNull();
    store.filters.set(privateFilters);
    const loading = store.loadPhotos();
    http.expectOne(req => req.url === '/api/photos/review_progress').flush({ total: 0, undecided: 0, kept: 0, rejected: 0 });
    http.expectOne(req => req.url === '/api/photos').flush({ photos: [], total: 0, has_more: false });
    localStorage.removeItem('facet_review_queues_v1');
    window.dispatchEvent(new StorageEvent('storage', { key: 'facet_review_queues_v1', newValue: null }));
    await loading;
    expect(localStorage.getItem('facet_review_queues_v1')).toBeNull();
    expect(store.reviewBookmark()).toBeNull();
  });

  it('continues logout when removing browser bookmarks is denied', async () => {
    const remove = Storage.prototype.removeItem;
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(function (this: Storage, key: string) {
      if (key === 'facet_review_queues_v1') throw new Error('SecurityError');
      remove.call(this, key);
    });
    const navigation = loggedOut();
    expect(() => auth.logout()).not.toThrow();
    http.expectOne('/api/auth/logout').flush({ ok: true });
    await navigation;
    expect(auth.status()).toBeNull();
    expect(router.url).toBe('/login');
  });

  it('keeps same-account resume across normal navigation and status revalidation', async () => {
    store.filters.set(privateFilters);
    const loading = store.loadPhotos();
    http.expectOne(req => req.url === '/api/photos/review_progress').flush({ total: 0, undecided: 0, kept: 0, rejected: 0 });
    http.expectOne(req => req.url === '/api/photos').flush({ photos: [], total: 0, has_more: false });
    await loading;
    expect(store.reviewBookmark()?.filters.path_prefix).toBe('/private/trip/');
    await router.navigateByUrl('/photo');
    const checking = auth.checkStatus();
    http.expectOne('/api/auth/status').flush({ ...status });
    await checking;
    await router.navigateByUrl('/');
    expect(readReviewQueue(auth.identity())?.filters).toMatchObject(privateFilters);
    expect(store.reviewBookmark()?.filters).toMatchObject(privateFilters);
  });
});
