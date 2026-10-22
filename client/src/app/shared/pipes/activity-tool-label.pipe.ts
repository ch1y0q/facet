import { Pipe, PipeTransform, inject } from '@angular/core';
import { I18nService } from '../../core/services/i18n.service';

/**
 * An activity entry's tool name as a translated past-tense label: `assistant_activity.tools.<mcp tool>` for a
 * write, `assistant_activity.ui.<ui tool>` for a UI call. Falls back to the raw tool name when the key is missing
 * (`I18nService.t` returns the key itself then). Impure like `ScoringContextLabelPipe`: the locale is set before
 * its bundle loads, so a pure pipe keyed on the locale would go stale.
 */
@Pipe({ name: 'activityToolLabel', pure: false })
export class ActivityToolLabelPipe implements PipeTransform {
  private readonly i18n = inject(I18nService);

  transform(tool: string, kind: 'write' | 'ui'): string {
    if (!tool) return '';
    const key = `assistant_activity.${kind === 'ui' ? 'ui' : 'tools'}.${tool}`;
    const translated = this.i18n.t(key);
    return translated === key ? tool : translated;
  }
}
