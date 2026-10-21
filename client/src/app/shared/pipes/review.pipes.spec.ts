import { ReviewGroupPipe, ReviewMarkPipe } from './review.pipes';

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
});
