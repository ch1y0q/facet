import { TestBed } from '@angular/core/testing';
import { MatDialogRef } from '@angular/material/dialog';
import { of, Subject, throwError } from 'rxjs';
import { PersonSelectorDialogComponent } from './person-selector-dialog.component';
import { ApiService } from '../../core/services/api.service';
import type { PersonOption } from './gallery.store';

const alice: PersonOption = { id: 1, name: 'Alice', face_count: 1 };
const bob: PersonOption = { id: 2, name: 'Bob', face_count: 3 };
describe('PersonSelectorDialogComponent server search', () => {
  let component: PersonSelectorDialogComponent;
  let get: ReturnType<typeof vi.fn>;
  let close: ReturnType<typeof vi.fn>;
  beforeEach(async () => {
    vi.useFakeTimers();
    get = vi.fn(() => of({ persons: [alice], total: 1 }));
    close = vi.fn();
    TestBed.configureTestingModule({
      providers: [
        PersonSelectorDialogComponent,
        { provide: ApiService, useValue: { get } },
        { provide: MatDialogRef, useValue: { close } },
      ],
    });
    component = TestBed.inject(PersonSelectorDialogComponent);
    await Promise.resolve();
  });
  afterEach(() => vi.useRealTimers());
  it('includes visible people with only one appearance via bounded server pagination', () => {
    expect(get).toHaveBeenCalledWith('/persons', {
      page: 1,
      per_page: 48,
      search: '',
      sort: 'name_asc',
    });
    expect(component.filtered()).toEqual([alice]);
  });
  it('debounces server search instead of filtering a gallery dropdown', async () => {
    get.mockReturnValue(of({ persons: [bob], total: 1 }));
    component.searchQuery = 'Bo';
    component.filter();
    component.searchQuery = 'Bob';
    component.filter();
    await vi.advanceTimersByTimeAsync(249);
    expect(get).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(get).toHaveBeenLastCalledWith('/persons', {
      page: 1,
      per_page: 48,
      search: 'Bob',
      sort: 'name_asc',
    });
    expect(component.filtered()).toEqual([bob]);
  });
  it('discards late responses for a superseded search', async () => {
    const old = new Subject<{ persons: PersonOption[]; total: number }>();
    get.mockReturnValueOnce(old).mockReturnValueOnce(of({ persons: [bob], total: 1 }));
    component.searchQuery = 'Alice';
    component.filter();
    await vi.advanceTimersByTimeAsync(250);
    component.searchQuery = 'Bob';
    component.filter();
    await vi.advanceTimersByTimeAsync(250);
    old.next({ persons: [alice], total: 1 });
    old.complete();
    await Promise.resolve();
    expect(component.filtered()).toEqual([bob]);
  });
  it('loads additional pages without a minimum appearance cutoff', async () => {
    get.mockReturnValueOnce(
      of({ persons: [alice, { id: 9, name: null, face_count: 8 }], total: 49 }),
    );
    component.searchQuery = '';
    component.filter();
    await vi.advanceTimersByTimeAsync(250);
    expect(component.hasMore()).toBe(true);
    expect(component.filtered()).toEqual([alice]);
    get.mockReturnValueOnce(of({ persons: [bob], total: 49 }));
    await component.loadMore();
    expect(get).toHaveBeenLastCalledWith('/persons', {
      page: 2,
      per_page: 48,
      search: '',
      sort: 'name_asc',
    });
    expect(component.filtered()).toEqual([alice, bob]);
    expect(component.hasMore()).toBe(false);
  });
  it('shows failure and retries the failed page without discarding previous results', async () => {
    get.mockReturnValueOnce(of({ persons: [alice], total: 49 }));
    component.filter();
    await vi.advanceTimersByTimeAsync(250);
    get.mockReturnValueOnce(throwError(() => new Error('offline')));
    await component.loadMore();
    expect(component.failed()).toBe(true);
    expect(component.filtered()).toEqual([alice]);
    get.mockReturnValueOnce(of({ persons: [bob], total: 49 }));
    await component.retry();
    expect(component.filtered()).toEqual([alice, bob]);
    expect(component.failed()).toBe(false);
  });
  it('cancels pending debounce and ignores responses after destruction', async () => {
    const pending = new Subject<{ persons: PersonOption[]; total: number }>();
    get.mockReturnValueOnce(pending);
    component.searchQuery = 'late';
    component.filter();
    await vi.advanceTimersByTimeAsync(250);
    component.searchQuery = 'never';
    component.filter();
    const count = get.mock.calls.length;
    TestBed.resetTestingModule();
    await vi.advanceTimersByTimeAsync(250);
    pending.next({ persons: [bob], total: 1 });
    pending.complete();
    await Promise.resolve();
    expect(get).toHaveBeenCalledTimes(count);
    expect(component.filtered()).toEqual([]);
  });
  it('keeps creation a proposal and cancellation makes no write', () => {
    component.searchQuery = ' Grace ';
    component.startCreate();
    component.confirmCreate();
    expect(close).toHaveBeenCalledWith({ kind: 'create', name: 'Grace' });
    component.startCreate();
    component.cancelCreate();
    expect(component.newName).toBe('');
    expect(get).toHaveBeenCalledTimes(1);
  });
});
