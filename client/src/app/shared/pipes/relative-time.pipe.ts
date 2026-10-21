import { Pipe, PipeTransform } from '@angular/core';

/**
 * "3 minutes ago" for a past timestamp, in the given locale. Pure: pass the ticking `now`
 * as an argument so the text refreshes when it changes and not on every change detection.
 */
@Pipe({ name: 'relativeTime' })
export class RelativeTimePipe implements PipeTransform {
  transform(at: number, now: number, locale: string): string {
    const seconds = Math.max(0, Math.round((now - at) / 1000));
    const format = new Intl.RelativeTimeFormat(locale, { numeric: 'auto' });
    if (seconds < 60) return format.format(-seconds, 'second');
    const minutes = Math.round(seconds / 60);
    if (minutes < 60) return format.format(-minutes, 'minute');
    return format.format(-Math.round(minutes / 60), 'hour');
  }
}
