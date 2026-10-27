import { TestBed } from '@angular/core/testing';
import { DEFAULT_KEYMAP, KeyboardMappingService } from './keyboard-mapping.service';

describe('KeyboardMappingService', () => {
  const stored = (): unknown => JSON.parse(localStorage.getItem('facet_keymap')!);

  afterEach(() => localStorage.removeItem('facet_keymap'));

  it('defaults to the built-in bindings when nothing is saved', () => {
    expect(TestBed.inject(KeyboardMappingService).keymap()).toEqual(DEFAULT_KEYMAP);
  });

  it('lowercases a captured key and persists it per browser', () => {
    const service = TestBed.inject(KeyboardMappingService);
    service.setKey('reject', 'R');
    expect(service.key('reject')).toBe('r');
    expect(stored()).toEqual({ ...DEFAULT_KEYMAP, reject: 'r' });
  });

  it('updates the live signal the page handlers read', () => {
    const service = TestBed.inject(KeyboardMappingService);
    const before = service.keymap().favourite;
    service.setKey('favourite', 'z');
    expect(service.keymap().favourite).toBe('z');
    expect(before).toBe(DEFAULT_KEYMAP.favourite);
  });

  it('falls back to the defaults for malformed saved values', () => {
    localStorage.setItem('facet_keymap', JSON.stringify({ favourite: 'ZZ', reject: 7, keep: true, focusSearch: '//', toggleSidebar: 'w' }));
    const service = TestBed.inject(KeyboardMappingService);
    expect(service.key('favourite')).toBe(DEFAULT_KEYMAP.favourite);
    expect(service.key('reject')).toBe(DEFAULT_KEYMAP.reject);
    expect(service.key('keep')).toBe(DEFAULT_KEYMAP.keep);
    expect(service.key('focusSearch')).toBe(DEFAULT_KEYMAP.focusSearch);
    expect(service.key('toggleSidebar')).toBe('w');
  });

  it('falls back to the defaults for unparsable storage', () => {
    localStorage.setItem('facet_keymap', '{not json');
    expect(TestBed.inject(KeyboardMappingService).keymap()).toEqual(DEFAULT_KEYMAP);
  });

  it('resetAll restores every default and persists them', () => {
    const service = TestBed.inject(KeyboardMappingService);
    service.setKey('reject', 'r');
    service.resetAll();
    expect(service.keymap()).toEqual(DEFAULT_KEYMAP);
    expect(stored()).toEqual(DEFAULT_KEYMAP);
  });
});
