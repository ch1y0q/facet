import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { MatDialog } from '@angular/material/dialog';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { JunkSweepComponent } from './junk-sweep.component';

describe('JunkSweepComponent', () => {

  let component: any;
  let mockApi: { get: Mock; post: Mock };
  let mockI18n: { t: Mock };
  let mockSnackBar: { open: Mock };
  let mockDialog: { open: Mock };
  let photosCall: number;
  let journal: { record: Mock };

  const initialPhotos = [
    { path: '/p/meme.jpg', filename: 'meme.jpg', junk_kind: 'meme', aggregate: 2.1 },
    { path: '/p/s1.jpg', filename: 's1.jpg', junk_kind: 'screenshot', aggregate: 1.0 },
    { path: '/p/s2.jpg', filename: 's2.jpg', junk_kind: 'screenshot', aggregate: 1.1 },
    { path: '/p/s3.jpg', filename: 's3.jpg', junk_kind: 'screenshot', aggregate: 1.2 },
  ];

  const defaultFirstPage = { photos: initialPhotos, total: 4, total_pages: 1, page: 1, has_more: false };

  function createComponent(firstPage: Record<string, unknown> = defaultFirstPage) {
    photosCall = 0;
    mockApi = {
      get: vi.fn((url: string) => {
        if (url.includes('junk_kinds')) {
          return of({ junk_kinds: [['meme', 1], ['screenshot', 3]] });
        }
        photosCall += 1;
        if (photosCall === 1) {
          return of(firstPage);
        }
        return of({ photos: [], total: 0, total_pages: 1, page: 1, has_more: false });
      }),
      post: vi.fn(() => of({})),
    };
    mockI18n = { t: vi.fn((k: string) => k) };
    mockSnackBar = { open: vi.fn() };
    mockDialog = { open: vi.fn(() => ({ afterClosed: () => of(true) })) };
    journal = { record: vi.fn() };

    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      providers: [
        JunkSweepComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: I18nService, useValue: mockI18n },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: MatDialog, useValue: mockDialog },
        { provide: UserActivityJournal, useValue: journal },
      ],
    });
    component = TestBed.inject(JunkSweepComponent);
  }

  it('reads the total candidate count from the API `total` field, not `total_count`', async () => {
    createComponent();

    await component.ngOnInit();

    expect(component.total()).toBe(4);
  });

  it('keeps the counter a finite number after rejecting a photo (no NaN)', async () => {
    createComponent();
    await component.ngOnInit();

    await component.reject(initialPhotos[1]);

    expect(component.total()).toBe(3);
    expect(Number.isNaN(component.total())).toBe(false);
  });

  it('rejectAllShown refreshes the per-kind counts feeding the filter menu items', async () => {
    createComponent();
    await component.ngOnInit();
    expect(component.kinds()).toEqual([['meme', 1], ['screenshot', 3]]);

    await component.rejectAllShown();

    expect(mockApi.post).toHaveBeenCalledWith('/photos/batch_reject', {
      photo_paths: initialPhotos.map(p => p.path),
    });
    const counts = new Map(component.kinds() as [string, number][]);
    expect(counts.get('meme')).toBe(0);
    expect(counts.get('screenshot')).toBe(0);
  });

  // `loadMore` has no ceiling, so 21 clicks at 48/page puts `shown` past the
  // server's 1,000-entry photo_paths cap: one POST of the lot is a 422 behind a
  // generic error toast, which is the whole action failing.
  it('splits reject-all past the server cap into request-sized chunks', async () => {
    const many = Array.from({ length: 1500 }, (_, i) => ({
      path: `/p/j${i}.jpg`, filename: `j${i}.jpg`, junk_kind: 'meme', aggregate: 1.0,
    }));
    createComponent({ photos: many, total: 1500, total_pages: 32, page: 1, has_more: true });
    await component.ngOnInit();

    await component.rejectAllShown();

    const chunks = mockApi.post.mock.calls
      .filter(c => c[0] === '/photos/batch_reject')
      .map(c => (c[1] as { photo_paths: string[] }).photo_paths);
    expect(chunks.map(c => c.length)).toEqual([1000, 500]);
    expect(chunks.flat()).toEqual(many.map(p => p.path));
  });

  it('journals a single reject and a clear, and nothing when either fails', async () => {
    createComponent();
    await component.ngOnInit();

    await component.reject(initialPhotos[0]);
    await component.keep(initialPhotos[1]);
    expect(journal.record).toHaveBeenNthCalledWith(1, 'junk', ['/p/meme.jpg'], { action: 'reject', count: 1 });
    expect(journal.record).toHaveBeenNthCalledWith(2, 'junk', ['/p/s1.jpg'], { action: 'clear', count: 1 });

    journal.record.mockClear();
    mockApi.post.mockReturnValue(throwError(() => new Error('boom')));
    await component.reject(initialPhotos[2]);
    await component.keep(initialPhotos[3]);
    expect(journal.record).not.toHaveBeenCalled();
  });

  it('journals one entry for a reject-all, and only the chunks that landed when a later one fails', async () => {
    const many = Array.from({ length: 1500 }, (_, i) => ({
      path: `/p/j${i}.jpg`, filename: `j${i}.jpg`, junk_kind: 'meme', aggregate: 1.0,
    }));
    createComponent({ photos: many, total: 1500, total_pages: 32, page: 1, has_more: true });
    await component.ngOnInit();
    await component.rejectAllShown();
    expect(journal.record).toHaveBeenCalledTimes(1);
    const [kind, paths, value] = journal.record.mock.calls[0];
    expect([kind, paths.length, value]).toEqual(['junk', 1500, { action: 'reject', count: 1500 }]);

    journal.record.mockClear();
    createComponent({ photos: many, total: 1500, total_pages: 32, page: 1, has_more: true });
    await component.ngOnInit();
    mockApi.post.mockReturnValueOnce(of({})).mockReturnValueOnce(throwError(() => new Error('boom')));
    await component.rejectAllShown();
    expect(journal.record).toHaveBeenCalledTimes(1);
    const [, partialPaths, partialValue] = journal.record.mock.calls[0];
    expect(partialPaths).toEqual(many.slice(0, 1000).map(p => p.path));
    expect(partialValue).toEqual({ action: 'reject', count: 1000, partial: true });
  });

  it('feeds the count of *shown* candidates (not the API total) into the reject-all tooltip', async () => {
    // Only 2 of 10 candidates are loaded on the first page; the reject-all button
    // binds junk.reject_all with { count: photos().length }, so the tooltip must
    // reflect the shown count (2), decoupled from the whole-library total (10).
    createComponent({ photos: initialPhotos.slice(0, 2), total: 10, total_pages: 5, page: 1, has_more: true });
    await component.ngOnInit();

    expect(component.photos().length).toBe(2);
    expect(component.total()).toBe(10);
  });
});
