import { normalizeOnlineQuery } from './online-query';

describe('normalizeOnlineQuery', () => {
  it('requires at least 3 code points', () => {
    expect(normalizeOnlineQuery('ab')).toBeNull();
    expect(normalizeOnlineQuery('abc')).toBe('abc');
  });

  it('accepts 200 code points and refuses 201', () => {
    expect(normalizeOnlineQuery('a'.repeat(200))).toBe('a'.repeat(200));
    expect(normalizeOnlineQuery('a'.repeat(201))).toBeNull();
  });

  it('counts astral characters as one code point, not two UTF-16 units', () => {
    expect(normalizeOnlineQuery('😀'.repeat(200))).toBe('😀'.repeat(200));
    expect(normalizeOnlineQuery('😀'.repeat(201))).toBeNull();
    expect(normalizeOnlineQuery('😀😀')).toBeNull();
    expect(normalizeOnlineQuery('😀😀😀')).toBe('😀😀😀');
  });

  it('applies both bounds to the trimmed text', () => {
    expect(normalizeOnlineQuery('  ab  ')).toBeNull();
    expect(normalizeOnlineQuery('  abc  ')).toBe('abc');
    expect(normalizeOnlineQuery(` ${'a'.repeat(200)}`)).toBe('a'.repeat(200));
    expect(normalizeOnlineQuery(` ${'a'.repeat(201)}`)).toBeNull();
    expect(normalizeOnlineQuery(`${'a'.repeat(198)}  `)).toBe('a'.repeat(198));
  });

  it('refuses control characters in the trimmed text', () => {
    expect(normalizeOnlineQuery('ab\u0000c')).toBeNull();
    expect(normalizeOnlineQuery('ab\nc')).toBeNull();
    expect(normalizeOnlineQuery('abc\n')).toBe('abc');
  });
});
