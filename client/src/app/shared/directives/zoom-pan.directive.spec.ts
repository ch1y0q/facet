import { ChangeDetectionStrategy, Component, signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { ZoomPanDirective } from './zoom-pan.directive';

@Component({
  selector: 'app-zoom-host',
  imports: [ZoomPanDirective],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <div [appZoomPan]="key()" #zoom="zoomPan">
      <img alt="" [style.transform]="zoom.transform()" />
    </div>
  `,
})
class ZoomHostComponent {
  readonly key = signal('a');
}

describe('ZoomPanDirective', () => {
  let fixture: ComponentFixture<ZoomHostComponent>;
  let panel: HTMLElement;
  let img: HTMLImageElement;

  const wheel = (deltaY: number) => {
    const event = new WheelEvent('wheel', { deltaY, cancelable: true });
    panel.dispatchEvent(event);
    fixture.detectChanges();
    return event;
  };

  const pointer = (type: string, clientX: number, clientY: number) => {
    panel.dispatchEvent(new PointerEvent(type, { clientX, clientY, pointerId: 1, bubbles: true }));
    fixture.detectChanges();
  };

  beforeEach(() => {
    TestBed.configureTestingModule({ imports: [ZoomHostComponent] });
    fixture = TestBed.createComponent(ZoomHostComponent);
    fixture.detectChanges();
    panel = fixture.nativeElement.querySelector('div');
    img = fixture.nativeElement.querySelector('img');
  });

  afterEach(() => TestBed.resetTestingModule());

  it('zooms with the wheel within 0.5x and 5x and keeps the page from scrolling', () => {
    const event = wheel(-1);
    expect(event.defaultPrevented).toBe(true);
    expect(img.style.transform).toBe('scale(1.15) translate(0px, 0px)');
    for (let i = 0; i < 40; i++) wheel(-1);
    expect(img.style.transform).toBe('scale(5) translate(0px, 0px)');
    for (let i = 0; i < 80; i++) wheel(1);
    expect(img.style.transform).toBe('scale(0.5) translate(0px, 0px)');
  });

  it('pans only while zoomed in, clamped to the panel', () => {
    Object.defineProperty(panel, 'clientWidth', { value: 400 });
    Object.defineProperty(panel, 'clientHeight', { value: 300 });
    pointer('pointerdown', 0, 0);
    pointer('pointermove', 50, 0);
    pointer('pointerup', 50, 0);
    expect(img.style.transform).toBe('');
    let scale = 1;
    for (let i = 0; i < 7; i++) { wheel(-1); scale += 0.15; }
    pointer('pointerdown', 0, 0);
    expect(panel.classList).toContain('cursor-grabbing');
    pointer('pointermove', 10000, 0);
    pointer('pointerup', 10000, 0);
    expect(panel.classList).not.toContain('cursor-grabbing');
    expect(img.style.transform).toBe(`scale(${scale}) translate(${400 / (2 * scale)}px, 0px)`);
  });

  it('resets on double-click and when the bound value changes', () => {
    wheel(-1);
    panel.dispatchEvent(new MouseEvent('dblclick'));
    fixture.detectChanges();
    expect(img.style.transform).toBe('');
    wheel(-1);
    fixture.componentInstance.key.set('b');
    fixture.detectChanges();
    expect(img.style.transform).toBe('');
  });
});
