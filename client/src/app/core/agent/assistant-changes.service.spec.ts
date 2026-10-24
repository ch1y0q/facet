import { computed, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { AuthService } from '../services/auth.service';
import { AssistantChangeBatch, AssistantChangesService, MAX_CHANGED_PATHS } from './assistant-changes.service';
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
        { provide: AuthService, useValue: { identity: computed(() => `${authStatus()?.authenticated ? 1 : 0}|${authStatus()?.user_id ?? ''}`) } },
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

  describe('activity and the active chip', () => {
    it('a report lights active, appends one write entry, and active drops after 4 s', () => {
      service.report({ tool: 'set_rating', paths: ['/a'], count: 1 });
      expect(service.active()).toBe(true);
      expect(service.activity()).toHaveLength(1);
      expect(service.activity()[0]).toMatchObject({ kind: 'write', tool: 'set_rating', count: 1, paths: ['/a'] });
      vi.advanceTimersByTime(3999);
      expect(service.active()).toBe(true);
      vi.advanceTimersByTime(1);
      expect(service.active()).toBe(false);
    });

    it('merges frames sharing a callId into one entry with summed count and unioned paths', () => {
      for (const p of ['/a', '/b', '/c', '/d']) service.report({ tool: 'toggle_rejected', agentTool: 'set_rejected', callId: 'c1', paths: [p], count: 1 });
      expect(service.activity()).toHaveLength(1);
      expect(service.activity()[0]).toMatchObject({ kind: 'write', tool: 'set_rejected', callId: 'c1', count: 4, paths: ['/a', '/b', '/c', '/d'] });
    });

    it('keeps different callIds as separate entries and frames without a callId on their own', () => {
      service.report({ agentTool: 'set_rejected', callId: 'c1', paths: ['/a'], count: 1 });
      service.report({ agentTool: 'set_rejected', callId: 'c2', paths: ['/b'], count: 1 });
      service.report({ tool: 'x', paths: ['/c'], count: 1 });
      service.report({ tool: 'x', paths: ['/d'], count: 1 });
      expect(service.activity()).toHaveLength(4);
    });

    it('a null-paths frame nulls the merged union, and the count sums the non-null ones', () => {
      service.report({ agentTool: 't', callId: 'c1', paths: ['/a'], count: 1 });
      service.report({ agentTool: 't', callId: 'c1', paths: null, count: 5 });
      service.report({ agentTool: 't', callId: 'c1', paths: null, count: null });
      expect(service.activity()).toHaveLength(1);
      expect(service.activity()[0]).toMatchObject({ count: 6, paths: null });
    });

    it('count stays null when every frame has a null count', () => {
      service.report({ agentTool: 't', callId: 'c1', paths: null, count: null });
      service.report({ agentTool: 't', callId: 'c1', paths: null, count: null });
      expect(service.activity()[0].count).toBeNull();
    });

    it('a union over MAX_CHANGED_PATHS becomes null', () => {
      service.report({ agentTool: 't', callId: 'c1', paths: Array.from({ length: MAX_CHANGED_PATHS }, (_, i) => `/p${i}`), count: MAX_CHANGED_PATHS });
      service.report({ agentTool: 't', callId: 'c1', paths: ['/extra'], count: 1 });
      expect(service.activity()[0].paths).toBeNull();
      expect(service.activity()[0].count).toBe(MAX_CHANGED_PATHS + 1);
    });

    it('a frame without showPaths adds nothing to the merged list', () => {
      service.report({ agentTool: 'auto_cull', callId: 'c2', paths: null, count: 1 });
      service.report({ agentTool: 'auto_cull', callId: 'c2', paths: null, showPaths: ['/r1'], count: 1 });
      service.report({ agentTool: 'auto_cull', callId: 'c2', paths: null, count: 1 });
      expect(service.activity()[0].showPaths).toEqual(['/r1']);
    });

    it('carries showPaths separately from paths', () => {
      service.report({ agentTool: 'auto_cull', callId: 'c1', paths: null, showPaths: ['/r1', '/r2'], count: 2 });
      expect(service.activity()[0]).toMatchObject({ paths: null, showPaths: ['/r1', '/r2'] });
    });

    it('merging bumps at and moves the entry to the front, keeping its id', () => {
      service.report({ agentTool: 'a', callId: 'c1', paths: ['/a'], count: 1 });
      const id = service.activity()[0].id;
      const first = service.activity()[0].at;
      vi.advanceTimersByTime(1000);
      service.report({ agentTool: 'b', callId: 'c2', paths: ['/b'], count: 1 });
      vi.advanceTimersByTime(1000);
      service.report({ agentTool: 'a', callId: 'c1', paths: ['/c'], count: 1 });
      expect(service.activity().map(e => e.callId)).toEqual(['c1', 'c2']);
      expect(service.activity()[0].id).toBe(id);
      expect(service.activity()[0].at).toBeGreaterThan(first);
    });

    it('does not merge into an entry that fell out of the ring', () => {
      service.report({ agentTool: 'a', callId: 'old', paths: ['/a'], count: 1 });
      for (let i = 0; i < 50; i++) service.noteCall(`ui_tool_${i}`);
      service.report({ agentTool: 'a', callId: 'old', paths: ['/b'], count: 1 });
      expect(service.activity()).toHaveLength(50);
      expect(service.activity()[0]).toMatchObject({ callId: 'old', count: 1, paths: ['/b'] });
    });

    it('an identity change clears merged entries so a later frame starts fresh', () => {
      service.report({ agentTool: 'a', callId: 'c1', paths: ['/a'], count: 1 });
      authStatus.set({ authenticated: true, user_id: 'bob' });
      TestBed.tick();
      service.report({ agentTool: 'a', callId: 'c1', paths: ['/b'], count: 1 });
      expect(service.activity()).toHaveLength(1);
      expect(service.activity()[0]).toMatchObject({ count: 1, paths: ['/b'] });
    });

    it('noteCall for a ui tool lights active and appends a ui entry', () => {
      service.noteCall('ui_show_photos');
      expect(service.active()).toBe(true);
      expect(service.activity()).toHaveLength(1);
      expect(service.activity()[0]).toMatchObject({ kind: 'ui', tool: 'ui_show_photos', count: null, paths: null });
    });

    it('noteCall for a ui_get_ tool lights active with no entry', () => {
      service.noteCall('ui_get_context');
      expect(service.active()).toBe(true);
      expect(service.activity()).toHaveLength(0);
    });

    it('resets the 4 s timer on each event', () => {
      service.noteCall('ui_get_context');
      vi.advanceTimersByTime(3000);
      service.noteCall('ui_get_context');
      vi.advanceTimersByTime(3000);
      expect(service.active()).toBe(true);
      vi.advanceTimersByTime(1000);
      expect(service.active()).toBe(false);
    });

    it('keeps the newest 50 of 60 events, newest first', () => {
      for (let i = 0; i < 60; i++) service.noteCall(`ui_tool_${i}`);
      const log = service.activity();
      expect(log).toHaveLength(50);
      expect(log[0].tool).toBe('ui_tool_59');
      expect(log[49].tool).toBe('ui_tool_10');
      expect(new Set(log.map(e => e.id)).size).toBe(50);
    });
  });

  it.each([
    ['another user', { authenticated: true, user_id: 'bob' }],
    ['logout', null],
  ])('clears the activity log and the active chip on %s', (_label, next) => {
    service.noteCall('ui_navigate');
    service.report({ tool: 'set_rating', paths: ['/a'], count: 1 });
    expect(service.activity()).toHaveLength(2);
    expect(service.active()).toBe(true);
    authStatus.set(next);
    TestBed.tick();
    expect(service.activity()).toEqual([]);
    expect(service.active()).toBe(false);
    vi.advanceTimersByTime(5000);
    expect(service.active()).toBe(false);
  });
});
