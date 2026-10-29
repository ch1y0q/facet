import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideNativeDateAdapter } from '@angular/material/core';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { StackDialogComponent } from './stack-dialog.component';
import { MatDialog } from '@angular/material/dialog';
import { Subject } from 'rxjs';
import { BurstCullingComponent } from './burst-culling.component';
import { CullingStore } from './culling.store';
import { AuthService } from '../../core/services/auth.service';
import { GalleryStore } from './gallery.store';
import { I18nService } from '../../core/services/i18n.service';
import { AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { AssistantCullPlanService } from '../../core/agent/assistant-cull-plan.service';
import { PageContextService } from '../../core/agent/page-context.service';
import { UndoService, UndoableCommand } from '../../core/services/undo.service';

@Component({ template: '' }) class GalleryDestination {}

describe('Suggested stacks routed darkroom', () => {
  let http: HttpTestingController;
  let harness: RouterTestingHarness;
  let page: BurstCullingComponent;
  let cull: CullingStore;
  let commands: UndoableCommand[];
  const identity = signal('owner');
  const edition = signal(true);
  const filters = { album_id: '42', camera: 'Camera & Lens', hide_blinks: 'false' };
  const origin = '/album/42?sort=date&tag=a%20b#focused';
  const group = (id: number, paths = ['/b.jpg', '/a.jpg']) => ({
    group_id: id, kind: 'duplicate', key: 'membership-' + id, paths, cover_path: paths[1],
    photos: paths.map(path => ({ path, filename: path.slice(1), aggregate: 8, is_blink: null,
      is_burst_lead: null, date_taken: null, burst_score: null, is_rejected: path.includes('b') ? 1 : 0, is_kept: 1 })),
  });
  const response = { suggestions: [group(1), group(2, ['/d.jpg', '/c.jpg'])] };
  const url = (returnUrl = origin, scope = JSON.stringify(filters)) => '/culling?mode=stacks&filters='
    + encodeURIComponent(scope) + '&return=' + encodeURIComponent(returnUrl);
  const dom = () => harness.routeNativeElement!;
  const key = (value: string, shiftKey = false) => document.dispatchEvent(new KeyboardEvent('keydown', {
    key: value, shiftKey, bubbles: true, cancelable: true,
  }));
  async function settle(): Promise<void> { await Promise.resolve(); await Promise.resolve(); TestBed.tick(); harness.detectChanges(); }
  async function enter(target = url()): Promise<void> {
    page = await harness.navigateByUrl(target, BurstCullingComponent);
    cull = harness.routeDebugElement!.injector.get(CullingStore);
  }
  function batch(value = response): void {
    const request = http.expectOne('/api/stacks/suggestions');
    expect(request.request.body).toEqual({ filters, include_photos: true });
    request.flush(value);
  }
  beforeEach(async () => {
    Element.prototype.scrollIntoView = vi.fn();
    localStorage.clear(); identity.set('owner'); edition.set(true); commands = [];
    TestBed.configureTestingModule({ providers: [
      provideHttpClient(), provideHttpClientTesting(), provideNativeDateAdapter(),
      provideRouter([{ path: 'culling', component: BurstCullingComponent },
        { path: '', component: GalleryDestination }, { path: 'album/:id', component: GalleryDestination }]),
      { provide: AuthService, useValue: { identity, isEdition: edition } },
      { provide: GalleryStore, useValue: { config: () => null, refreshPaths: async () => undefined } },
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
      { provide: AssistantChangesService, useValue: { batch$: new Subject() } },
      { provide: UndoService, useValue: { register: (command: UndoableCommand) => commands.push(command) } },
    ] });
    http = TestBed.inject(HttpTestingController);
    harness = await RouterTestingHarness.create();
  });
  afterEach(() => { try { http.verify(); } finally { TestBed.resetTestingModule(); } });

  it('initializes stack mode before effects and makes only the exact scoped suggestion request', async () => {
    const plan = TestBed.inject(AssistantCullPlanService);
    const pin = { digest: 'held', request: { group_by: 'burst' as const } };
    plan.setPin(pin);
    await enter();
    expect(cull.mode()).toBe('stacks'); batch(); await settle();
    expect(plan.pin()).toEqual(pin);
    expect(TestBed.inject(PageContextService).snapshot()).toEqual({ id: 'culling', mode: 'stacks' });
    expect(cull.selectionsMap().size).toBe(0);
    expect(TestBed.inject(Router).url).toBe(TestBed.inject(Router).serializeUrl(TestBed.inject(Router).parseUrl(url())));
    expect(http.match(() => true)).toEqual([]);
  });

  it('refuses the direct HttpClient detection transport in stack mode', async () => {
    await enter(); batch(); await settle();
    const pending = page['rerunDetection']();
    const requests = http.match('/api/scan/detect_panoramas');
    for (const request of requests) request.flush({});
    await pending;
    expect(requests).toHaveLength(0);
  });

  it('reloads the scope from the URL and returns to the exact album query and fragment', async () => {
    await enter(); batch(); await settle();
    await harness.navigateByUrl('/');
    await enter(); batch(); await settle();
    page['backToGallery'](); await settle();
    await vi.waitFor(() => expect(TestBed.inject(Router).url).toBe(origin));
  });

  it.each(['https://external.example', '//external.example', '/album/42(aux:photo)', '/album/42%ZZ', '/photo?path=private', '/album/42\\evil'])('refuses invalid return %s', async target => {
    await enter(url(target)); batch(); await settle(); page['backToGallery'](); await settle();
    await vi.waitFor(() => expect(TestBed.inject(Router).url).toBe('/'));
  });

  it('retains the normal culling toolbar, keep/reject tiles, confirm, pass and plan controls', async () => {
    page = await harness.navigateByUrl('/culling', BurstCullingComponent);
    cull = harness.routeDebugElement!.injector.get(CullingStore);
    for (const request of http.match(() => true)) {
      request.flush(request.request.url.includes('/culling-groups') ? {
        groups: response.suggestions.map(item => ({ ...item, type: 'burst', best_path: item.cover_path, count: item.paths.length })),
        total_groups: 2, page: 1, per_page: 20, total_pages: 1,
      } : request.request.url.includes('/culling/profiles') ? { profiles: [{ id: 'test', label_key: 'culling.profiles.test',
        strictness: 100, eyes_closed_max: null, poor_expression_min: null, keep_min_per_group: 1, similarity_threshold: 80 }], default: 'test' } : {});
    }
    await settle();
    cull.selectedProfile.set('test'); await settle();
    for (const label of ['culling.group_by.label', 'culling.threshold', 'culling.sort.easiest',
      'culling.sort.descending', 'culling.exclude_rejected', 'culling.auto_cull.button', 'culling.strictness',
      'culling.confirm', 'culling.skip', 'culling.profiles.test']) {
      expect(dom().querySelector(`[aria-label^="${label}"]`), label).not.toBeNull();
    }
    expect(dom().querySelector('[data-pidx][aria-pressed]')).not.toBeNull();
    expect(dom().textContent).toContain('culling.confirm_all');
    const group = cull.groups()[0];
    cull.passingGroups.set(new Map([[cull.groupKey(group), 3]])); await settle();
    expect(dom().textContent).toContain('culling.cancel_pass');
    cull.planActive.set(true); await settle();
    expect(dom().querySelector('[data-testid="cull-plan-banner"]')).not.toBeNull();
    cull.passingGroups.set(new Map()); cull.planActive.set(false);
    page['openLightbox'](group, 0);
    for (const request of http.match(() => true)) request.flush({});
    await settle();
    for (const request of http.match(() => true)) request.flush({});
    await settle();
    http.expectOne('/api/culling-group/subjects').flush({ subjects_by_path: {} }); await settle();
    page['compareMode'].set('2up'); await settle();
    expect(dom().querySelector('[aria-label*="culling.lightbox.keep"]')).not.toBeNull();
    expect(dom().querySelector('[aria-label*="culling.lightbox.reject"]')).not.toBeNull();
  });

  it('renders plain open tiles and hides culling toolbar and decision controls', async () => {
    await enter(); batch(); await settle();
    expect(dom().querySelector('[data-testid="stack-review-header"]')).not.toBeNull();
    expect(dom().textContent).not.toContain('culling.confirm_all');
    expect(dom().textContent).not.toContain('culling.cancel_pass');
    expect(dom().querySelector('[data-testid="cull-plan-banner"]')).toBeNull();
    const tiles = dom().querySelectorAll('[data-pidx]');
    expect(tiles).toHaveLength(4);
    for (const tile of tiles) {
      expect(tile.hasAttribute('aria-pressed')).toBe(false);
      expect(tile.getAttribute('aria-label')).not.toMatch(/kept|rejected|undecided/);
    }
    for (const label of ['culling.group_by.label', 'culling.threshold', 'culling.sort.easiest',
      'culling.sort.descending', 'culling.exclude_rejected', 'culling.auto_cull.button', 'culling.strictness', 'culling.confirm', 'culling.skip', 'culling.profiles.test']) {
      expect(dom().querySelector(`[aria-label^="${label}"]`)).toBeNull();
    }
    const toggle = vi.spyOn(cull, 'toggleSelection');
    (tiles[0] as HTMLElement).click(); await settle();
    expect(page['lightboxGroup']()?.group_id).toBe(1);
    expect(toggle).not.toHaveBeenCalled();
    expect(dom().querySelector('[data-testid="reject-marker"]')).toBeNull();
    expect(dom().querySelector('[data-testid="kept-marker"]')).toBeNull();
    expect(dom().querySelectorAll('[data-stack-filmstrip] button')).toHaveLength(2);
    const filmstrip = dom().querySelectorAll('[data-stack-filmstrip] button');
    filmstrip[1].dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    filmstrip[1].dispatchEvent(new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true }));
    expect(http.match('/api/stacks')).toHaveLength(0);
    (filmstrip[1] as HTMLButtonElement).click(); await settle(); expect(page['lightboxIndex']()).toBe(1);
    page['compareMode'].set('2up'); await settle();
    expect(page['compareFrames']().map(photo => photo.path)).toEqual(['/b.jpg', '/a.jpg']);
    expect(dom().querySelectorAll('app-synced-zoom')).toHaveLength(2);
    expect(dom().querySelector('[aria-label*="culling.lightbox.keep"]')).toBeNull();
    expect(dom().querySelector('[aria-label*="culling.lightbox.reject"]')).toBeNull();
    expect(dom().textContent).not.toContain('culling.lightbox.undecided');
    expect(http.match(() => true)).toEqual([]);
  });

  it('uses the proposed cover for grid S and the focused cover for lightbox Enter, with no cull writes', async () => {
    await enter(); batch(); await settle(); key('s');
    const create = http.expectOne('/api/stacks');
    expect(create.request.body).toEqual({ paths: ['/b.jpg', '/a.jpg'], cover_path: '/a.jpg' });
    create.flush({ undo: { entry_id: 23 } });
    await vi.waitFor(() => expect(cull.groups().map(item => item.group_id)).toEqual([2]));
    key('Enter'); await settle(); key('ArrowRight'); key('Enter');
    const focused = http.expectOne('/api/stacks');
    expect(focused.request.body).toEqual({ paths: ['/d.jpg', '/c.jpg'], cover_path: '/c.jpg' });
    focused.flush({}, { status: 500, statusText: 'failed' });
    await settle();
    expect(cull.groups()).toHaveLength(1);
    expect(page['lightboxGroup']()?.group_id).toBe(2);
  });

  it('makes Space and Shift+Space inert, opens on grid Enter and skips the open group with X', async () => {
    await enter(); batch(); await settle(); key(' '); key(' ', true); await settle();
    expect(cull.selectionsMap().size).toBe(0); expect(commands).toHaveLength(0);
    key('Enter'); await settle(); expect(page['lightboxGroup']()?.group_id).toBe(1);
    key('ArrowRight'); key('x');
    const request = http.expectOne('/api/stacks/suggestions/dismissals');
    expect(request.request.body).toEqual({ kind: 'duplicate', paths: ['/b.jpg', '/a.jpg'] });
    request.flush(null); await settle();
    await vi.waitFor(() => expect(page['lightboxGroup']()?.group_id).toBe(2));
    expect(http.match('/api/stacks/suggestions')).toHaveLength(0);
  });

  it('routes real secondary-dialog close results and captures Undo before Material clears componentInstance', async () => {
    await enter(); batch(); await settle();
    const captured = cull.groups()[1];
    page['selectedGroupIndex'].set(1);
    const opening = page['editSuggestion'](captured);
    await settle();
    const dialog = TestBed.inject(MatDialog);
    await vi.waitFor(() => expect(dialog.openDialogs).toHaveLength(1));
    const ref = dialog.openDialogs[0];
    const data = ref.componentInstance.data;
    expect(data.paths).toEqual(['/d.jpg', '/c.jpg']);
    expect(data.activePath).toBe('/d.jpg'); expect(data.skippable).toBe(true);
    const editor = ref.componentInstance as StackDialogComponent;
    const members = http.expectOne('/api/photos/by_paths');
    members.flush({ photos: ['/d.jpg', '/c.jpg'].map(path => ({ path, filename: path.slice(1), date_taken: null })), missing: [] });
    await settle();
    const saving = editor.save();
    http.expectOne('/api/stacks').flush({ undo: { entry_id: 24 } });
    await saving; await opening; await settle();
    expect(ref.componentInstance).toBeNull();
    expect(cull.groups().map(item => item.group_id)).toEqual([1]);
    const undoing = commands[0].undo();
    http.expectOne('/api/organization_history/24/revert').flush({});
    await undoing; await settle();
    expect(cull.groups().map(item => item.group_id).sort()).toEqual([1, 2]);
    cull.completeStackSuggestion(captured);
    identity.set('other'); data.onUndone();
    expect(cull.groups().filter(item => item.group_id === 2)).toHaveLength(0);
    await settle();
    for (const request of http.match(() => true)) request.flush(request.request.url.includes('/culling-groups')
      ? { groups: [], total_groups: 0, page: 1, per_page: 20, total_pages: 1 } : {});
    await settle();
  });

  it('uses the real Edit members Skip control on the captured second group', async () => {
    await enter(); batch(); await settle();
    const captured = cull.groups()[1];
    const opening = page['editSuggestion'](captured); await settle();
    const dialog = TestBed.inject(MatDialog);
    await vi.waitFor(() => expect(dialog.openDialogs).toHaveLength(1));
    const ref = dialog.openDialogs[0];
    http.expectOne('/api/photos/by_paths').flush({ photos: ['/d.jpg', '/c.jpg'].map(path => ({ path, filename: path.slice(1) })), missing: [] });
    await settle();
    const remove = document.querySelector('[data-stack-remove="/c.jpg"]') as HTMLButtonElement;
    remove.click(); await settle();
    const skip = [...document.querySelectorAll('mat-dialog-container button')].find(button => button.textContent?.trim() === 'stacks.suggestion_skip_group') as HTMLButtonElement;
    expect(skip).toBeDefined(); skip.click();
    await vi.waitFor(() => expect(ref.componentInstance).toBeNull());
    const dismissal = http.expectOne('/api/stacks/suggestions/dismissals');
    expect(dismissal.request.body.paths).toEqual(['/d.jpg', '/c.jpg']); dismissal.flush(null);
    await opening; await settle(); expect(cull.groups().map(item => item.group_id)).toEqual([1]);
    expect(http.match('/api/stacks/suggestions')).toHaveLength(0);
  });

  it.each(['identity', 'edition'])('closes the captured editor and clears private stack data on %s change', async reason => {
    await enter(); batch(); await settle();
    const captured = cull.groups()[0]; const opening = page['editSuggestion'](captured); await settle();
    await vi.waitFor(() => expect(TestBed.inject(MatDialog).openDialogs).toHaveLength(1));
    const ref = TestBed.inject(MatDialog).openDialogs[0];
    const callback = ref.componentInstance.data.onUndone;
    const photos = http.expectOne('/api/photos/by_paths');
    if (reason === 'identity') identity.set('other'); else edition.set(false);
    // Direct liveness checks must reject before the auth effect runs.
    photos.flush({ photos: captured.photos, missing: [] }); callback();
    await settle(); await opening;
    for (const request of http.match(() => true)) request.flush(request.request.url.includes('/culling-groups')
      ? { groups: [], total_groups: 0, page: 1, per_page: 20, total_pages: 1 } : {});
    await settle();
    expect(cull.mode()).toBe('cull'); expect(cull.groups()).toHaveLength(0);
    expect(page['lightboxGroupId']()).toBeNull(); expect(TestBed.inject(MatDialog).openDialogs).toHaveLength(0);
    callback(); expect(cull.groups()).toHaveLength(0);
    expect(dom().textContent).not.toContain('b.jpg');
    expect(dom().querySelector('[data-testid="stack-scope-notice"]')).not.toBeNull();
  });

  it('refuses a late stack completion after real navigation without reopening private photos', async () => {
    await enter(); batch(); await settle();
    const group = cull.groups()[0]; page['openLightbox'](group, 1);
    const stacking = page['stackGroup'](group);
    const write = http.expectOne('/api/stacks');
    await harness.navigateByUrl('/'); write.flush({ undo: { entry_id: 42 } }); await stacking;
    expect(commands).toHaveLength(0); expect(page['lightboxGroupId']()).toBeNull();
    expect(cull.groups()).toHaveLength(0);
  });

  it.each(['null', '[]', '{bad', '{"album_id":42}'])('falls back safely on malformed filter payload %s', async scope => {
    await enter(url(origin, scope));
    expect(http.match('/api/stacks/suggestions')).toHaveLength(0);
    for (const request of http.match(() => true)) request.flush(request.request.url.includes('/culling-groups')
      ? { groups: [], total_groups: 0, page: 1, per_page: 20, total_pages: 1 } : {});
    await settle(); expect(cull.mode()).toBe('cull');
    expect(dom().querySelector('[data-testid="stack-scope-notice"]')).not.toBeNull();
  });

  it.each([422, 500])('handles HTTP %s as invalid scope or a retryable stack failure', async status => {
    await enter();
    http.expectOne('/api/stacks/suggestions').flush({}, { status, statusText: 'failed' });
    await settle();
    if (status === 500) {
      expect(cull.mode()).toBe('stacks');
      cull.resetForReload(); batch(); await settle(); expect(cull.groups()).toHaveLength(2);
    } else {
      expect(cull.mode()).toBe('cull');
      expect(dom().querySelector('[data-testid="stack-scope-notice"]')).not.toBeNull();
      for (const request of http.match(() => true)) request.flush(request.request.url.includes('/culling-groups')
        ? { groups: [], total_groups: 0, page: 1, per_page: 20, total_pages: 1 } : {});
      await settle();
    }
  });
});
