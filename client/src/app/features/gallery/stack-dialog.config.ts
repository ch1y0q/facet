import type { MatDialogConfig } from '@angular/material/dialog';
import type { StackDialogData } from './stack-dialog.component';

/** Shared by gallery, photo/darkroom navigation and the suggestion editor. */
export function stackDialogConfig(data: StackDialogData): MatDialogConfig<StackDialogData> {
  return { data, width: '96vw', maxWidth: '1400px', height: '92dvh', maxHeight: '92dvh',
    autoFocus: 'first-header', restoreFocus: true };
}
