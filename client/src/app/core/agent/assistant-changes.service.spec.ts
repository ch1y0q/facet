import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { AuthService } from '../services/auth.service';
import { AssistantChangeBatch, AssistantChangesService } from './assistant-changes.service';
import { InpageChangeNotifier } from './inpage-change-notifier.service';

describe('AssistantChangesService', () => {
  let notify: ReturnType<typeof vi.fn>;
  let authStatus: ReturnType<typeof signal<{ authenticated: boolean; user_id: string | null } | null>>;
  let service: AssistantChangesService;
  let batches: AssistantChangeBatch[];

  beforeEach(() => {
    vi.useFakeTimers();
    notify = vi.fn();
    authStatus = signal({ authenticated: true, user_id: 'alice' });
    TestBed.configureTestingModule({
      providers: [
        { provide: InpageChangeNotifier, useValue: { notify } },
        { provide: AuthService, useValue: { status: authStatus } },
      ],
    });
    service = TestBed.inject(AssistantChangesService);
    batches = [];
    service.batch$.subscribe(b => batches.push(b));
    TestBed.tick();
  });

  afterEach(() => {
    vi.useRealTimers();
    TestBed.resetTestingModule();
  });

  it('coalesces 4 single-path reports within the window into one batch and one notify(4)', () => {
    for (const p of ['/a', '/b', '/c', '/d']) {
      service.report({ paths: [p], count: 1 });
      vi.advanceTimersByTime(100);
    }
    expect(batches).toHaveLength(0);
    vi.advanceTimersByTime(400);
    expect(batches).toEqual([{ paths: ['/a', '/b', '/c', '/d'], count: 4 }]);
    expect(notify).toHaveBeenCalledTimes(1);
    expect(notify).toHaveBeenCalledWith(4);
  });

  it('dedupes repeated paths', () => {
    service.report({ paths: ['/a'], count: 1 });
    service.report({ paths: ['/a'], count: 1 });
    vi.advanceTimersByTime(400);
    expect(batches).toEqual([{ paths: ['/a'], count: 1 }]);
    expect(notify).toHaveBeenCalledWith(1);
  });

  it('makes the batch sticky-null when a null report lands, notifying with the count', () => {
    service.report({ paths: ['/a'], count: 1 });
    service.report({ paths: null, count: 7 });
    service.report({ paths: ['/b'], count: 1 });
    vi.advanceTimersByTime(400);
    expect(batches).toEqual([{ paths: null, count: 7 }]);
    expect(notify).toHaveBeenCalledWith(7);
  });

  it('notifies with max(unique paths, count)', () => {
    service.report({ paths: ['/a', '/b'], count: 5 });
    vi.advanceTimersByTime(400);
    expect(notify).toHaveBeenCalledWith(5);
  });

  it('starts a new batch for a report after the flush', () => {
    service.report({ paths: ['/a'], count: 1 });
    vi.advanceTimersByTime(400);
    service.report({ paths: ['/b'], count: 1 });
    vi.advanceTimersByTime(400);
    expect(batches).toEqual([{ paths: ['/a'], count: 1 }, { paths: ['/b'], count: 1 }]);
  });

  it('flushes after the 2 s max wait even if reports keep arriving', () => {
    for (let i = 0; i < 12; i += 1) {
      service.report({ paths: [`/p${i}`], count: 1 });
      vi.advanceTimersByTime(300);
    }
    expect(batches.length).toBeGreaterThanOrEqual(1);
    expect(batches[0].paths!.length).toBeLessThanOrEqual(8);
  });

  it('drops pending batches on an identity change', () => {
    service.report({ paths: ['/a'], count: 1 });
    authStatus.set({ authenticated: true, user_id: 'bob' });
    TestBed.tick();
    vi.advanceTimersByTime(3000);
    expect(batches).toHaveLength(0);
    expect(notify).not.toHaveBeenCalled();
  });
});
