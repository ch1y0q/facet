import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MetricSparklineComponent } from './metric-sparkline.component';

describe('MetricSparklineComponent', () => {
  let fixture: ComponentFixture<MetricSparklineComponent>;

  function dimmed(value?: number | null): boolean[] {
    fixture.componentRef.setInput('range', { min: 0, max: 10, buckets: [1, 2, 4, 3] });
    if (value !== undefined) fixture.componentRef.setInput('value', value);
    fixture.detectChanges();
    return Array.from(fixture.nativeElement.querySelectorAll('span') as NodeListOf<HTMLElement>)
      .map(bar => bar.classList.contains('opacity-25'));
  }

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [MetricSparklineComponent] });
    fixture = TestBed.createComponent(MetricSparklineComponent);
  });

  it('draws every bucket dimmed without a value', () => {
    expect(dimmed()).toEqual([true, true, true, true]);
  });

  it('lights the bucket the value falls in', () => {
    expect(dimmed(6)).toEqual([true, true, false, true]);
  });

  it('is decorative', () => {
    dimmed(6);
    expect(fixture.nativeElement.querySelector('div').getAttribute('aria-hidden')).toBe('true');
  });
});
