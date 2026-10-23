import { toIsoDateString, plainScopeDate } from './date-format';

describe('toIsoDateString', () => {
  it('returns an empty string for null', () => {
    expect(toIsoDateString(null)).toBe('');
  });

  it('formats a date as YYYY-MM-DD using local components', () => {
    // Use local-component constructor so the test is timezone-independent:
    // the function reads getFullYear / getMonth / getDate (local time).
    const d = new Date(2026, 5, 17); // June (month index 5)
    expect(toIsoDateString(d)).toBe('2026-06-17');
  });

  it('zero-pads single-digit months and days', () => {
    const d = new Date(2026, 0, 5); // January 5
    expect(toIsoDateString(d)).toBe('2026-01-05');
  });

  it('handles December (month index 11 -> 12)', () => {
    const d = new Date(1999, 11, 31);
    expect(toIsoDateString(d)).toBe('1999-12-31');
  });

  it('handles the first day of the year', () => {
    const d = new Date(2000, 0, 1);
    expect(toIsoDateString(d)).toBe('2000-01-01');
  });

  it('does not pad four-digit years', () => {
    const d = new Date(2026, 9, 9); // October 9
    expect(toIsoDateString(d)).toBe('2026-10-09');
  });
});

describe('plainScopeDate', () => {
  it('turns a whole-day EXIF edge into a plain date', () => {
    expect(plainScopeDate('2025:04:14 00:00:00', 'from')).toBe('2025-04-14');
    expect(plainScopeDate('2025:04:15 23:59:59', 'to')).toBe('2025-04-15');
  });

  it('keeps an edge that is not the day\'s own start or end, and anything else', () => {
    expect(plainScopeDate('2025:04:14 10:00:00', 'from')).toBe('2025:04:14 10:00:00');
    expect(plainScopeDate('2025:04:15 00:00:00', 'to')).toBe('2025:04:15 00:00:00');
    expect(plainScopeDate('2025-04-14', 'from')).toBe('2025-04-14');
    expect(plainScopeDate(null, 'to')).toBeNull();
    expect(plainScopeDate(undefined, 'to')).toBeNull();
  });
});
