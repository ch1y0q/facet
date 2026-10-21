import { TestBed } from '@angular/core/testing';
import { HttpClient } from '@angular/common/http';
import { of } from 'rxjs';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from './translate.pipe';
import { ReviewAriaKeyPipe, ReviewChangedPipe, ReviewGroupHeaderPipe, ReviewGroupPipe, ReviewMarkPipe } from './review.pipes';

describe('review pipes', () => {
  it('prefers the user mark over the assistant mark', () => {
    const pipe = new ReviewMarkPipe();
    expect(pipe.transform('/a', new Map([['/a', 'keep']]), new Map([['/a', 'remove']]))).toBe('keep');
    expect(pipe.transform('/a', new Map(), new Map([['/a', 'remove']]))).toBe('remove');
    expect(pipe.transform('/b', new Map(), new Map())).toBeNull();
  });

  it('looks up the group number', () => {
    const pipe = new ReviewGroupPipe();
    expect(pipe.transform('/a', new Map([['/a', 3]]))).toBe(3);
    expect(pipe.transform('/b', new Map())).toBeNull();
  });

  it('flags a photo whose user mark differs from the assistant mark', () => {
    const pipe = new ReviewChangedPipe();
    expect(pipe.transform('/a', new Map([['/a', 'keep']]), new Map([['/a', 'remove']]))).toBe(true);
    expect(pipe.transform('/a', new Map([['/a', 'keep']]), new Map([['/a', 'keep']]))).toBe(false);
    expect(pipe.transform('/a', new Map(), new Map([['/a', 'keep']]))).toBe(false);
    expect(pipe.transform('/a', new Map([['/a', 'keep']]), new Map())).toBe(false);
  });

  describe('ReviewGroupHeaderPipe', () => {
    const pipe = new ReviewGroupHeaderPipe();
    const counts = new Map([[2, { count: 3, keep: 1, remove: 2 }], [5, { count: 1, keep: 1, remove: 0 }]]);

    it('describes a plural header with the effective counts', () => {
      expect(pipe.transform(2, counts, true)).toEqual({
        key: 'gallery.pinned.review.group_header_plural',
        params: { group: 2, count: 3, keep: 1, remove: 2 },
      });
    });

    it('uses the singular key for one photo', () => {
      expect(pipe.transform(5, counts, true).key).toBe('gallery.pinned.review.group_header');
    });

    it('shows the title only when the pin carries no marks', () => {
      expect(pipe.transform(2, counts, false)).toEqual({
        key: 'gallery.pinned.review.group_title', params: { group: 2 },
      });
    });
  });
});

describe('ReviewAriaKeyPipe', () => {
  it('picks the grouped key only when there is a group', () => {
    const pipe = new ReviewAriaKeyPipe();
    expect(pipe.transform('keep', 3)).toBe('gallery.pinned.review.keep_aria');
    expect(pipe.transform('remove', null)).toBe('gallery.pinned.review.remove_aria_ungrouped');
  });
});

describe('ReviewGroupHeaderPipe through the real i18n bundles', () => {
  const header = new ReviewGroupHeaderPipe();
  const counts = new Map([[2, { count: 3, keep: 1, remove: 2 }], [5, { count: 1, keep: 1, remove: 0 }]]);

  async function render(lang: string, group: number): Promise<string> {
    const bundle = (await import(`../../../../../i18n/translations/${lang}.json`)).default as Record<string, unknown>;
    TestBed.configureTestingModule({
      providers: [{ provide: HttpClient, useValue: { get: () => of(bundle) } }],
    });
    const i18n = TestBed.inject(I18nService);
    await i18n.setLocale(lang);
    const { key, params } = header.transform(group, counts, true);
    return TestBed.runInInjectionContext(() => new TranslatePipe().transform(key, params));
  }

  it.each([
    ['en', 2, 'Group 2 \u2014 3 photos \u00b7 1 keep \u00b7 2 remove'],
    ['en', 5, 'Group 5 \u2014 1 photo \u00b7 1 keep \u00b7 0 remove'],
    ['fr', 2, 'Groupe 2 \u2014 3 photos \u00b7 1 \u00e0 garder \u00b7 2 \u00e0 retirer'],
    ['fr', 5, 'Groupe 5 \u2014 1 photo \u00b7 1 \u00e0 garder \u00b7 0 \u00e0 retirer'],
  ])('%s group %i renders %s', async (lang, group, expected) => {
    expect(await render(lang, group)).toBe(expected);
  });
});
