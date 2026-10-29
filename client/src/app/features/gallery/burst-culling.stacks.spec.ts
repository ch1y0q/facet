import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideNativeDateAdapter } from '@angular/material/core';
import { Router, provideRouter } from '@angular/router';
import { RouterTestingHarness } from '@angular/router/testing';
import { MatDialog } from '@angular/material/dialog';
import { MatBottomSheet } from '@angular/material/bottom-sheet';
import { Subject } from 'rxjs';
import { BurstCullingComponent } from './burst-culling.component';
import { CullingStore } from './culling.store';
import { AuthService } from '../../core/services/auth.service';
import { GalleryStore } from './gallery.store';
import { I18nService } from '../../core/services/i18n.service';
import { AssistantChangeBatch, AssistantChangesService } from '../../core/agent/assistant-changes.service';
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
  let changes: Subject<AssistantChangeBatch>;
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
    localStorage.clear(); identity.set('owner'); edition.set(true); commands = []; changes = new Subject();
    TestBed.configureTestingModule({ providers: [
      provideHttpClient(), provideHttpClientTesting(), provideNativeDateAdapter(),
      provideRouter([{ path: 'culling', component: BurstCullingComponent },
        { path: 'blocked', component: GalleryDestination, canActivate: [() => false] },
        { path: 'load-failed', loadComponent: async () => { throw new Error('Chunk download failed'); } },
        { path: '', component: GalleryDestination }, { path: 'album/:id', component: GalleryDestination }]),
      { provide: AuthService, useValue: { identity, isEdition: edition } },
      { provide: GalleryStore, useValue: { config: () => null, refreshPaths: async () => undefined } },
      { provide: I18nService, useValue: { t: (key: string) => key, translations: () => ({}) } },
      { provide: AssistantChangesService, useValue: { batch$: changes } },
      { provide: UndoService, useValue: { register: (command: UndoableCommand) => commands.push(command) } },
    ] });
    http = TestBed.inject(HttpTestingController);
    harness = await RouterTestingHarness.create();
  });
  afterEach(() => { try { http.verify(); } finally { TestBed.resetTestingModule(); } });

  it('retains the stack-mode safety boundary after actual cancelled navigation', async () => {
    await enter(); batch(); await settle();
    const before = TestBed.inject(Router).url;
    expect(await TestBed.inject(Router).navigateByUrl('/blocked')).toBe(false);
    await settle();
    expect(TestBed.inject(Router).url).toBe(before);
    expect(cull.mode()).toBe('stacks');
    expect(dom().querySelector('[data-testid="stack-review-header"]')).not.toBeNull();
    expect(cull.cullWritesAllowed()).toBe(false); expect(cull.groups()).toHaveLength(0);
    batch(); await settle(); expect(cull.groups()).toHaveLength(2);
  });

  it.each(['ctrlKey', 'metaKey', 'altKey', 'isComposing'])('does not stack on header S with %s', async modifier => {
    await enter(); batch(); await settle(); key('Enter'); await settle();
    const control = dom().querySelector('button[aria-keyshortcuts="S"]')!;
    expect(control).not.toBeNull();
    control.dispatchEvent(new KeyboardEvent('keydown', { key: 's', [modifier]: true, bubbles: true, cancelable: true }));
    const writes = http.match('/api/stacks');
    for (const write of writes) write.flush({}, { status: 500, statusText: 'failed' });
    await settle();
    expect(writes).toHaveLength(0);
  });

  it('does not stack on a composing grid S', async () => {
    await enter(); batch(); await settle();
    document.dispatchEvent(new KeyboardEvent('keydown', { key: 's', isComposing: true, bubbles: true, cancelable: true }));
    const writes = http.match('/api/stacks');
    for (const write of writes) write.flush({}, { status: 500, statusText: 'failed' });
    await settle(); expect(writes).toHaveLength(0);
  });
  it.each(['dialog.cancel', 'slideshow.fullscreen'])('leaves native Enter for the %s button', async label => {
    await enter(); batch(); await settle(); key('Enter'); await settle();
    const button = dom().querySelector(`button[aria-label="${label}"]`)!;
    expect(button).not.toBeNull();
    const event = new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true });
    button.dispatchEvent(event);
    const writes = http.match('/api/stacks');
    for (const write of writes) write.flush({}, { status: 500, statusText: 'failed' });
    await settle();
    expect(writes).toHaveLength(0);
    expect(event.defaultPrevented).toBe(false);
    const space = new KeyboardEvent('keydown', { key: ' ', bubbles: true, cancelable: true });
    button.dispatchEvent(space); expect(space.defaultPrevented).toBe(false);
    const fullscreen = vi.fn().mockResolvedValue(undefined);
    Element.prototype.requestFullscreen = fullscreen;
    (button as HTMLButtonElement).click(); await settle();
    if (label === 'dialog.cancel') expect(page['lightboxGroupId']()).toBeNull();
    else expect(fullscreen).toHaveBeenCalledOnce();
    expect(http.match('/api/stacks')).toHaveLength(0);
  });

  it('keeps shortcut S inert while a bottom sheet covers the darkroom', async () => {
    await enter(); batch(); await settle();
    const ref = TestBed.inject(MatBottomSheet).open(GalleryDestination); await settle();
    const sheet = document.querySelector('mat-bottom-sheet-container')!; expect(sheet).not.toBeNull();
    try {
      sheet.dispatchEvent(new KeyboardEvent('keydown', { key: 's', bubbles: true, cancelable: true }));
      const writes = http.match('/api/stacks');
      for (const write of writes) write.flush({}, { status: 500, statusText: 'failed' });
      await settle(); expect(writes).toHaveLength(0);
    } finally { ref.dismiss(); await settle(); }
  });

  it('retains stack mode when destination lazy loading fails', async () => {
    await enter(); batch(); await settle();
    const before = TestBed.inject(Router).url;
    await expect(TestBed.inject(Router).navigateByUrl('/load-failed')).rejects.toThrow('Chunk download failed');
    await settle();
    expect(TestBed.inject(Router).url).toBe(before);
    expect(cull.mode()).toBe('stacks');
    expect(cull.cullWritesAllowed()).toBe(false); batch(); await settle();
  });

  describe('shared stack shortcut admission', () => {
    const invalidKeys: [string, KeyboardEventInit][] = [
      ['Ctrl', { ctrlKey: true }], ['Meta', { metaKey: true }], ['Alt', { altKey: true }],
      ['composition', { isComposing: true }], ['legacy composition', { keyCode: 229 }],
      ['repeat', { repeat: true }],
    ];
    it.each(['s', 'x'])('rejects modified/composing/repeated %s through the header and document paths', async action => {
      await enter(); batch(); await settle();
      for (const surface of ['grid', 'darkroom']) {
        if (surface === 'darkroom') { key('Enter'); await settle(); }
        for (const [, init] of invalidKeys) {
          const target = surface === 'grid' ? document : dom().querySelector('button[aria-keyshortcuts="S"]')!;
          target.dispatchEvent(new KeyboardEvent('keydown', { key: action, ...init, bubbles: true, cancelable: true }));
          // Reach the direct path as well as Angular's document modifier matcher.
          page[action === 's' ? 'onStackKey' : 'onSkipSuggestionKey'](new KeyboardEvent('keydown', { key: action, ...init }));
          const writes = http.match(request => request.method !== 'GET');
          for (const write of writes) write.flush({}, { status: 500, statusText: 'failed' });
          await settle(); expect(writes, surface + JSON.stringify(init)).toHaveLength(0);
        }
      }
    });

    it.each(['s', 'x', 'Enter'])('leaves typing %s alone on the document and inner darkroom paths', async action => {
      await enter(); batch(); await settle();
      const input = document.createElement('input'); dom().append(input);
      input.dispatchEvent(new KeyboardEvent('keydown', { key: action, bubbles: true, cancelable: true }));
      key('Enter'); await settle();
      dom().querySelector('button[aria-keyshortcuts="S"]')!.parentElement!.append(input);
      input.dispatchEvent(new KeyboardEvent('keydown', { key: action, bubbles: true, cancelable: true }));
      expect(http.match(request => request.method !== 'GET')).toHaveLength(0);
      expect(page['lightboxGroup']()?.group_id).toBe(1);
    });

    it.each(['dialog', 'bottom_sheet', 'slideshow'])('blocks S and X behind an active %s on both paths', async overlay => {
      await enter(); batch(); await settle(); key('Enter'); await settle();
      const close = overlay === 'dialog' ? (() => { const ref = TestBed.inject(MatDialog).open(GalleryDestination); return () => ref.close(); })()
        : overlay === 'bottom_sheet' ? (() => { const ref = TestBed.inject(MatBottomSheet).open(GalleryDestination); return () => ref.dismiss(); })()
          : TestBed.inject(PageContextService).registerOverlay('slideshow');
      await settle();
      for (const action of ['s', 'x']) {
        document.dispatchEvent(new KeyboardEvent('keydown', { key: action, bubbles: true, cancelable: true }));
        dom().querySelector('button[aria-keyshortcuts="S"]')!.dispatchEvent(new KeyboardEvent('keydown', { key: action, bubbles: true, cancelable: true }));
      }
      const writes = http.match(request => request.method !== 'GET');
      for (const write of writes) write.flush({}, { status: 500, statusText: 'failed' });
      close(); await settle(); expect(writes).toHaveLength(0);
      expect(cull.groups()).toHaveLength(2);
    });
  });

  it('keeps unmodified inner-header S and X actionable after shortcut admission', async () => {
    await enter(); batch(); await settle(); key('Enter'); await settle();
    const header = dom().querySelector('button[aria-keyshortcuts="S"]')!;
    header.dispatchEvent(new KeyboardEvent('keydown', { key: 's', bubbles: true, cancelable: true }));
    const create = http.expectOne('/api/stacks');
    expect(create.request.body).toEqual({ paths: ['/b.jpg', '/a.jpg'], cover_path: '/b.jpg' });
    create.flush({}, { status: 500, statusText: 'failed' }); await settle();
    expect(page['lightboxGroup']()?.group_id).toBe(1);
    header.dispatchEvent(new KeyboardEvent('keydown', { key: 'x', bubbles: true, cancelable: true }));
    http.expectOne('/api/stacks/suggestions/dismissals').flush(null);
    await vi.waitFor(() => expect(page['lightboxGroup']()?.group_id).toBe(2));
    expect(http.match(() => true)).toHaveLength(0);
  });

  it('stacks the focused photo with plain Enter from the real darkroom pane', async () => {
    await enter(); batch(); await settle(); key('Enter'); await settle();
    (dom().querySelectorAll('[data-stack-filmstrip] button')[1] as HTMLButtonElement).click(); await settle();
    dom().querySelector('app-synced-zoom')!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter', bubbles: true, cancelable: true }));
    const create = http.expectOne('/api/stacks');
    expect(create.request.body).toEqual({ paths: ['/b.jpg', '/a.jpg'], cover_path: '/a.jpg' });
    create.flush({}, { status: 500, statusText: 'failed' }); await settle();
    expect(cull.groups()).toHaveLength(2);
  });

  describe('interrupted stack navigation', () => {
    function delayedNavigation() {
      const router = TestBed.inject(Router);
      const answer = new Subject<boolean>();
      let start!: () => void;
      const started = new Promise<void>(resolve => { start = resolve; });
      router.resetConfig([...router.config, { path: 'delayed', component: GalleryDestination,
        canActivate: [() => { start(); return answer; }] }]);
      return { answer, started, navigating: router.navigateByUrl('/delayed') };
    }

    it('clears private rows while a guard waits, expires old decisions/editor/Undo, and recovers a usable fresh visit', async () => {
      await enter(); batch(); await settle();
      const router = TestBed.inject(Router); const before = router.url;
      const oldFirst = cull.groups()[0];
      const stacking = page['stackGroup'](oldFirst);
      http.expectOne('/api/stacks').flush({ undo: { entry_id: 50 } }); await stacking;
      expect(commands).toHaveLength(1);
      const oldUndo = commands[0]; const oldSecond = cull.groups()[0];
      const skipping = page['skipStackSuggestion'](oldSecond);
      const oldWrite = http.expectOne('/api/stacks/suggestions/dismissals');
      const editing = page['editSuggestion'](oldSecond); await settle();
      await vi.waitFor(() => expect(TestBed.inject(MatDialog).openDialogs).toHaveLength(1));
      const ref = TestBed.inject(MatDialog).openDialogs[0];
      const oldEditorUndo = ref.componentInstance.editor().data.onUndone;
      http.expectOne('/api/photos/by_paths').flush({ photos: oldSecond.photos, missing: [] }); await settle();
      page['openLightbox'](oldSecond, 0);
      const navigation = delayedNavigation(); await navigation.started; await settle();
      expect(cull.mode()).toBe('stacks'); expect(cull.cullWritesAllowed()).toBe(false);
      expect(cull.groups()).toHaveLength(0); expect(page['lightboxGroupId']()).toBeNull();
      expect(dom().querySelector('[data-pidx]')).toBeNull();
      expect(dom().querySelector('app-synced-zoom')).toBeNull();
      await editing; expect(TestBed.inject(MatDialog).openDialogs).toHaveLength(0);
      expect(http.match('/api/stacks/suggestions')).toHaveLength(0);
      navigation.answer.next(false); navigation.answer.complete(); expect(await navigation.navigating).toBe(false);
      expect(router.url).toBe(before); expect(cull.groups()).toHaveLength(0);
      const fresh = http.expectOne('/api/stacks/suggestions'); expect(fresh.request.body).toEqual({ filters, include_photos: true });
      oldWrite.flush(null); await skipping; oldEditorUndo();
      await expect(oldUndo.undo()).rejects.toThrow('Stack session expired');
      expect(http.match('/api/organization_history/50/revert')).toHaveLength(0);
      expect(commands).toHaveLength(1); expect(cull.groups()).toHaveLength(0);
      fresh.flush({ suggestions: [response.suggestions[1]] }); await settle();
      expect(cull.groups()[0]).not.toBe(oldSecond);
      expect(TestBed.inject(PageContextService).snapshot()).toEqual({ id: 'culling', mode: 'stacks' });
      const freshDecision = page['stackGroup'](cull.groups()[0]);
      http.expectOne('/api/stacks').flush({ undo: { entry_id: 51 } }); await freshDecision;
      http.expectOne('/api/stacks/suggestions').flush({ suggestions: [] }); await settle();
      expect(commands).toHaveLength(2);
    });

    it('keeps failed recovery empty and in stacks, with the real Reload action retrying only its captured scope', async () => {
      await enter(); batch(); await settle();
      expect(await TestBed.inject(Router).navigateByUrl('/blocked')).toBe(false);
      http.expectOne('/api/stacks/suggestions').flush({}, { status: 500, statusText: 'failed' }); await settle();
      expect(cull.mode()).toBe('stacks'); expect(cull.cullWritesAllowed()).toBe(false);
      expect(dom().querySelector('[data-pidx]')).toBeNull();
      expect(dom().querySelector('[aria-label^="culling.confirm"]')).toBeNull();
      const reload = [...dom().querySelectorAll('button')].find(button => button.textContent?.trim() === 'stacks.suggestions_reload') as HTMLButtonElement;
      expect(reload).toBeDefined(); reload.click(); batch(); await settle();
      expect(cull.groups()).toHaveLength(2); expect(http.match(() => true)).toHaveLength(0);
    });

    it.each(['blocked', 'same'])('recovers once after a guard redirect to %s', async target => {
      await enter(); batch(); await settle(); const router = TestBed.inject(Router); const before = router.url;
      router.resetConfig([...router.config, { path: 'redirected', component: GalleryDestination,
        canActivate: [() => router.parseUrl(target === 'same' ? before : '/blocked')] }]);
      expect(await router.navigateByUrl('/redirected')).toBe(target === 'same');
      expect(router.url).toBe(before); expect(cull.mode()).toBe('stacks');
      batch(); await settle(); expect(http.match(() => true)).toHaveLength(0);
    });

    it('waits for a superseding navigation before recovering once', async () => {
      await enter(); batch(); await settle();
      const navigation = delayedNavigation(); await navigation.started;
      expect(await TestBed.inject(Router).navigateByUrl('/blocked')).toBe(false);
      expect(await navigation.navigating).toBe(false);
      batch(); await settle(); expect(cull.mode()).toBe('stacks');
      expect(http.match(() => true)).toHaveLength(0);
    });

    it('reuses the component on a completed normal culling navigation and initializes that feed', async () => {
      await enter(); batch(); await settle();
      expect(await TestBed.inject(Router).navigateByUrl('/culling')).toBe(true); await settle();
      expect(harness.routeDebugElement!.componentInstance).toBe(page);
      expect(cull.mode()).toBe('cull'); expect(cull.cullWritesAllowed()).toBe(true);
      expect(TestBed.inject(PageContextService).snapshot()).toEqual({ id: 'culling', mode: 'cull' });
      expect(dom().querySelector('[data-testid="stack-review-header"]')).toBeNull();
      expect(http.match('/api/stacks/suggestions')).toHaveLength(0);
      const reads = http.match(() => true); expect(reads.some(request => request.request.url === '/api/culling-groups')).toBe(true);
      for (const request of reads) request.flush(request.request.url.includes('/culling-groups')
        ? { groups: [], total_groups: 0, page: 1, per_page: 20, total_pages: 1 } : {});
      await settle();
    });

    it('revalidates a changed scope and return URL on a completed same-component stack navigation', async () => {
      await enter(); batch(); await settle(); const router = TestBed.inject(Router);
      const nextFilters = { album_id: '43', camera: 'Another camera' }; const nextOrigin = '/album/43?camera=other#new';
      expect(await router.navigateByUrl(url(nextOrigin, JSON.stringify(nextFilters)))).toBe(true);
      expect(harness.routeDebugElement!.componentInstance).toBe(page);
      expect(cull.mode()).toBe('stacks'); expect(cull.groups()).toHaveLength(0);
      const request = http.expectOne('/api/stacks/suggestions');
      expect(request.request.body).toEqual({ filters: nextFilters, include_photos: true });
      request.flush(response); await settle(); expect(http.match(() => true)).toHaveLength(0);
      page['backToGallery'](); await settle(); await vi.waitFor(() => expect(router.url).toBe(nextOrigin));
    });
  });

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

  it.each(['stack', 'skip'])('advances the actual darkroom after %s and a subscribed assistant mark refresh', async action => {
    await enter(); batch(); await settle(); key('Enter'); await settle();
    key(action === 'stack' ? 's' : 'x');
    const write = http.expectOne(action === 'stack' ? '/api/stacks' : '/api/stacks/suggestions/dismissals');
    changes.next({ paths: ['/a.jpg'], count: 1 }); await settle();
    http.expectOne('/api/photos/by_paths').flush({ photos: [{ path: '/a.jpg', star_rating: 4, is_favorite: 1 }] });
    await settle();
    expect(cull.groups()[0].photos[1].star_rating).toBe(4);
    write.flush(action === 'stack' ? { undo: { entry_id: 90 } } : null);
    await vi.waitFor(() => expect(cull.groups().map(item => item.group_id)).toEqual([2]));
    await settle(); expect(page['lightboxGroup']()?.group_id).toBe(2); expect(commands).toHaveLength(1);
    const undoing = commands[0].undo();
    http.expectOne(action === 'stack' ? '/api/organization_history/90/revert' : '/api/stacks/suggestions/dismissals/membership-1').flush({});
    await undoing; await settle();
    expect(cull.groups().map(item => item.group_id)).toEqual([1, 2]);
    expect(cull.groups()[0].photos[1].star_rating).toBe(4);
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
    const data = ref.componentInstance.editor().data;
    expect(data.paths).toEqual(['/d.jpg', '/c.jpg']);
    expect(data.activePath).toBe('/d.jpg'); expect(data.skippable).toBe(true);
    const members = http.expectOne('/api/photos/by_paths');
    members.flush({ photos: ['/d.jpg', '/c.jpg'].map(path => ({ path, filename: path.slice(1), date_taken: null })), missing: [] });
    await settle();
    const save = document.querySelector('mat-dialog-container [data-stack-save]') as HTMLButtonElement;
    expect(save).toBeDefined(); save.click();
    const write = http.expectOne('/api/stacks');
    changes.next({ paths: ['/d.jpg'], count: 1 }); await settle();
    http.expectOne('/api/photos/by_paths').flush({ photos: [{ path: '/d.jpg', star_rating: 5, is_favorite: 1 }] });
    await settle();
    expect(cull.groups()[1]).not.toBe(captured);
    write.flush({ undo: { entry_id: 24 } });
    await opening; await settle();
    expect(ref.componentInstance).toBeNull();
    expect(cull.groups().map(item => item.group_id)).toEqual([1]);
    const undoing = commands[0].undo();
    http.expectOne('/api/organization_history/24/revert').flush({});
    await undoing; await settle();
    expect(cull.groups().map(item => item.group_id).sort()).toEqual([1, 2]);
    expect(cull.groups().find(item => item.group_id === 2)?.photos[0].star_rating).toBe(5);
    expect(commands).toHaveLength(1);
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
    const callback = ref.componentInstance.editor().data.onUndone;
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
