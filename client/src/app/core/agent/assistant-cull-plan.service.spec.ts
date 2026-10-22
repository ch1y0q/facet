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
      plan_digest: 'd', groups_total: 10, truncated: true,
      confirmed: [3, 4], pending: [2], untouched: 7,
      changed: [
        { type: 'similar', group_id: 5, number: 2, keep_paths: ['/c', '/d'], reject_paths: [] },
        { type: 'burst', group_id: 6, number: 3, keep_paths: ['/f'], reject_paths: ['/e'] },
      ],
    });
    expect(record).toHaveBeenCalledWith('cull_confirm', ['/f'], { type: 'burst', group_id: 6, number: 3, keep: 1, reject: 1 });
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
});
