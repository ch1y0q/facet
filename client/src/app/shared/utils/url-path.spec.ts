import { pathOf } from './url-path';

describe('pathOf', () => {
  it('returns a plain path unchanged', () => {
    expect(pathOf('/albums')).toBe('/albums');
  });

  it('drops the query string', () => {
    expect(pathOf('/albums?search=a&b=1')).toBe('/albums');
  });

  it('drops the fragment', () => {
    expect(pathOf('/albums#top')).toBe('/albums');
  });

  it('drops both query string and fragment', () => {
    expect(pathOf('/albums?x=1#top')).toBe('/albums');
  });

  it('returns an empty string for an empty url', () => {
    expect(pathOf('')).toBe('');
  });

  it('returns an empty string when the url starts with a query', () => {
    expect(pathOf('?x=1')).toBe('');
  });
});
