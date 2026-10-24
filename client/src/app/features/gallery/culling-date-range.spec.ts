import { describe, it, expect, afterEach } from 'vitest';
import { CULL_DATE_PRESETS, presetRange, parseScopeDate } from './culling-date-range';

describe('presetRange', () => {
  const today = new Date(2026, 9, 23);

  it('lists the four presets', () => {
    expect(CULL_DATE_PRESETS.map(p => p.id)).toEqual(['last_7_days', 'last_30_days', 'this_year', 'last_year']);
  });

  it('last 7 days spans today and the six before', () => {
    expect(presetRange('last_7_days', today)).toEqual({ from: '2026-10-17', to: '2026-10-23' });
  });

  it('last 30 days spans today and the 29 before', () => {
    expect(presetRange('last_30_days', today)).toEqual({ from: '2026-09-24', to: '2026-10-23' });
  });

  it('this year and last year cover whole calendar years', () => {
    expect(presetRange('this_year', today)).toEqual({ from: '2026-01-01', to: '2026-12-31' });
    expect(presetRange('last_year', today)).toEqual({ from: '2025-01-01', to: '2025-12-31' });
  });

  it('crosses a year boundary', () => {
    expect(presetRange('last_7_days', new Date(2026, 0, 3))).toEqual({ from: '2025-12-28', to: '2026-01-03' });
  });

  it('crosses a leap day', () => {
    expect(presetRange('last_7_days', new Date(2028, 2, 2))).toEqual({ from: '2028-02-25', to: '2028-03-02' });
  });

  it('this year on January 1st', () => {
    expect(presetRange('this_year', new Date(2026, 0, 1))).toEqual({ from: '2026-01-01', to: '2026-12-31' });
  });

  it('does not mutate the input date', () => {
    const d = new Date(2026, 9, 23, 14, 5);
    presetRange('last_30_days', d);
    expect(d.getTime()).toBe(new Date(2026, 9, 23, 14, 5).getTime());
  });

  describe('across a DST change', () => {
    // The test runner is Node; its typings are not part of this project, so reach `process` through globalThis.
    const env = (globalThis as unknown as { process: { env: Record<string, string | undefined> } }).process.env;
    const original = env['TZ'];
    afterEach(() => {
      if (original === undefined) delete env['TZ'];
      else env['TZ'] = original;
    });

    it('counts calendar days, not 24-hour blocks', () => {
      env['TZ'] = 'Europe/Paris';
      // Switching TZ at runtime works in Node's main thread and forks (the Vitest default pool), not in worker
      // threads. Fail loudly, rather than pass for a millisecond implementation, if the switch did not take.
      expect(new Date(2026, 2, 24, 12).getTimezoneOffset()).not.toBe(new Date(2026, 2, 30, 12).getTimezoneOffset());
      expect(presetRange('last_7_days', new Date(2026, 2, 30, 0, 30))).toEqual({ from: '2026-03-24', to: '2026-03-30' });
    });
  });
});

describe('parseScopeDate', () => {
  it('reads an ISO date as local midnight', () => {
    const d = parseScopeDate('2026-07-01');
    expect(d).toEqual(new Date(2026, 6, 1));
  });

  it('reads the EXIF form with and without a time', () => {
    expect(parseScopeDate('2026:07:31 23:59:59')).toEqual(new Date(2026, 6, 31));
    expect(parseScopeDate('2026:07:31')).toEqual(new Date(2026, 6, 31));
  });

  it('returns null for null, empty and garbage', () => {
    expect(parseScopeDate(null)).toBeNull();
    expect(parseScopeDate('')).toBeNull();
    expect(parseScopeDate('yesterday')).toBeNull();
    expect(parseScopeDate('2026-13-45')).toBeNull();
  });
});
