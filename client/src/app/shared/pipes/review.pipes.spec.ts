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
