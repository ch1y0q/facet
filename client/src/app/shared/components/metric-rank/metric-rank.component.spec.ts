import { ComponentFixture, TestBed } from '@angular/core/testing';
import { I18nService } from '../../../core/services/i18n.service';
import { MetricRankComponent } from './metric-rank.component';

describe('MetricRankComponent', () => {
  let fixture: ComponentFixture<MetricRankComponent>;

  const mockI18n = {
    t: vi.fn((key: string, vars?: Record<string, string | number>) =>
      Object.entries(vars ?? {}).reduce((out, [k, v]) => `${out} ${k}=${v}`, key)),
    translations: vi.fn(() => ({})),
  };

  function label(value: number | null, percent = false): string | null {
    fixture.componentRef.setInput('range', { min: 0, max: 1, buckets: [1, 2, 4, 3] });
    fixture.componentRef.setInput('value', value);
    fixture.componentRef.setInput('percent', percent);
    fixture.detectChanges();
    return (fixture.nativeElement.querySelector('[tabindex="0"][role="img"]') as HTMLElement).getAttribute('aria-label');
  }

  beforeEach(() => {
    TestBed.configureTestingModule({
      imports: [MetricRankComponent],
      providers: [{ provide: I18nService, useValue: mockI18n }],
    });
    fixture = TestBed.createComponent(MetricRankComponent);
  });

  it('names the rank and the library range of a focusable distribution', () => {
    // 0.6 sits 0.4 into the third bucket: 1 + 2 + 1.6 of 10 photos below, so top 54%.
    expect(label(0.6)).toBe('photo_detail.distribution.top pct=54 · photo_detail.distribution.range min=0 max=1');
    expect(fixture.nativeElement.querySelector('app-metric-sparkline')).not.toBeNull();
  });

  it('shows a fractional metric range as percentages', () => {
    expect(label(0.6, true)).toContain('min=0% max=100%');
  });

  it('names only the range for a value it cannot place', () => {
    expect(label(null)).toBe('Photo_detail.distribution.range min=0 max=1');
  });
});
