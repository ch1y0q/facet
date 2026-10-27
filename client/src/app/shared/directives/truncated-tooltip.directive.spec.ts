import { Component, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { By } from '@angular/platform-browser';
import { MatTooltip } from '@angular/material/tooltip';
import { TruncatedTooltipDirective } from './truncated-tooltip.directive';

@Component({
  imports: [TruncatedTooltipDirective],
  template: `<div [appTruncatedTooltip]="text()">{{ text() }}</div>`,
})
class HostComponent {
  readonly text = signal('A long caption');
}

describe('TruncatedTooltipDirective', () => {
  function render(scrollHeight: number, clientHeight: number) {
    const fixture = TestBed.createComponent(HostComponent);
    const el = fixture.debugElement.query(By.directive(TruncatedTooltipDirective));
    Object.defineProperty(el.nativeElement, 'scrollHeight', { configurable: true, get: () => scrollHeight });
    Object.defineProperty(el.nativeElement, 'clientHeight', { configurable: true, get: () => clientHeight });
    fixture.detectChanges();
    TestBed.tick();
    return { fixture, tooltip: el.injector.get(MatTooltip) };
  }

  it('offers the full text while the element is clipped', () => {
    const { tooltip } = render(60, 32);
    expect(tooltip.disabled).toBe(false);
    expect(tooltip.message).toBe('A long caption');
  });

  it('stays silent when the text fits', () => {
    const { tooltip } = render(32, 32);
    expect(tooltip.disabled).toBe(true);
  });

  it('follows a text change', () => {
    const { fixture, tooltip } = render(60, 32);
    fixture.componentInstance.text.set('Another caption');
    fixture.detectChanges();
    TestBed.tick();
    expect(tooltip.message).toBe('Another caption');
  });

  it('stops observing resizes once destroyed', () => {
    const disconnect = vi.fn();
    const original = globalThis.ResizeObserver;
    globalThis.ResizeObserver = class {
      observe = vi.fn();
      unobserve = vi.fn();
      disconnect = disconnect;
    } as unknown as typeof ResizeObserver;
    try {
      const { fixture } = render(32, 32);
      fixture.destroy();
      expect(disconnect).toHaveBeenCalledTimes(1);
    } finally {
      globalThis.ResizeObserver = original;
    }
  });
});
