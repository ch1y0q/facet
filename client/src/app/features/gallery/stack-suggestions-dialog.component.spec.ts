import { ComponentFixture, TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialog, MatDialogRef } from '@angular/material/dialog';
import { Subject } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { UndoService, UndoableCommand } from '../../core/services/undo.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from './gallery.store';
import { SKIP_SUGGESTION, StackDialogComponent } from './stack-dialog.component';
import { StackSuggestionsDialogComponent } from './stack-suggestions-dialog.component';
import { components } from '../../core/api/schema';

type Suggestion = components['schemas']['StackSuggestion'];
const candidate: Suggestion = { key: 'a'.repeat(64), kind: 'duplicate', paths: ['/a.jpg', '/b.jpg'], cover_path: '/b.jpg' };
const second: Suggestion = { key: 'b'.repeat(64), kind: 'burst', paths: ['/c.jpg', '/d.jpg', '/e.jpg'], cover_path: '/c.jpg' };

describe('suggested stack review through HTTP and router', () => {
  let fixture: ComponentFixture<StackSuggestionsDialogComponent>;
  let http: HttpTestingController;
  let owner: ReturnType<typeof signal<string>>;
  let edition: ReturnType<typeof signal<boolean>>;
  let filters: ReturnType<typeof signal<Record<string, string>>>;
  let close: ReturnType<typeof vi.fn>;
  let open: ReturnType<typeof vi.fn>;
  let reviewed: Subject<unknown>;
  let register: ReturnType<typeof vi.fn>;
  let keys: Subject<KeyboardEvent>;
  let refresh: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    owner = signal('alice'); edition = signal(true); filters = signal({ path_prefix: '/photos' });
    const beforeClosed = new Subject<void>(); reviewed = new Subject<unknown>(); register = vi.fn(); keys = new Subject<KeyboardEvent>(); refresh = vi.fn(async () => undefined);
    close = vi.fn(() => beforeClosed.next()); open = vi.fn(() => ({ afterClosed: () => reviewed, close: vi.fn(() => { reviewed.next(false); reviewed.complete(); }) }));
    TestBed.configureTestingModule({
      imports: [StackSuggestionsDialogComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting(),
        { provide: AuthService, useValue: { identity: owner, isEdition: edition } },
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
        { provide: GalleryStore, useValue: { filters, pinnedPaths: signal(null), filterPayload: filters, refreshPaths: refresh } },
        { provide: MatDialog, useValue: { open } },
        { provide: UndoService, useValue: { register } },
        { provide: MatDialogRef, useValue: { close, beforeClosed: () => beforeClosed, keydownEvents: () => keys } },
        { provide: MAT_DIALOG_DATA, useValue: { filters: { path_prefix: '/photos' } } },
      ],
    });
    TestBed.overrideProvider(MatDialog, { useValue: { open } });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(StackSuggestionsDialogComponent); fixture.detectChanges();
  });
  afterEach(() => {
    try { fixture?.destroy(); http?.verify(); } finally { TestBed.resetTestingModule(); vi.restoreAllMocks(); }
  });

  async function loaded(suggestions: Suggestion[] = [candidate]) {
    const request = http.expectOne('/api/stacks/suggestions');
    expect(request.request.body).toEqual({ filters: { path_prefix: '/photos' } });
    request.flush({ suggestions });
    await fixture.whenStable(); fixture.detectChanges();
  }

  /** Keys arrive through the dialog's own stream, wherever focus is. */
  function key(k: string, init: KeyboardEventInit = {}) {
    const event = new KeyboardEvent('keydown', { key: k, cancelable: true, ...init });
    keys.next(event);
    return event;
  }

  async function settle() { await fixture.whenStable(); fixture.detectChanges(); }

  it('shows one suggestion at a time with its proposed cover large and progress', async () => {
    await loaded([candidate, second]);
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('stacks.suggestion_progress');
    const pressed = fixture.nativeElement.querySelector('button[aria-pressed="true"] img') as HTMLImageElement;
    expect(new URL(pressed.src).searchParams.get('path')).toBe('/b.jpg');
    expect(fixture.nativeElement.querySelectorAll('button[aria-pressed] img')).toHaveLength(2);
    expect(fixture.componentInstance.focusedPath()).toBe('/b.jpg');
    http.expectNone('/api/stacks');
  });

  it('stacks with the focused frame as cover, advances, and Undo reverts and brings it back', async () => {
    await loaded([candidate, second]);
    expect(key('ArrowRight').defaultPrevented).toBe(true);
    expect(fixture.componentInstance.focusedPath()).toBe('/a.jpg');
    key('s');
    const create = http.expectOne('/api/stacks');
    expect(create.request.body).toEqual({ paths: ['/a.jpg', '/b.jpg'], cover_path: '/a.jpg' });
    create.flush({ stack: null, undo: { entry_id: 7 } });
    await vi.waitFor(() => expect(fixture.componentInstance.candidate()).toBe(second));
    expect(fixture.componentInstance.handled()).toBe(1);
    expect(fixture.componentInstance.focusedPath()).toBe('/c.jpg');
    expect(refresh).toHaveBeenCalledWith(null);
    const command = register.mock.calls[0][0] as UndoableCommand;
    expect(command.labelParams).toEqual({ count: 2 });
    const undone = command.undo();
    http.expectOne('/api/organization_history/7/revert').flush({});
    await undone;
    expect(fixture.componentInstance.candidate()).toBe(candidate);
    expect(fixture.componentInstance.handled()).toBe(0);
  });

  it('skip persists the dismissal and Undo restores it', async () => {
    await loaded([candidate, second]);
    key('x');
    const dismiss = http.expectOne('/api/stacks/suggestions/dismissals');
    expect(dismiss.request.method).toBe('POST');
    expect(dismiss.request.body).toEqual({ kind: 'duplicate', paths: ['/a.jpg', '/b.jpg'] });
    dismiss.flush(null, { status: 204, statusText: 'No Content' });
    await vi.waitFor(() => expect(fixture.componentInstance.candidate()).toBe(second));
    const undone = (register.mock.calls[0][0] as UndoableCommand).undo();
    const restore = http.expectOne(`/api/stacks/suggestions/dismissals/${candidate.key}`);
    expect(restore.request.method).toBe('DELETE');
    restore.flush(null, { status: 204, statusText: 'No Content' });
    await undone;
    expect(fixture.componentInstance.candidate()).toBe(candidate);
  });

  it('keeps reviewing by keyboard after a decision, ignoring keys while one is in flight', async () => {
    await loaded([candidate, second]);
    key('S'); key('x');
    http.expectOne('/api/stacks').flush({ stack: null, undo: null });
    http.expectNone('/api/stacks/suggestions/dismissals');
    await vi.waitFor(() => expect(fixture.componentInstance.candidate()).toBe(second));
    key('ArrowLeft');
    expect(fixture.componentInstance.focusedPath()).toBe('/e.jpg');
    key('X');
    http.expectOne('/api/stacks/suggestions/dismissals').flush(null, { status: 204, statusText: 'No Content' });
    await vi.waitFor(() => expect(fixture.componentInstance.handled()).toBe(2));
  });

  it('refuses an Undo once the account has changed', async () => {
    await loaded([candidate, second]);
    key('x');
    http.expectOne('/api/stacks/suggestions/dismissals').flush(null, { status: 204, statusText: 'No Content' });
    await vi.waitFor(() => expect(register).toHaveBeenCalled());
    owner.set('bob');
    await expect((register.mock.calls[0][0] as UndoableCommand).undo()).rejects.toThrow();
    http.expectNone(`/api/stacks/suggestions/dismissals/${candidate.key}`);
  });

  it('keeps the suggestion and reports a failed stack', async () => {
    await loaded();
    void fixture.componentInstance.stack();
    http.expectOne('/api/stacks').flush({ detail: 'x' }, { status: 409, statusText: 'Conflict' });
    await vi.waitFor(() => expect(fixture.componentInstance.actionFailed()).toBe(true));
    await settle();
    expect(fixture.componentInstance.candidate()).toBe(candidate);
    expect(fixture.nativeElement.querySelector('[role="alert"]').textContent).toContain('stacks.suggestion_failed');
    expect(register).not.toHaveBeenCalled();
  });

  it('says the batch is done once every suggestion is handled', async () => {
    await loaded();
    void fixture.componentInstance.skip();
    http.expectOne('/api/stacks/suggestions/dismissals').flush(null, { status: 204, statusText: 'No Content' });
    await vi.waitFor(() => expect(fixture.componentInstance.candidate()).toBeNull());
    await settle();
    expect(fixture.nativeElement.textContent).toContain('stacks.suggestions_done');
  });

  it('makes no write for read-only accounts or a modified key', async () => {
    await loaded();
    for (const modifier of ['metaKey', 'ctrlKey', 'altKey']) expect(key('s', { [modifier]: true }).defaultPrevented).toBe(false);
    edition.set(false); fixture.detectChanges();
    key('s'); key('x');
    await settle();
    http.expectNone('/api/stacks');
    http.expectNone('/api/stacks/suggestions/dismissals');
    expect(fixture.componentInstance.candidate()).toBe(candidate);
  });

  it('refreshes only suggestion image URLs on successful load/reopen and keeps them stable on rerender', async () => {
    vi.spyOn(Date, 'now').mockReturnValue(42);
    await loaded();
    const images = () => [...fixture.nativeElement.querySelectorAll('button[aria-pressed] img')]
      .map((img: HTMLImageElement) => img.getAttribute('src')!);
    const first = images();
    expect(first).toHaveLength(2);
    for (const src of first) {
      const url = new URL(src, 'http://facet.test');
      expect(url.searchParams.get('ngsw-bypass')).toBeNull();
      expect(url.searchParams.get('preview')).toBe(fixture.componentInstance.previewToken());
    }
    fixture.detectChanges();
    expect(images()).toEqual(first);
    const reload = fixture.componentInstance.load(); await loaded(); await reload;
    const second = images();
    expect(second).not.toEqual(first);
    expect(second.map(src => new URL(src, 'http://facet.test').searchParams.get('path')))
      .toEqual(first.map(src => new URL(src, 'http://facet.test').searchParams.get('path')));
    fixture.destroy();
    fixture = TestBed.createComponent(StackSuggestionsDialogComponent); fixture.detectChanges();
    await loaded();
    expect(images()).not.toEqual(second);
    http.expectNone('/api/photos/by_paths');
    http.expectNone('/api/stacks');
  });

  it('zooms the preview and resets the zoom when the cover changes', async () => {
    await loaded();
    const preview = () => fixture.nativeElement.querySelector('img[decoding="async"]:not([loading])') as HTMLImageElement;
    preview().parentElement!.dispatchEvent(new WheelEvent('wheel', { deltaY: -1, cancelable: true }));
    fixture.detectChanges();
    expect(preview().style.transform).toBe('scale(1.15) translate(0px, 0px)');
    fixture.componentInstance.step(1);
    await settle();
    expect(preview().style.transform).toBe('');
  });

  it('opens the existing editor with exact membership and the focused frame as cover', async () => {
    await loaded();
    const item = fixture.componentInstance.candidates()[0];
    fixture.componentInstance.step(1);
    const pending = fixture.componentInstance.review(item);
    expect(open).toHaveBeenCalledWith(StackDialogComponent, expect.objectContaining({ data: {
      paths: ['/a.jpg', '/b.jpg'], activePath: '/a.jpg', skippable: true,
    } }));
    http.expectNone('/api/stacks');
    reviewed.next(false); reviewed.complete();
    await vi.waitFor(() => expect(fixture.componentInstance.busy()).toBe(false));
    await loaded(); await pending;
  });

  it('skips the whole suggested group when the editor asks to', async () => {
    await loaded([candidate, second]);
    const pending = fixture.componentInstance.review(candidate);
    expect(open).toHaveBeenCalledWith(StackDialogComponent, expect.objectContaining({
      data: expect.objectContaining({ skippable: true }),
    }));
    reviewed.next(SKIP_SUGGESTION); reviewed.complete();
    const dismiss = await vi.waitFor(() => http.expectOne('/api/stacks/suggestions/dismissals'));
    expect(dismiss.request.body).toEqual({ kind: 'duplicate', paths: ['/a.jpg', '/b.jpg'] });
    dismiss.flush(null, { status: 204, statusText: 'No Content' });
    http.expectNone('/api/stacks');
    await vi.waitFor(() => http.expectOne('/api/stacks/suggestions').flush({ suggestions: [second] }));
    await pending;
    expect(fixture.componentInstance.candidate()).toBe(second);
  });

  it('does not open a write editor for read-only accounts', async () => {
    await loaded(); edition.set(false); fixture.detectChanges();
    const review = [...fixture.nativeElement.querySelectorAll('button')]
      .find((b: HTMLButtonElement) => b.textContent?.trim() === 'stacks.suggestion_edit_members') as HTMLButtonElement;
    expect(review.disabled).toBe(true);
    await fixture.componentInstance.review(fixture.componentInstance.candidates()[0]);
    expect(open).not.toHaveBeenCalled();
  });

  it.each(['identity', 'navigation', 'filters'])(
    'drops old candidates when %s changes before the response', async change => {
      const request = http.expectOne('/api/stacks/suggestions');
      if (change === 'identity') owner.set('bob');
      if (change === 'filters') filters.set({ camera: 'Nikon' });
      if (change === 'navigation') await TestBed.inject(Router).navigateByUrl('/?other=1');
      request.flush({ suggestions: [candidate] });
      await fixture.whenStable(); fixture.detectChanges();
      expect(fixture.componentInstance.candidates()).toEqual([]);
      expect(close).toHaveBeenCalled();
      await fixture.componentInstance.review(candidate);
      expect(open).not.toHaveBeenCalled();
    },
  );

  it('dismisses the proposed editor when its gallery scope changes', async () => {
    await loaded();
    const pending = fixture.componentInstance.review(fixture.componentInstance.candidates()[0]);
    filters.set({ camera: 'Nikon' }); fixture.detectChanges();
    await pending;
    expect(open.mock.results[0].value.close).toHaveBeenCalled();
    expect(close).toHaveBeenCalled();
    http.expectNone('/api/stacks');
    http.expectNone('/api/stacks/suggestions');
  });

  it('allows a failed discovery to be retried', async () => {
    http.expectOne('/api/stacks/suggestions').flush({}, { status: 503, statusText: 'Busy' });
    await fixture.whenStable(); fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]')).not.toBeNull();
    const retry = fixture.componentInstance.load(); await loaded(); await retry;
    expect(fixture.componentInstance.failed()).toBe(false);
    expect(fixture.componentInstance.candidates()).toHaveLength(1);
  });
});
