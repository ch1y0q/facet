import { TestBed } from '@angular/core/testing';
import { HttpClient } from '@angular/common/http';
import { of } from 'rxjs';
import { I18nService } from '../../core/services/i18n.service';
import { TranslatePipe } from './translate.pipe';
import {
  ReviewAriaKeyPipe, ReviewChangedPipe, ReviewGroupHeaderPipe, ReviewGroupKeptWholePipe, ReviewGroupLabelPipe,
  ReviewGroupPipe, ReviewMarkPipe, ReviewReasonPipe,
  ReviewApplyPlanPipe, ReviewGroupAppliedPipe, ReviewGroupReceiptPipe, ReviewPathLockedPipe, ReviewReceiptLabelPipe, ReviewReceiptTitlePipe,
} from './review.pipes';
import type { AppliedGroup, AppliedMark, AppliedReceipt, ApplyUnit } from '../../features/gallery/gallery.store';

describe('review pipes', () => {
  it('prefers the user mark over the assistant mark', () => {
    const pipe = new ReviewMarkPipe();
    expect(pipe.transform('/a', new Map([['/a', 'keep']]), new Map([['/a', 'remove']]))).toBe('keep');
    expect(pipe.transform('/a', new Map(), new Map([['/a', 'remove']]))).toBe('remove');
    expect(pipe.transform('/b', new Map(), new Map())).toBeNull();
  });

  it('shows the applied mark over the user and assistant marks (a frame kept whole reads Keep)', () => {
    const pipe = new ReviewMarkPipe();
    const applied = new Map([['/a', { mark: 'keep' as const, receiptId: 'r' }]]);
    expect(pipe.transform('/a', new Map([['/a', 'remove']]), new Map([['/a', 'remove']]), applied)).toBe('keep');
    expect(pipe.transform('/b', new Map([['/b', 'remove']]), new Map(), applied)).toBe('remove');
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

describe('ReviewGroupLabelPipe', () => {
  const pipe = new ReviewGroupLabelPipe();
  const labels = new Map([[1, { key: 'bracket_span', params: { frames: 4, ev_span: 1.3 } }]]);

  it('maps the server key to the culling.group_reason bundle key and keeps the params', () => {
    expect(pipe.transform(1, labels)).toEqual({ key: 'culling.group_reason.bracket_span', params: { frames: 4, ev_span: 1.3 } });
  });

  it('is null for a group without a label', () => {
    expect(pipe.transform(2, labels)).toBeNull();
  });

  it.each([
    ['en', '4 frames, 1.3 EV span'],
    ['fr', '4 vues, écart de 1.3 IL'],
  ])('renders %s through the real bundle', async (lang, expected) => {
    const bundle = (await import(`../../../../../i18n/translations/${lang}.json`)).default as Record<string, unknown>;
    TestBed.configureTestingModule({ providers: [{ provide: HttpClient, useValue: { get: () => of(bundle) } }] });
    await TestBed.inject(I18nService).setLocale(lang);
    const { key, params } = pipe.transform(1, labels)!;
    expect(TestBed.runInInjectionContext(() => new TranslatePipe().transform(key, params))).toBe(expected);
  });

  it('interpolates the moment text as data, never as markup', async () => {
    const bundle = (await import('../../../../../i18n/translations/en.json')).default as Record<string, unknown>;
    TestBed.configureTestingModule({ providers: [{ provide: HttpClient, useValue: { get: () => of(bundle) } }] });
    await TestBed.inject(I18nService).setLocale('en');
    const label = pipe.transform(1, new Map([[1, { key: 'moment', params: { moment: '<b>Toast</b>' } }]]))!;
    expect(TestBed.runInInjectionContext(() => new TranslatePipe().transform(label.key, label.params))).toBe('<b>Toast</b>');
  });
});

describe('ReviewReasonPipe', () => {
  const pipe = new ReviewReasonPipe();

  it('hands the cull-reason pipe a {key, value}, with a null value when the server sent none', () => {
    const reasons = new Map([['/a', { key: 'soft', value: 2 }], ['/b', { key: 'best' }]]);
    expect(pipe.transform('/a', reasons)).toEqual({ key: 'soft', value: 2 });
    expect(pipe.transform('/b', reasons)).toEqual({ key: 'best', value: null });
    expect(pipe.transform('/c', reasons)).toBeNull();
  });
});

describe('ReviewGroupKeptWholePipe', () => {
  const pipe = new ReviewGroupKeptWholePipe();

  it.each([['bracket', true], ['panorama', true], ['hdr_panorama', true], ['burst', false], ['similar', false], ['scene', false]])(
    '%s is kept whole: %s', (kind, whole) => {
      expect(pipe.transform(1, new Map([[1, kind]]))).toBe(whole);
    });

  it('is false for a group without a kind', () => {
    expect(pipe.transform(1, new Map())).toBe(false);
  });
});

describe('apply pipes', () => {
  const group: AppliedGroup = { receiptId: 'r1', keptWhole: 2, unavailable: false };
  const receipt = (over: Partial<AppliedReceipt> = {}): AppliedReceipt => ({
    receiptId: 'r1', paths: ['/a.jpg'], group: 3, kind: 'burst', label: null, firstFilename: 'a.jpg', skippedKeepWhole: [], ...over,
  });

  it('ReviewPathLockedPipe is true only for a path in the applied record', () => {
    const pipe = new ReviewPathLockedPipe();
    const applied = new Map<string, AppliedMark>([['/a.jpg', { mark: 'keep', receiptId: 'r1' }]]);
    expect(pipe.transform('/a.jpg', applied)).toBe(true);
    expect(pipe.transform('/b.jpg', applied)).toBe(false);
    expect(pipe.transform('/a.jpg', new Map())).toBe(false);
  });

  it('ReviewGroupAppliedPipe / ReviewGroupReceiptPipe read the applied groups', () => {
    const groups = new Map([[3, group]]);
    expect(new ReviewGroupAppliedPipe().transform(3, groups)).toBe(true);
    expect(new ReviewGroupAppliedPipe().transform(4, groups)).toBe(false);
    expect(new ReviewGroupReceiptPipe().transform(3, groups)).toBe(group);
    expect(new ReviewGroupReceiptPipe().transform(4, groups)).toBeNull();
  });

  it('ReviewApplyPlanPipe returns the unit of a group, else null', () => {
    const unit: ApplyUnit = { group: 1, kind: 'burst', ungrouped: false, keep: ['/a'], reject: [], unreject: [] };
    expect(new ReviewApplyPlanPipe().transform(1, new Map([[1, unit]]))).toBe(unit);
    expect(new ReviewApplyPlanPipe().transform(2, new Map([[1, unit]]))).toBeNull();
  });

  it('ReviewReceiptLabelPipe prefers the assistant label, then the group title, then the marks-only text', () => {
    const pipe = new ReviewReceiptLabelPipe();
    expect(pipe.transform(receipt({ label: { key: 'burst', params: { n: 2 } } }))).toEqual({ key: 'culling.group_reason.burst', params: { n: 2 } });
    expect(pipe.transform(receipt())).toEqual({ key: 'gallery.pinned.review.group_title', params: { group: 3 } });
    expect(pipe.transform(receipt({ group: null }))).toEqual({ key: 'gallery.pinned.review.applied_marks_only', params: {} });
  });

  it('ReviewReceiptTitlePipe gives the group number only when a heading also names the entry', () => {
    const pipe = new ReviewReceiptTitlePipe();
    expect(pipe.transform(receipt({ label: { key: 'burst', params: {} } }))).toEqual({ key: 'gallery.pinned.review.group_title', params: { group: 3 } });
    expect(pipe.transform(receipt())).toBeNull();
    expect(pipe.transform(receipt({ group: null, label: { key: 'burst', params: {} } }))).toBeNull();
  });
});
