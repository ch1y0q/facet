import { NOTICE_DISMISSALS_KEY, readNoticeDismissals, saveNoticeDismissals } from './notice-dismiss.util';

describe('notice dismissals', () => {
  afterEach(() => { vi.restoreAllMocks(); sessionStorage.removeItem(NOTICE_DISMISSALS_KEY); });

  it('round-trips a saved record', () => {
    saveNoticeDismissals({ hidden: '12', review_progress: '{"tag":"a"}' });
    expect(readNoticeDismissals()).toEqual({ hidden: '12', review_progress: '{"tag":"a"}' });
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
    expect(() => saveNoticeDismissals({ hidden: '1' })).not.toThrow();
  });
});
