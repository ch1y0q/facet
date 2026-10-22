import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { I18nService } from '../../core/services/i18n.service';
import { ActivityToolLabelPipe } from './activity-tool-label.pipe';

describe('ActivityToolLabelPipe', () => {
  const dict = signal<Record<string, string>>({
    'assistant_activity.tools.set_rejected': 'Rejected photos',
    'assistant_activity.ui.ui_show_photos': 'Showed photos',
  });
  let pipe: ActivityToolLabelPipe;

  beforeEach(() => {
    TestBed.configureTestingModule({
      providers: [{ provide: I18nService, useValue: { t: (key: string) => dict()[key] ?? key } }],
    });
    pipe = TestBed.runInInjectionContext(() => new ActivityToolLabelPipe());
  });

  afterEach(() => TestBed.resetTestingModule());

  it('translates a write tool under assistant_activity.tools', () => {
    expect(pipe.transform('set_rejected', 'write')).toBe('Rejected photos');
  });

  it('translates a ui tool under assistant_activity.ui, distinct from the Show photos button', () => {
    expect(pipe.transform('ui_show_photos', 'ui')).toBe('Showed photos');
  });

  it('falls back to the raw tool name when the key is missing', () => {
    expect(pipe.transform('brand_new_tool', 'write')).toBe('brand_new_tool');
    expect(pipe.transform('ui_new_thing', 'ui')).toBe('ui_new_thing');
  });

  it('follows a locale switch', () => {
    expect(pipe.transform('set_rejected', 'write')).toBe('Rejected photos');
    dict.set({ 'assistant_activity.tools.set_rejected': 'Photos rejetees' });
    expect(pipe.transform('set_rejected', 'write')).toBe('Photos rejetees');
  });

  it('returns an empty string for an empty name', () => {
    expect(pipe.transform('', 'write')).toBe('');
  });
});
