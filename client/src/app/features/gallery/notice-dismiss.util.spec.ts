import { MAX_DISMISSALS_PER_KIND, NoticeDismissals, NOTICE_DISMISSALS_KEY, readNoticeDismissals, saveNoticeDismissals, withDismissal } from './notice-dismiss.util';

describe('notice dismissals', () => {
  afterEach(() => { vi.restoreAllMocks(); sessionStorage.removeItem(NOTICE_DISMISSALS_KEY); });

  it('round-trips a saved record', () => {
    saveNoticeDismissals({ hidden: ['12'], review_progress: ['{"tag":"a"}', '{"tag":"b"}'] });
    expect(readNoticeDismissals()).toEqual({ hidden: ['12'], review_progress: ['{"tag":"a"}', '{"tag":"b"}'] });
  });

  it('drops kinds that do not hold a list and entries that are not strings', () => {
    sessionStorage.setItem(NOTICE_DISMISSALS_KEY, JSON.stringify({ hidden: '12', review_progress: ['a', 3, null] }));
    expect(readNoticeDismissals()).toEqual({ review_progress: ['a'] });
  });

  it('keeps the most recent signatures per kind, oldest dropped past the cap', () => {
    let record: NoticeDismissals = {};
    for (let i = 0; i <= MAX_DISMISSALS_PER_KIND; i++) record = withDismissal(record, 'hidden', `s${i}`);
    record = withDismissal(record, 'hidden', 's1');
    const hidden = record.hidden!;
    expect(hidden).toHaveLength(MAX_DISMISSALS_PER_KIND);
    expect(hidden).not.toContain('s0');
    expect(hidden.at(-1)).toBe('s1');
    expect(hidden.filter(s => s === 's1')).toHaveLength(1);
  });

  it.each([['absent', null], ['null', 'null'], ['an array', '[]'], ['a string', '"x"'], ['a number', '3'], ['malformed JSON', '{bad']])(
    'reads %s as no dismissals', (_, stored) => {
      if (stored !== null) sessionStorage.setItem(NOTICE_DISMISSALS_KEY, stored);
      expect(readNoticeDismissals()).toEqual({});
    });

  it('reads no dismissals when storage access throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new DOMException('denied', 'SecurityError'); });
    expect(readNoticeDismissals()).toEqual({});
  });

  it('swallows a storage write failure', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new DOMException('full', 'QuotaExceededError'); });
    expect(() => saveNoticeDismissals({ hidden: ['1'] })).not.toThrow();
  });
});
