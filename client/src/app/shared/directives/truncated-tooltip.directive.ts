import { DestroyRef, Directive, ElementRef, afterRenderEffect, inject, input } from '@angular/core';
import { MatTooltip } from '@angular/material/tooltip';

/**
 * Shows the full text in a tooltip, but only while the element is clipped
 * (truncate, line-clamp): a tooltip repeating text that is already fully
 * visible is noise. Re-measured when the text changes and on every resize.
 */
@Directive({
  selector: '[appTruncatedTooltip]',
  hostDirectives: [MatTooltip],
})
export class TruncatedTooltipDirective {
  readonly appTruncatedTooltip = input<string | null | undefined>('');

  private readonly tooltip = inject(MatTooltip);
  private readonly el: HTMLElement = inject(ElementRef).nativeElement;

  constructor() {
    // Measure before writing: the tooltip state must not be set in a read phase.
    afterRenderEffect({
      earlyRead: () => this.measure(),
      write: state => this.apply(state()),
    });
    if (typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => this.apply(this.measure()));
    observer.observe(this.el);
    inject(DestroyRef).onDestroy(() => observer.disconnect());
  }

  private measure(): { text: string; clipped: boolean } {
    return {
      text: this.appTruncatedTooltip() ?? '',
      clipped: this.el.scrollHeight > this.el.clientHeight || this.el.scrollWidth > this.el.clientWidth,
    };
  }

  private apply({ text, clipped }: { text: string; clipped: boolean }): void {
    this.tooltip.message = text;
    this.tooltip.disabled = !clipped;
  }
}
