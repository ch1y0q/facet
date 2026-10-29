import type { MatDialogConfig } from '@angular/material/dialog';
import type { StackEditorData } from './stack-editor-host';

/** Shared by gallery, photo/darkroom navigation and the suggestion editor. */
export function stackDialogConfig(data: StackEditorData): MatDialogConfig<StackEditorData> {
  return { data, width: '96vw', maxWidth: '1400px', height: '92dvh', maxHeight: '92dvh',
    autoFocus: 'first-header', restoreFocus: true };
}
