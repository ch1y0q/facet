import { Pipe, PipeTransform } from '@angular/core';

/** `ui_show_photos` -> "Show photos": the tool name as a sentence, without the `ui_` prefix. */
@Pipe({ name: 'activityToolLabel' })
export class ActivityToolLabelPipe implements PipeTransform {
  transform(tool: string): string {
    const words = tool.replace(/^ui_/, '').replace(/_/g, ' ').trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
  }
}
