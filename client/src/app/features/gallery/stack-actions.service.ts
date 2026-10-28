import { Injectable, inject } from '@angular/core';
import { firstValueFrom } from 'rxjs';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { AuthService } from '../../core/services/auth.service';
import { PhotoStackService } from '../../core/services/photo-stack.service';
import { UndoService } from '../../core/services/undo.service';
import { I18N } from '../../core/i18n/keys';
import { GalleryStore } from './gallery.store';

/** One-step stacking outside the stack editor, with the editor's journal, refresh and Undo. */
@Injectable({ providedIn: 'root' })
export class StackActionsService {
  private readonly stacks = inject(PhotoStackService);
  private readonly journal = inject(UserActivityJournal);
  private readonly store = inject(GalleryStore);
  private readonly undo = inject(UndoService);
  private readonly auth = inject(AuthService);

  /** Rejects when the server refuses; `onUndone` runs only after a successful revert. */
  async create(paths: string[], cover: string, onUndone?: () => void): Promise<void> {
    const session = this.stacks.context();
    const result = await firstValueFrom(this.stacks.create(paths, cover));
    this.journal.record('stack', paths, 'create');
    void this.store.refreshPaths(null);
    const entryId = result.undo?.entry_id;
    if (entryId === undefined) return;
    this.undo.register({
      labelKey: I18N.stacks.stacked, labelParams: { count: paths.length },
      undo: async () => {
        // A snackbar outlives the page and the account that made the stack.
        if (!session() || !this.auth.isEdition()) throw new Error('Stack session expired');
        await firstValueFrom(this.stacks.revert(entryId));
        this.journal.record('stack', paths, 'undo');
        await this.store.refreshPaths(null);
        onUndone?.();
      },
    });
  }
}
