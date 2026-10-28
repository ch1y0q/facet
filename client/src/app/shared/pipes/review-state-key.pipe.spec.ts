import { i18nKeys } from '../../core/i18n/keys';
import { ReviewStateKeyPipe } from './review-state-key.pipe';

describe('ReviewStateKeyPipe', () => {
  const pipe = new ReviewStateKeyPipe();
  const I18N = i18nKeys();

  it('reports a rejected photo even when it is also flagged kept', () => {
    expect(pipe.transform([0, 0, 1, 1])).toBe(I18N.organization_history.rejected);
  });

  it('reports a kept photo', () => {
    expect(pipe.transform([0, 0, 0, 1])).toBe(I18N.organization_history.kept);
  });

  it('reports undecided when neither flag is set or the snapshot is empty', () => {
    expect(pipe.transform([0, 0, 0, 0])).toBe(I18N.culling.lightbox.undecided);
    expect(pipe.transform([])).toBe(I18N.culling.lightbox.undecided);
  });
});
