import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { AuthService } from './auth.service';
import { clearPersonAssignmentHistory } from './person-assignment-history.storage';
import { PersonAssignmentHistoryService } from './person-assignment-history.service';

describe('successful person assignment history', () => {
  const identity = signal('1|alice');
  let history: PersonAssignmentHistoryService;
  beforeEach(() => {
    localStorage.removeItem('facet_person_assignments_v1');
    identity.set('1|alice');
    TestBed.configureTestingModule({ providers: [
      { provide: AuthService, useValue: { identity, isEdition: () => true } },
    ] });
    history = TestBed.inject(PersonAssignmentHistoryService);
  });
  it('keeps only bounded, unique IDs in most-recent-success order', () => {
    for (let id = 1; id <= 15; id++) history.record(id, identity());
    history.record(9, identity());
    expect(history.recentIds()).toEqual([9, 15, 14, 13, 12, 11, 10, 8, 7, 6, 5, 4]);
    expect(localStorage.getItem('facet_person_assignments_v1')).not.toContain('name');
  });
  it('isolates owners and ignores a write completed after an account switch', () => {
    history.record(8, identity());
    identity.set('1|bob');
    expect(history.recentIds()).toEqual([]);
    history.record(9, '1|alice');
    history.record(2, identity());
    expect(history.recentIds()).toEqual([2]);
    identity.set('1|alice');
    expect(history.recentIds()).toEqual([8]);
  });
  it('validates persisted data and ignores invalid response IDs', () => {
    localStorage.setItem('facet_person_assignments_v1', JSON.stringify([
      null, { identity: '1|alice', ids: [3, 3, 0, -1, '2', 1.5, null, 7] },
    ]));
    for (const invalid of [0, -1, NaN, Number.MAX_SAFE_INTEGER + 1]) history.record(invalid, identity());
    expect(history.recentIds()).toEqual([3, 7]);
    localStorage.setItem('facet_person_assignments_v1', '{broken');
    expect(history.recentIds()).toEqual([]);
  });
  it('clears all identities on logout and tolerates disabled storage', () => {
    history.record(8, identity());
    identity.set('1|bob');
    history.record(9, identity());
    clearPersonAssignmentHistory();
    expect(history.recentIds()).toEqual([]);
    identity.set('1|alice');
    expect(history.recentIds()).toEqual([]);
    vi.spyOn(Storage.prototype, 'removeItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(() => clearPersonAssignmentHistory()).not.toThrow();
    vi.restoreAllMocks();
  });
  it('does not fail assignments when browser storage is unavailable', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('blocked'); });
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('blocked'); });
    expect(() => history.record(3, identity())).not.toThrow();
    expect(history.recentIds()).toEqual([]);
    vi.restoreAllMocks();
  });
});
