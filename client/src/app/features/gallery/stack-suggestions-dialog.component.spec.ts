import { ComponentFixture, TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { provideRouter, Router } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialog, MatDialogRef } from '@angular/material/dialog';
import { Subject } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from './gallery.store';
import { StackDialogComponent } from './stack-dialog.component';
import { StackSuggestionsDialogComponent } from './stack-suggestions-dialog.component';

const candidate = { key: 'duplicate:2', kind: 'duplicate' as const, paths: ['/a.jpg', '/b.jpg'], cover_path: '/b.jpg' };

describe('suggested stack review through HTTP and router', () => {
  let fixture: ComponentFixture<StackSuggestionsDialogComponent>;
  let http: HttpTestingController;
  let owner: ReturnType<typeof signal<string>>;
  let edition: ReturnType<typeof signal<boolean>>;
  let filters: ReturnType<typeof signal<Record<string, string>>>;
  let close: ReturnType<typeof vi.fn>;
  let open: ReturnType<typeof vi.fn>;
  let reviewed: Subject<boolean>;

  beforeEach(() => {
    owner = signal('alice'); edition = signal(true); filters = signal({ path_prefix: '/photos' });
    const beforeClosed = new Subject<void>(); reviewed = new Subject<boolean>();
    close = vi.fn(() => beforeClosed.next()); open = vi.fn(() => ({ afterClosed: () => reviewed, close: vi.fn(() => { reviewed.next(false); reviewed.complete(); }) }));
    TestBed.configureTestingModule({
      imports: [StackSuggestionsDialogComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting(),
        { provide: AuthService, useValue: { identity: owner, isEdition: edition } },
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
        { provide: GalleryStore, useValue: { filters, pinnedPaths: signal(null), filterPayload: filters } },
        { provide: MatDialog, useValue: { open } },
        { provide: MatDialogRef, useValue: { close, beforeClosed: () => beforeClosed } },
        { provide: MAT_DIALOG_DATA, useValue: { filters: { path_prefix: '/photos' } } },
      ],
    });
    TestBed.overrideProvider(MatDialog, { useValue: { open } });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(StackSuggestionsDialogComponent); fixture.detectChanges();
  });
  afterEach(() => {
    try { fixture?.destroy(); http?.verify(); } finally { TestBed.resetTestingModule(); }
  });

  async function loaded() {
    const request = http.expectOne('/api/stacks/suggestions');
    expect(request.request.body).toEqual({ filters: { path_prefix: '/photos' } });
    request.flush({ suggestions: [candidate] });
    await fixture.whenStable(); fixture.detectChanges();
  }

  it('renders candidates without creating stacks; dismissal makes no write and survives reload in this dialog', async () => {
    await loaded();
    expect(fixture.nativeElement.querySelectorAll('img').length).toBe(2);
    fixture.componentInstance.dismiss(candidate.key); fixture.detectChanges();
    expect(fixture.componentInstance.candidates()).toEqual([]);
    http.expectNone('/api/stacks');
    const reload = fixture.componentInstance.load(); await loaded(); await reload;
    expect(fixture.componentInstance.candidates()).toEqual([]);
    expect(open).not.toHaveBeenCalled();
  });

  it('opens the existing editor with exact reviewed membership and recommended cover', async () => {
    await loaded();
    const item = fixture.componentInstance.candidates()[0];
    const pending = fixture.componentInstance.review(item);
    expect(open).toHaveBeenCalledWith(StackDialogComponent, expect.objectContaining({ data: {
      paths: ['/a.jpg', '/b.jpg'], activePath: '/b.jpg',
    } }));
    http.expectNone('/api/stacks');
    reviewed.next(false); reviewed.complete();
    await vi.waitFor(() => expect(fixture.componentInstance.reviewing()).toBe(false));
    await loaded(); await pending;
  });

  it('does not open a write editor for read-only accounts', async () => {
    await loaded(); edition.set(false); fixture.detectChanges();
    const review = [...fixture.nativeElement.querySelectorAll('button')]
      .find((b: HTMLButtonElement) => b.textContent?.trim() === 'stacks.suggestion_review') as HTMLButtonElement;
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
