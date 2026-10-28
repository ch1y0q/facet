import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { NavigationStart, Router } from '@angular/router';
import { NEVER, Subject } from 'rxjs';
import { I18nService } from '../../core/services/i18n.service';
import { AuthService } from '../../core/services/auth.service';
import { UndoService } from '../../core/services/undo.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { GalleryStore } from './gallery.store';
import { StackDialogComponent, StackDialogData } from './stack-dialog.component';

const stack = { id: 's1', revision: 7, cover_path: '/a.jpg', editable: true,
  members: [{ path: '/b.jpg', position: 0 }, { path: '/a.jpg', position: 1 }] };

describe('StackDialog HTTP workflow', () => {
  let component: StackDialogComponent;
  let http: HttpTestingController;
  let identity: ReturnType<typeof signal<string>>;
  let events: Subject<unknown>;
  let close: ReturnType<typeof vi.fn>;
  let register: ReturnType<typeof vi.fn>;
  let journal: ReturnType<typeof vi.fn>;
  let refresh: ReturnType<typeof vi.fn>;
  function create(data: StackDialogData = { stackId: 's1', selectedPaths: ['/c.jpg'] }) {
    identity = signal('alice'); events = new Subject(); close = vi.fn(); register = vi.fn(); journal = vi.fn(); refresh = vi.fn(async () => undefined);
    TestBed.configureTestingModule({ providers: [StackDialogComponent,
      provideHttpClient(withXhr()), provideHttpClientTesting(),
      { provide: MAT_DIALOG_DATA, useValue: data },
      { provide: I18nService, useValue: { translations: signal({}), t: (key: string) => key } },
      { provide: MatDialogRef, useValue: { close, beforeClosed: () => NEVER } },
      { provide: Router, useValue: { url: '/gallery', events, navigate: vi.fn() } },
      { provide: AuthService, useValue: { identity, isEdition: signal(true) } },
      { provide: GalleryStore, useValue: { pinnedPaths: signal(null), refreshPaths: refresh, restoreSelection: vi.fn(), showPaths: vi.fn(async () => []), loadError: signal(false), photos: signal(stack.members.map(m => ({ path: m.path }))) } },
      { provide: UndoService, useValue: { register } },
      { provide: UserActivityJournal, useValue: { record: journal } },
    ] });
    component = TestBed.inject(StackDialogComponent); http = TestBed.inject(HttpTestingController);
  }
  async function load() {
    const done = component.load();
    http.expectOne('/api/stacks/s1').flush(stack); await done;
  }
  afterEach(() => { http.verify({ ignoreCancelled: true }); TestBed.resetTestingModule(); });

  it('renders compact filenames with full-path tooltips, accessible names and unchanged thumbnail identities', async () => {
    create();
    const paths = ['/a/very/long/directory/same.jpg', '/another/long/directory/same.jpg'];
    const fixture = TestBed.createComponent(StackDialogComponent); fixture.detectChanges();
    http.expectOne('/api/stacks/s1').flush({ ...stack, cover_path: paths[0], members: paths.map((path, position) => ({ path, position })) });
    await fixture.whenStable(); fixture.detectChanges();
    const labels = [...(fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>('[data-stack-filename]')];
    expect(labels.map(label => label.textContent?.trim())).toEqual(['same.jpg', 'same.jpg']);
    expect(labels.map(label => label.title)).toEqual(paths);
    expect(labels.map(label => label.getAttribute('aria-label'))).toEqual(paths);
    const images = [...(fixture.nativeElement as HTMLElement).querySelectorAll<HTMLImageElement>('img')];
    expect(images.map(image => new URL(image.src).searchParams.get('path'))).toEqual(paths);
    expect(labels.every(label => label.classList.contains('truncate'))).toBe(true);
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-stack-member-count]')?.textContent?.trim()).toBe('stacks.member_count_plural');
    fixture.componentInstance.paths.set([paths[0]]); fixture.detectChanges();
    expect((fixture.nativeElement as HTMLElement).querySelector('[data-stack-member-count]')?.textContent?.trim()).toBe('stacks.member_count');
    fixture.destroy();
  });

  it('reviews chronological initial order separately from the selected cover and writes explicit paths', async () => {
    create({ paths: ['/a.jpg', '/b.jpg'], activePath: '/a.jpg' });
    const loading = component.load();
    http.expectOne('/api/photos/by_paths').flush({ photos: [
      { path: '/a.jpg', date_taken: '2025-02-02', filename: 'a.jpg' },
      { path: '/b.jpg', date_taken: '2025-01-01', filename: 'b.jpg' },
    ], missing: [], total: 2 }); await loading;
    expect(component.paths()).toEqual(['/b.jpg', '/a.jpg']);
    expect(component.cover()).toBe('/a.jpg');
    const saving = component.save();
    const req = http.expectOne('/api/stacks');
    expect(req.request.body).toEqual({ paths: ['/b.jpg', '/a.jpg'], cover_path: '/a.jpg' });
    req.flush({ stack, undo: { entry_id: 9 } }); await saving;
    expect(register).toHaveBeenCalled(); expect(journal).toHaveBeenCalledWith('stack', ['/b.jpg', '/a.jpg'], 'create');
  });
  it('orders equivalent EXIF and ISO capture dates together and leaves missing dates last', async () => {
    create({ paths: ['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg'], activePath: '/b.jpg' });
    const loading = component.load();
    http.expectOne('/api/photos/by_paths').flush({ photos: [
      { path: '/a.jpg', date_taken: '2025:01:01 10:00:00' },
      { path: '/b.jpg', date_taken: '2025-12-01T10:00:00' },
      { path: '/c.jpg', date_taken: '2025-01-01 10:00:01' },
      { path: '/d.jpg', date_taken: null },
    ], missing: [] });
    await loading;
    expect(component.paths()).toEqual(['/a.jpg', '/c.jpg', '/b.jpg', '/d.jpg']);
    expect(component.cover()).toBe('/b.jpg');
    const saving = component.save();
    const request = http.expectOne('/api/stacks');
    expect(request.request.body.paths).toEqual(['/a.jpg', '/c.jpg', '/b.jpg', '/d.jpg']);
    request.flush({ stack, undo: null });
    await saving;
  });
  it('edits order, cover and selected additions with the loaded revision', async () => {
    create(); await load(); component.addSelected(); component.move(2, -1); component.setCover('/c.jpg');
    const saving = component.save();
    const req = http.expectOne('/api/stacks/s1');
    expect(req.request.method).toBe('PUT');
    expect(req.request.body).toEqual({ paths: ['/b.jpg', '/c.jpg', '/a.jpg'], cover_path: '/c.jpg', expected_revision: 7 });
    req.flush({ stack: { ...stack, revision: 8 }, undo: { entry_id: 10 } }); await saving;
    const undo = register.mock.calls[0][0].undo();
    http.expectOne('/api/organization_history/10/revert').flush({ changed: 3 }); await undo;
    expect(refresh).toHaveBeenCalledTimes(2);
  });
  it('removes without deleting photos and preserves the earliest surviving cover', async () => {
    create(); await load(); component.remove('/a.jpg');
    expect(component.paths()).toEqual(['/b.jpg']); expect(component.cover()).toBe('/b.jpg');
    const saving = component.save();
    const req = http.expectOne('/api/stacks/s1'); expect(req.request.method).toBe('PUT');
    req.flush({ stack: null, undo: { entry_id: 2 } }); await saving; expect(close).toHaveBeenCalled();
    http.expectNone(request => /delete|reject/.test(request.url));
  });
  it('can save a draft with no members to dissolve without an invalid empty cover', async () => {
    create(); await load(); component.remove('/a.jpg'); component.remove('/b.jpg');
    const saving = component.save();
    const request = http.expectOne('/api/stacks/s1');
    expect(request.request.body).toEqual({ paths: [], cover_path: null, expected_revision: 7 });
    request.flush({ stack: null, undo: { entry_id: 3 } }); await saving;
    expect(close).toHaveBeenCalled();
  });
  it('unstack uses the revision query parameter and offers organization Undo', async () => {
    create(); await load(); const saving = component.unstack();
    const req = http.expectOne('/api/stacks/s1?expected_revision=7'); expect(req.request.method).toBe('DELETE');
    req.flush({ stack: null, undo: { entry_id: 12 } }); await saving;
    expect(register).toHaveBeenCalled();
  });
  it('retains the draft after a conflict until an explicit reload', async () => {
    create(); await load(); component.setCover('/b.jpg');
    const saving = component.save();
    http.expectOne('/api/stacks/s1').flush({}, { status: 409, statusText: 'Conflict' }); await saving;
    expect(component.error()).toBe('conflict'); expect(component.cover()).toBe('/b.jpg'); expect(close).not.toHaveBeenCalled();
    await load(); expect(component.cover()).toBe('/a.jpg');
  });
  it.each(['identity', 'navigation'])('ignores successful writes after %s changes', async change => {
    create(); await load(); component.setCover('/b.jpg'); const saving = component.save();
    if (change === 'identity') identity.set('bob'); else events.next(new NavigationStart(1, '/albums'));
    http.expectOne('/api/stacks/s1').flush({ stack, undo: { entry_id: 13 } }); await saving;
    expect(register).not.toHaveBeenCalled(); expect(journal).not.toHaveBeenCalled(); expect(refresh).not.toHaveBeenCalled();
  });
  it('opens a member without replacing the source gallery or installing a pinned list', async () => {
    create(); await load();
    const opening = component.openMember('/a.jpg');
    const photo = { path: '/a.jpg' };
    http.expectOne(request => request.url === '/api/photo').flush(photo); await opening;
    expect(TestBed.inject(GalleryStore).showPaths).not.toHaveBeenCalled();
    expect(TestBed.inject(Router).navigate).toHaveBeenCalledWith(['/photo'], { queryParams: { path: '/a.jpg' }, state: { photo }, replaceUrl: false });
  });
  it('opens a newly added draft member without saving or changing gallery scope', async () => {
    create(); await load(); component.addSelected();
    const opening = component.openMember('/c.jpg');
    const photo = { path: '/c.jpg' };
    http.expectOne(request => request.url === '/api/photo').flush(photo); await opening;
    expect(TestBed.inject(GalleryStore).showPaths).not.toHaveBeenCalled();
    expect(TestBed.inject(Router).navigate).toHaveBeenCalledWith(['/photo'], { queryParams: { path: '/c.jpg' }, state: { photo }, replaceUrl: false });
    http.expectNone(request => request.method === 'PUT');
  });
  it('does not open a member outside an existing exact pinned list', async () => {
    create(); await load(); TestBed.inject(GalleryStore).pinnedPaths.set(['/a.jpg']);
    await component.openMember('/b.jpg');
    http.expectNone(request => request.url === '/api/photo');
    expect(TestBed.inject(Router).navigate).not.toHaveBeenCalled();
  });
  it.each([null, ['/a.jpg', '/b.jpg']])('rechecks pin %j after reading an editor member', async initial => {
    create(); await load();
    const store = TestBed.inject(GalleryStore);
    store.pinnedPaths.set(initial);
    const opening = component.openMember('/a.jpg');
    store.pinnedPaths.set(['/b.jpg']);
    http.expectOne(request => request.url === '/api/photo').flush({ path: '/a.jpg' });
    await opening;
    expect(TestBed.inject(Router).navigate).not.toHaveBeenCalled();
    expect(store.pinnedPaths()).toEqual(['/b.jpg']);
    expect(close).not.toHaveBeenCalled();
  });
  it('permits an editor member retained by a changed exact pin', async () => {
    create(); await load();
    const opening = component.openMember('/a.jpg');
    TestBed.inject(GalleryStore).pinnedPaths.set(['/a.jpg']);
    http.expectOne(request => request.url === '/api/photo').flush({ path: '/a.jpg' });
    await opening;
    expect(TestBed.inject(Router).navigate).toHaveBeenCalled();
    expect(TestBed.inject(GalleryStore).pinnedPaths()).toEqual(['/a.jpg']);
  });
  it('refuses Undo after leaving and returning to the same route', async () => {
    create(); await load(); const saving = component.unstack();
    http.expectOne('/api/stacks/s1?expected_revision=7').flush({ stack: null, undo: { entry_id: 12 } }); await saving;
    events.next(new NavigationStart(1, '/albums')); events.next(new NavigationStart(2, '/gallery'));
    await expect(register.mock.calls[0][0].undo()).rejects.toThrow();
    http.expectNone('/api/organization_history/12/revert');
  });
  it('does not navigate to a member after an account change during its read', async () => {
    create(); await load();
    const opening = component.openMember('/a.jpg'); identity.set('bob');
    http.expectOne(request => request.url === '/api/photo').flush({ path: '/a.jpg' }); await opening;
    expect(TestBed.inject(Router).navigate).not.toHaveBeenCalled();
  });
  it('keeps failed writes retryable without losing the chosen cover', async () => {
    create(); await load(); component.setCover('/b.jpg');
    const failed = component.save();
    http.expectOne('/api/stacks/s1').flush({}, { status: 500, statusText: 'Failed' }); await failed;
    expect(component.error()).toBe('error'); expect(component.saving()).toBe(false);
    const retried = component.save();
    const request = http.expectOne('/api/stacks/s1'); expect(request.request.body.cover_path).toBe('/b.jpg');
    request.flush({ stack: { ...stack, revision: 8 }, undo: null }); await retried;
    expect(journal).toHaveBeenCalledTimes(1);
  });
  it('chunks initial photo metadata reads at the exact-list endpoint cap', async () => {
    const paths = Array.from({ length: 1000 }, (_, i) => `/photo-${i}.jpg`);
    create({ paths }); const loading = component.load();
    for (const offset of [0, 500]) {
      const request = http.expectOne('/api/photos/by_paths');
      expect(request.request.body.paths).toEqual(paths.slice(offset, offset + 500));
      request.flush({ photos: paths.slice(offset, offset + 500).map(path => ({ path, date_taken: null })), missing: [] });
      // Advancing the awaited HTTP continuation starts the next bounded request.
      await Promise.resolve();
    }
    await loading; expect(component.paths()).toHaveLength(1000);
    http.expectNone(request => request.url.startsWith('/image'));
  });
  it('ignores load completion immediately after identity changes, before an auth effect runs', async () => {
    create(); const loading = component.load(); identity.set('bob');
    http.expectOne('/api/stacks/s1').flush(stack); await loading;
    expect(component.paths()).toEqual([]); expect(component.ready()).toBe(false);
  });
  it('does not edit partially visible stacks but can explicitly select all permitted members', async () => {
    create(); const loading = component.load(); http.expectOne('/api/stacks/s1').flush({ ...stack, editable: false }); await loading;
    component.remove('/a.jpg'); component.setCover('/b.jpg'); await component.save(); await component.unstack();
    expect(component.paths()).toHaveLength(2); http.expectNone(request => request.method !== 'GET');
    component.selectMembers();
    expect(TestBed.inject(GalleryStore).restoreSelection).toHaveBeenCalledWith(['/b.jpg', '/a.jpg']);
  });
});
