import { RelativeTimePipe } from './relative-time.pipe';

describe('RelativeTimePipe', () => {
  const pipe = new RelativeTimePipe();
  const now = 1_000_000_000;

  it('formats seconds, minutes and hours in the locale', () => {
    expect(pipe.transform(now - 5_000, now, 'en')).toBe('5 seconds ago');
    expect(pipe.transform(now - 120_000, now, 'en')).toBe('2 minutes ago');
    expect(pipe.transform(now - 3 * 3_600_000, now, 'en')).toBe('3 hours ago');
    expect(pipe.transform(now - 120_000, now, 'fr')).toBe('il y a 2 minutes');
  });

  it('never goes into the future', () => {
    expect(pipe.transform(now + 9_000, now, 'en')).toBe('now');
  });
});
