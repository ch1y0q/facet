import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { OverlayContainer } from '@angular/cdk/overlay';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpRequest, provideHttpClient, withInterceptors, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ActivatedRoute, convertToParamMap, provideRouter } from '@angular/router';
import { MATERIAL_ANIMATIONS, provideNativeDateAdapter } from '@angular/material/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { NEVER, Subject, filter, firstValueFrom, take } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { ScanService } from '../../core/services/scan.service';
import { AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { makePhoto } from '../../../testing/photo.fixture';
import { GalleryComponent } from './gallery.component';
import { GalleryStore } from './gallery.store';

const counts = { total: 2, undecided: 2, kept: 0, rejected: 0 };
const rows = [makePhoto({ path: '/trip/a.jpg' }), makePhoto({ path: '/trip/b.jpg' })];
const page = { photos: rows, total: 2, page: 1, per_page: 64, total_pages: 1, has_more: false };
const config = {
  pagination: { default_per_page: 64 },
  defaults: { sort: 'star_rating', sort_direction: 'ASC', gallery_mode: 'grid', hide_details: true },
  display: { card_width_px: 168, image_width_px: 640, tags_per_photo: 5 },
  features: { show_rating_controls: true },
  quality_thresholds: { good: 6, great: 7, excellent: 8, best: 9 },
  sort_options_grouped: [], search_threshold_default: 0.15,
};

describe('manual review activity from rendered gallery menus', () => {
  let fixture: ComponentFixture<GalleryComponent>;
  let store: GalleryStore;
  let http: HttpTestingController;
  let auth: AuthService;
  let requests: Subject<HttpRequest<unknown>>;
  const requested = (url: string) => firstValueFrom(requests.pipe(filter(request => request.url === url), take(1)));
  const progressRequests = () => http.match(request => request.url === '/api/photos/review_progress');
  const flushSideData = () => {
    for (const request of http.match(request => request.url.startsWith('/api/filter_options/') || request.url === '/api/type_counts')) {
      request.flush({ types: [], cameras: [], lenses: [], tags: [], persons: [], patterns: [], temps: [], hue_buckets: [], ranges: {} });
    }
    for (const request of http.match('/api/photos/keeper_hints')) request.flush({});
  };

  beforeEach(async () => {
    localStorage.clear(); sessionStorage.clear();
    requests = new Subject();
    TestBed.configureTestingModule({ providers: [
      provideHttpClient(withXhr(), withInterceptors([(request, next) => { requests.next(request); return next(request); }])), provideHttpClientTesting(), provideRouter([]), provideNativeDateAdapter(),
      { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
      { provide: ActivatedRoute, useValue: { snapshot: { queryParams: {}, paramMap: convertToParamMap({}) } } },
      { provide: ScanService, useValue: { canLaunch: signal(false) } },
      { provide: I18nService, useValue: { translations: signal({}), locale: () => 'en', t: (key: string, params?: unknown) => `${key} ${JSON.stringify(params ?? {})}` } },
      { provide: AssistantChangesService, useValue: { batch$: NEVER } },
      { provide: MatSnackBar, useValue: { open: vi.fn(() => ({ onAction: () => NEVER, afterDismissed: () => NEVER })) } },
    ] });
    auth = TestBed.inject(AuthService);
    auth.status.set({ authenticated: true, multi_user: true, edition_enabled: true, edition_authenticated: true,
      edition_password_required: false, login_password_required: true, user_id: 'alice', user_role: 'admin',
      display_name: 'Alice', features: {}, download_profiles: [] });
    http = TestBed.inject(HttpTestingController);
    store = TestBed.inject(GalleryStore);
    fixture = TestBed.createComponent(GalleryComponent);
    fixture.detectChanges();
    const photosStarted = requested('/api/photos');
    http.expectOne('/api/config').flush(config);
    await photosStarted;
    const sideDataStarted = requested('/api/filter_options/metric_ranges');
    http.expectOne(request => request.url === '/api/photos').flush(page);
    progressRequests().forEach(request => request.flush(counts));
    await sideDataStarted;
    flushSideData();
    await fixture.whenStable();
    fixture.detectChanges();
    expect(store.photos()).toHaveLength(2);
  });

  afterEach(() => {
    fixture.destroy();
    TestBed.resetTestingModule();
    http.verify({ ignoreCancelled: true });
    localStorage.clear(); sessionStorage.clear();
  });

  it.each([
    ['kept', false], ['undecided', false], ['kept', true], ['undecided', true],
  ] as const)('reports %s from the real %s-bulk context-menu dispatch after HTTP success', async (decision, bulk) => {
    const journal = TestBed.inject(UserActivityJournal);
    const cursor = journal.since().until;
    const batch = vi.spyOn(store, 'batchReview');
    if (bulk) store.selectedPaths.set(new Set(rows.map(photo => photo.path)));
    fixture.detectChanges();
    const card = fixture.nativeElement.querySelector('app-photo-card');
    card.dispatchEvent(new MouseEvent('contextmenu', { bubbles: true, cancelable: true, button: 2 }));
    fixture.detectChanges();
    await fixture.whenStable();
    const overlay = TestBed.inject(OverlayContainer).getContainerElement();
    const label = decision === 'kept' ? 'review.keep' : 'review.reset';
    const button = [...overlay.querySelectorAll<HTMLButtonElement>('button[mat-menu-item]')]
      .find(button => button.textContent?.includes(label + ' {}'));
    expect(button).toBeDefined();
    const writeStarted = requested('/api/photos/batch_review');
    button!.click();
    await writeStarted;
    expect(journal.since(cursor).items).toEqual([]);
    const request = http.expectOne('/api/photos/batch_review');
    expect(request.request.body).toEqual({ photo_paths: bulk ? rows.map(photo => photo.path) : [rows[0].path], decision });
    const countStarted = requested('/api/photos/review_progress');
    request.flush({ count: bulk ? 2 : 1 });
    await countStarted;
    progressRequests().forEach(request => request.flush(counts));
    await batch.mock.results[0].value;
    await fixture.whenStable();
    expect(journal.since(cursor).items).toEqual([expect.objectContaining({
      kind: 'review', value: decision, paths: bulk ? rows.map(photo => photo.path) : [rows[0].path],
    })]);
  });
});
