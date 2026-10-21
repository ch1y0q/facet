import { ActivityToolLabelPipe } from './activity-tool-label.pipe';

describe('ActivityToolLabelPipe', () => {
  const pipe = new ActivityToolLabelPipe();

  it('turns a tool name into a sentence', () => {
    expect(pipe.transform('ui_show_photos')).toBe('Show photos');
    expect(pipe.transform('set_rating')).toBe('Set rating');
  });

  it('returns an empty string for an empty name', () => {
    expect(pipe.transform('')).toBe('');
  });
});
