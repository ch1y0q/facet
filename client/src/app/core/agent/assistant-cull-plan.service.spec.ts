import { TestBed } from '@angular/core/testing';
import { UserActivityJournal } from './user-activity-journal.service';
import { AssistantCullPlanService, type CullPlanEntryInput } from './assistant-cull-plan.service';

const entry = (number: number, type: string, id: number, paths: string[], keep: string[]): CullPlanEntryInput => ({
  key: `${id}_${type}`, type, group_id: id, number, paths, keep_paths: keep,
});

describe('AssistantCullPlanService', () => {
  let service: AssistantCullPlanService;
  let record: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    record = vi.fn();
    TestBed.configureTestingModule({ providers: [{ provide: UserActivityJournal, useValue: { record } }] });
    service = TestBed.inject(AssistantCullPlanService);
  });

  it('has no snapshot without a pin or before the plan registered', () => {
    expect(service.snapshot()).toBeNull();
    service.setPin({ digest: 'd', request: { group_by: 'all' } });
    expect(service.snapshot()).toBeNull();
  });

  it('classifies groups into confirmed / pending / changed / untouched', () => {
    service.setPin({ digest: 'd', request: { group_by: 'all' } });
    service.register([
      entry(1, 'burst', 5, ['/a', '/b'], ['/b']),
      entry(2, 'similar', 5, ['/c', '/d'], ['/c']),
      entry(3, 'burst', 6, ['/e', '/f'], ['/e']),
      entry(4, 'burst', 7, ['/g', '/h'], ['/g']),
    ], { total: 10, truncated: true });
    service.recordSelection('5_similar', ['/c', '/d']);
    service.recordSelection('6_burst', ['/f']);
    service.recordConfirm('6_burst', ['/f']);
    service.recordConfirm('7_burst', ['/g']);
    expect(service.snapshot()).toEqual({
      plan_digest: 'd', groups_total: 10, plan_truncated: true,
      scope: { album_id: null, date_from: null, date_to: null },
      confirmed: [3, 4], pending: [2], untouched: 7,
      suggestions_total: 0, suggestions_accepted: 0, suggestions_open: [],
      changed: [
        { type: 'similar', group_id: 5, number: 2, keep_paths: ['/c', '/d'], reject_paths: [] },
        { type: 'burst', group_id: 6, number: 3, keep_paths: ['/f'], reject_paths: ['/e'] },
      ],
    });
    expect(record).toHaveBeenCalledWith('cull_confirm', ['/f'], { type: 'burst', group_id: 6, number: 3, keep: 1, reject: 1 });
  });

  it('reports the scope the pin was computed for and follows a new pin', () => {
    service.setPin({ digest: 'd', request: { group_by: 'all', album_id: 9, date_from: '2026-07-01', date_to: '2026:07:31 23:59:59' } });
    service.register([entry(1, 'burst', 1, ['/a', '/b'], ['/a'])], { total: 1, truncated: false });
    expect(service.snapshot()?.scope).toEqual({ album_id: 9, date_from: '2026-07-01', date_to: '2026-07-31' });
    service.setPin({ digest: 'd2', request: { group_by: 'all', album_id: 9, date_from: null, date_to: null } });
    service.register([entry(1, 'burst', 1, ['/a', '/b'], ['/a'])], { total: 1, truncated: false });
    expect(service.snapshot()?.scope).toEqual({ album_id: 9, date_from: null, date_to: null });
  });

  it('reports a whole-day EXIF window as plain dates', () => {
    service.setPin({ digest: 'd', request: { group_by: 'all', date_from: '2025:04:14 00:00:00', date_to: '2025:04:15 23:59:59' } });
    service.register([entry(1, 'burst', 1, ['/a', '/b'], ['/a'])], { total: 1, truncated: false });
    expect(service.snapshot()?.scope).toEqual({ album_id: null, date_from: '2025-04-14', date_to: '2025-04-15' });
    service.setPin({ digest: 'd2', request: { group_by: 'all', date_from: '2025:04:14 10:00:00', date_to: '2025:04:14 10:30:00' } });
    service.register([entry(1, 'burst', 1, ['/a', '/b'], ['/a'])], { total: 1, truncated: false });
    expect(service.snapshot()?.scope).toEqual({ album_id: null, date_from: '2025:04:14 10:00:00', date_to: '2025:04:14 10:30:00' });
  });

  it('compares keepers over the group\'s own photos: an unchanged confirm is not changed, a flip back is not pending', () => {
    service.setPin({ digest: 'd', request: { group_by: 'all' } });
    service.register([
      entry(1, 'burst', 1, ['/a1', '/a2', '/a3'], ['/a1', '/a4']),
      entry(2, 'burst', 2, ['/b1', '/b2'], ['/b1', '/b9']),
    ], { total: 2, truncated: false });
    service.registerDecisionsProbe(() => false);
    service.recordSelection('2_burst', ['/b1', '/b2']);
    service.recordSelection('2_burst', ['/b1']);
    service.recordConfirm('1_burst', ['/a1']);
    const snap = service.snapshot()!;
    expect(snap.changed).toEqual([]);
    expect(snap.pending).toEqual([]);
    expect(service.hasUnsavedDecisions()).toBe(false);
    expect(record).toHaveBeenCalledWith('cull_confirm', ['/a1'], expect.objectContaining({ keep: 1, reject: 2 }));
  });

  it('holds a loaded plan with the user state per digest and forgets it on a new digest or clear', () => {
    service.setPin({ digest: 'd', request: { group_by: 'all' } });
    service.register([entry(1, 'burst', 1, ['/a', '/b'], ['/a'])], { total: 1, truncated: false });
    service.hold('d', { groups: [] });
    service.recordConfirm('1_burst', ['/b']);
    expect(service.heldPlan('d')).toEqual({ data: { groups: [] }, state: new Map([['1_burst', { status: 'confirmed', current: ['/b'] }]]) });
    expect(service.heldPlan('other')).toBeNull();
    service.setPin({ digest: 'd', request: { group_by: 'all' } });
    expect(service.heldPlan('d')).not.toBeNull();
    service.setPin({ digest: 'e', request: { group_by: 'all' } });
    expect(service.heldPlan('d')).toBeNull();
  });

  it('reports why a load failed, per digest', () => {
    service.recordLoadFailure('d', 'failed');
    expect(service.loadFailure('d')).toBe('failed');
    expect(service.loadFailure('e')).toBeNull();
    service.setPin({ digest: 'e', request: { group_by: 'all' } });
    expect(service.loadFailure('d')).toBeNull();
  });

  it('a skipped group is neither pending nor untouched, and journals cull_skip', () => {
    service.setPin({ digest: 'd', request: { group_by: 'all' } });
    service.register([entry(1, 'burst', 5, ['/a', '/b'], ['/a'])], { total: 1, truncated: false });
    service.recordSkip('5_burst');
    expect(service.snapshot()).toEqual(expect.objectContaining({ untouched: 0, pending: [], confirmed: [] }));
    expect(record).toHaveBeenCalledWith('cull_skip', ['/a', '/b'], { type: 'burst', group_id: 5, number: 1 });
  });

  it('reports unconfirmed flips for the re-show guard', () => {
    service.setPin({ digest: 'd', request: { group_by: 'all' } });
    service.register([entry(1, 'burst', 5, ['/a', '/b'], ['/a'])], { total: 1, truncated: false });
    expect(service.hasUnconfirmedFlips()).toBe(false);
    service.recordSelection('5_burst', ['/b']);
    expect(service.hasUnconfirmedFlips()).toBe(true);
    service.recordConfirm('5_burst', ['/b']);
    expect(service.hasUnconfirmedFlips()).toBe(false);
  });

  it('clear drops the pin and the read model', () => {
    service.setPin({ digest: 'd', request: { group_by: 'all' } });
    service.register([entry(1, 'burst', 5, ['/a'], ['/a'])], { total: 1, truncated: false });
    service.clear();
    expect(service.pin()).toBeNull();
    expect(service.snapshot()).toBeNull();
  });

  it('setFocus moves only focusNumber on the held pin', () => {
    service.setPin({ digest: 'd', request: { group_by: 'all' } });
    service.setFocus(7);
    expect(service.pin()).toEqual({ digest: 'd', request: { group_by: 'all' }, focusNumber: 7 });
  });

  it('a pin with another digest forgets the previous plan, the same digest keeps it', () => {
    service.setPin({ digest: 'd1', request: { group_by: 'all' } });
    service.register([entry(1, 'burst', 5, ['/a', '/b'], ['/a'])], { total: 1, truncated: false });
    service.setPin({ digest: 'd1', request: { group_by: 'all' }, focusNumber: 1 });
    expect(service.snapshot()).not.toBeNull();
    service.setPin({ digest: 'd2', request: { group_by: 'all' } });
    expect(service.snapshot()).toBeNull();
  });

  it('counts a held unconfirmed flip as unsaved even with no darkroom mounted (it is restored on re-mount)', () => {
    service.setPin({ digest: 'd', request: { group_by: 'all' } });
    service.register([entry(1, 'burst', 5, ['/a', '/b'], ['/a'])], { total: 1, truncated: false });
    expect(service.hasUnsavedDecisions()).toBe(false);
    service.recordSelection('5_burst', ['/b']);
    expect(service.hasUnsavedDecisions()).toBe(true);
    let manual = false;
    const unregister = service.registerDecisionsProbe(() => manual);
    expect(service.hasUnsavedDecisions()).toBe(true);
    service.recordConfirm('5_burst', ['/b']);
    expect(service.hasUnsavedDecisions()).toBe(false);
    manual = true;
    expect(service.hasUnsavedDecisions()).toBe(true);
    unregister();
    expect(service.hasUnsavedDecisions()).toBe(false);
  });

  it('a probe withdrawn after a newer one registered leaves the newer one in place', () => {
    const first = service.registerDecisionsProbe(() => true);
    service.registerDecisionsProbe(() => false);
    first();
    expect(service.hasUnsavedDecisions()).toBe(false);
    const second = service.registerDecisionsProbe(() => true);
    expect(service.hasUnsavedDecisions()).toBe(true);
    second();
  });

  describe('carried-over flips (re-plan)', () => {
    beforeEach(() => service.setPin({ digest: 'd2', request: { group_by: 'all' } }));

    it('registers current_paths as the keepers, in path order and limited to the group, and reports them as pending and changed', () => {
      service.register([
        { ...entry(1, 'burst', 5, ['/a', '/b', '/c'], ['/a']), current_paths: ['/c', '/b', '/zz'] },
        entry(2, 'burst', 6, ['/d', '/e'], ['/d']),
      ], { total: 2, truncated: false });
      const snap = service.snapshot()!;
      expect(snap.plan_digest).toBe('d2');
      expect(snap.pending).toEqual([1]);
      expect(snap.changed).toEqual([{ type: 'burst', group_id: 5, number: 1, keep_paths: ['/b', '/c'], reject_paths: ['/a'] }]);
      expect(snap.untouched).toBe(1);
    });

    it('a carried selection equal to the new keepers is no flip', () => {
      service.register([{ ...entry(1, 'burst', 5, ['/a', '/b'], ['/a', '/b']), current_paths: ['/b', '/a'] }], { total: 1, truncated: false });
      expect(service.snapshot()!.changed).toEqual([]);
      expect(service.openFlips()).toEqual([]);
    });

    it('openFlips lists only open groups whose keepers differ, with an empty selection kept', () => {
      service.register([
        entry(1, 'burst', 1, ['/a1', '/a2'], ['/a1']),
        entry(2, 'burst', 2, ['/b1', '/b2'], ['/b1']),
        entry(3, 'burst', 3, ['/c1', '/c2'], ['/c1']),
        entry(4, 'burst', 4, ['/d1', '/d2'], ['/d1']),
        entry(5, 'burst', 5, ['/e1', '/e2'], ['/e1']),
      ], { total: 5, truncated: false });
      service.recordSelection('1_burst', ['/a1', '/a2']);
      service.recordSelection('2_burst', ['/b2']);
      service.recordConfirm('2_burst', ['/b2']);
      service.recordSelection('3_burst', ['/c2']);
      service.recordSkip('3_burst');
      service.recordSelection('5_burst', []);
      expect(service.openFlips()).toEqual([
        { paths: ['/a1', '/a2'], current: ['/a1', '/a2'] },
        { paths: ['/e1', '/e2'], current: [] },
      ]);
    });

    it('confirmedEntries lists only confirmed groups with the keepers they were confirmed with', () => {
      service.register([
        entry(1, 'scene', 1, ['/a', '/b', '/c'], ['/a']),
        entry(2, 'scene', 2, ['/d', '/e'], ['/d']),
        entry(3, 'scene', 3, ['/f', '/g'], ['/f']),
      ], { total: 3, truncated: false });
      service.recordConfirm('1_scene', ['/b', '/a']);
      service.recordSelection('2_scene', ['/e']);
      service.recordSkip('3_scene');
      expect(service.confirmedEntries()).toEqual([{ paths: ['/a', '/b', '/c'], current: ['/a', '/b'] }]);
    });

    it('registers a carried confirmed group as confirmed, without journalling a new confirm', () => {
      service.register([
        { ...entry(1, 'scene', 8, ['/a', '/b'], ['/a']), current_paths: ['/a', '/b'], confirmed: true },
        entry(2, 'scene', 9, ['/x', '/y'], ['/x']),
      ], { total: 2, truncated: false });
      const snap = service.snapshot()!;
      expect(snap.confirmed).toEqual([1]);
      expect(snap.pending).toEqual([]);
      expect(snap.changed).toEqual([{ type: 'scene', group_id: 8, number: 1, keep_paths: ['/a', '/b'], reject_paths: [] }]);
      expect(snap.untouched).toBe(1);
      expect(service.openFlips()).toEqual([]);
      expect(record).not.toHaveBeenCalled();
    });
  });

  describe('suggestions', () => {
    const plan = () => {
      service.setPin({ digest: 'd', request: { group_by: 'all' } });
      service.register([
        entry(1, 'burst', 1, ['/a', '/b', '/c'], ['/a']),
        entry(2, 'burst', 2, ['/d', '/e'], ['/d']),
        entry(3, 'burst', 3, ['/f', '/g'], ['/f']),
      ], { total: 3, truncated: false });
    };
    const reject = (path: string, reason = 'soft') => ({ path, action: 'reject' as const, reason });
    const keep = (path: string, reason = 'sharp') => ({ path, action: 'keep' as const, reason });

    it('stores a differing suggestion, merges by path on a later call and keeps the others', () => {
      plan();
      expect(service.suggest([reject('/a'), keep('/b')], [{ path: '/a', note: 'close' }], false)).toEqual({
        applied: ['/a', '/b'], redundant: [], closed: [], missing: [], groups_applied: ['/a'], groups_missing: [], groups_closed: [], suggestions_total: 2, notes_total: 1,
      });
      service.suggest([reject('/a', 'blurry')], [], false);
      const held = service.suggestions();
      expect(held.photos.get('/a')).toEqual({ action: 'reject', reason: 'blurry' });
      expect(held.photos.get('/b')).toEqual({ action: 'keep', reason: 'sharp' });
      expect(held.notes.get('/a')).toBe('close');
    });

    it('lets a later call that agrees with the plan retire the earlier proposal for that photo', () => {
      plan();
      service.suggest([reject('/a')], [], false);
      expect(service.suggest([keep('/a')], [], false)).toMatchObject({ redundant: ['/a'], suggestions_total: 0 });
      expect(service.suggestions().photos.size).toBe(0);
    });

    it('replace drops the earlier ones and replace with nothing clears', () => {
      plan();
      service.suggest([reject('/a')], [{ path: '/d', note: 'n' }], false);
      service.suggest([keep('/e')], [], true);
      expect([...service.suggestions().photos.keys()]).toEqual(['/e']);
      expect(service.suggestions().notes.size).toBe(0);
      expect(service.suggest([], [], true)).toMatchObject({ applied: [], suggestions_total: 0, notes_total: 0 });
      expect(service.suggestions().photos.size).toBe(0);
    });

    it('reports missing, closed and redundant paths and stores none of them', () => {
      plan();
      service.recordConfirm('2_burst', ['/d']);
      service.recordSkip('3_burst');
      const answer = service.suggest(
        [reject('/zzz'), reject('/e'), reject('/g'), keep('/a'), keep('/b')],
        [{ path: '/zzz', note: 'x' }, { path: '/d', note: 'closed group' }, { path: '/c', note: 'ok' }], false);
      expect(answer).toEqual({
        applied: ['/b'], redundant: ['/a'], closed: ['/e', '/g'], missing: ['/zzz'],
        groups_applied: ['/c'], groups_missing: ['/zzz'], groups_closed: ['/d'], suggestions_total: 1, notes_total: 1,
      });
      expect([...service.suggestions().photos.keys()]).toEqual(['/b']);
    });

    it('reports a photo and a note of a group counting down to a confirm as closed, and stores neither', () => {
      plan();
      service.registerClosedGroupsProbe(() => new Set(['1_burst']));
      expect(service.suggest([reject('/a')], [{ path: '/b', note: 'n' }], false)).toMatchObject({
        applied: [], closed: ['/a'], groups_applied: [], groups_closed: ['/b'], suggestions_total: 0, notes_total: 0,
      });
      service.registerClosedGroupsProbe(() => new Set());
      service.suggest([reject('/a')], [], false);
      service.registerClosedGroupsProbe(() => new Set(['1_burst']));
      expect(service.snapshot()?.suggestions_open).toEqual([]);
    });

    it('refuses over the cap as a whole and leaves the maps identical', () => {
      service.setPin({ digest: 'd', request: { group_by: 'all' } });
      const paths = Array.from({ length: 301 }, (_, i) => `/p${i}`);
      service.register([entry(1, 'burst', 1, paths, [])], { total: 1, truncated: false });
      const first = service.suggest(paths.slice(0, 300).map(p => keep(p)), [], false);
      expect(first).not.toBe('too_large');
      const before = service.suggestions();
      expect(service.suggest([keep('/p300')], [], false)).toBe('too_large');
      expect(service.suggestions()).toBe(before);
      expect(service.suggest([keep('/p0', 'again')], [], false)).not.toBe('too_large');
    });

    it('clear() empties them, and a re-plan with a new digest through setPin keeps them', () => {
      plan();
      service.suggest([reject('/a')], [{ path: '/a', note: 'n' }], false);
      service.setPin({ digest: 'd2', request: { group_by: 'all' } });
      expect(service.suggestions().photos.size).toBe(1);
      service.clear();
      expect(service.suggestions().photos.size).toBe(0);
      expect(service.suggestions().notes.size).toBe(0);
    });

    it('does not let a selection flip alter the stored suggestions', () => {
      plan();
      service.suggest([reject('/a')], [], false);
      const before = service.suggestions();
      service.recordSelection('1_burst', ['/b']);
      expect(service.suggestions()).toBe(before);
    });

    it('reports open and accepted suggestions in the snapshot, with the stored total', () => {
      plan();
      service.suggest([reject('/a'), keep('/b'), reject('/d')], [], false);
      expect(service.snapshot()).toMatchObject({
        suggestions_total: 3, suggestions_accepted: 0,
        suggestions_open: [{ path: '/a', action: 'reject' }, { path: '/b', action: 'keep' }, { path: '/d', action: 'reject' }],
      });
      service.recordSelection('1_burst', ['/b']);
      expect(service.snapshot()).toMatchObject({
        suggestions_accepted: 2, suggestions_open: [{ path: '/d', action: 'reject' }],
      });
    });

    it('drops a confirmed group from the open list but still counts what was accepted there', () => {
      plan();
      service.suggest([reject('/a'), reject('/d')], [], false);
      service.recordSelection('1_burst', ['/b']);
      service.recordConfirm('1_burst', ['/b']);
      service.recordSkip('2_burst');
      const snap = service.snapshot()!;
      expect(snap.suggestions_open).toEqual([]);
      expect(snap.suggestions_accepted).toBe(1);
      expect(snap.suggestions_total).toBe(2);
    });

    it('keeps them across a re-plan that holds the same paths, and does not count a plan that moved onto them as accepted', () => {
      plan();
      service.suggest([reject('/a')], [], false);
      service.register([entry(1, 'burst', 1, ['/a', '/b', '/c'], ['/b'])], { total: 1, truncated: false });
      expect(service.snapshot()).toMatchObject({ suggestions_open: [], suggestions_accepted: 0, suggestions_total: 1 });
      service.register([entry(1, 'burst', 1, ['/a', '/b', '/c'], ['/a'])], { total: 1, truncated: false });
      expect(service.snapshot()).toMatchObject({ suggestions_open: [{ path: '/a', action: 'reject' }], suggestions_accepted: 0 });
    });
  });
});
