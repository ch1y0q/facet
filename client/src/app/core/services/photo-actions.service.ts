import { Injectable, inject } from '@angular/core';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { Photo } from '../../shared/models/photo.model';
import { GalleryStore } from '../../features/gallery/gallery.store';
import { ExportService } from './export.service';
import { I18nService } from './i18n.service';
import { ApiService } from './api.service';
import { I18N } from '../i18n/keys';

/** `POST /api/photo/delete` response — per-path, see `api.routers.export.api_photo_delete`. */
export interface PhotoDeleteResponse {
  dry_run: boolean;
  would_trash?: string[] | null;
  deleted: string[];
  not_found: string[];
  not_visible: string[];
  refused_bracket_lead: string[];
  sequence_siblings: string[];
  trashed: number;
  errors: Record<string, string>;
}

@Injectable({ providedIn: 'root' })
export class PhotoActionsService {
  private readonly dialog = inject(MatDialog);
  private readonly store = inject(GalleryStore);
  private readonly snackBar = inject(MatSnackBar);
  private readonly exportService = inject(ExportService);
  private readonly i18n = inject(I18nService);
  private readonly api = inject(ApiService);

  /**
   * Send photos to the OS trash via `POST /api/photo/delete`.
   *
   * Owns the request and the failure snackbar, matching `embedMetadata`'s
   * shape -- the only local effect of a delete is REMOVING rows, which the
   * caller applies via `GalleryStore.removePhotos` (this service never
   * reaches into the store for that), so there is no optimistic patch to own
   * here the way `toggleFavorite`/`toggleRejected` do per-component.
   *
   * Returns `null` (rather than throwing) on failure so callers can bail out
   * without a try/catch of their own; the error snackbar is already shown.
   */
  async deletePhotos(
    paths: string[],
    opts: { includeCompanions: boolean; includeSequenceSiblings: boolean },
  ): Promise<PhotoDeleteResponse | null> {
    try {
      return await firstValueFrom(this.api.post<PhotoDeleteResponse>('/photo/delete', {
        paths,
        include_companions: opts.includeCompanions,
        include_sequence_siblings: opts.includeSequenceSiblings,
        dry_run: false,
      }));
    } catch {
      this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
      return null;
    }
  }

  embedMetadata(photo: Photo): void {
    this.exportService.embedMetadata(photo.path).subscribe({
      next: () => this.snackBar.open(this.i18n.t(I18N.notifications.metadata_embedded), '', { duration: 2000 }),
      error: () => this.snackBar.open(this.i18n.t(I18N.notifications.metadata_embed_failed), '', { duration: 3000 }),
    });
  }

  openCritique(photo: Photo): void {
    import('../../features/gallery/photo-critique-dialog.component').then(m => {
      const vlmAvailable = this.store.config()?.features?.show_vlm_critique ?? false;
      this.dialog.open(m.PhotoCritiqueDialogComponent, {
        data: { photoPath: photo.path, vlmAvailable },
        width: '95vw',
        maxWidth: '600px',
      });
    });
  }

  openAddPerson(photo: Photo, onAssigned?: () => void): void {
    import('../../features/gallery/face-selector-dialog.component').then(m => {
      const faceRef = this.dialog.open(m.FaceSelectorDialogComponent, {
        data: { photoPath: photo.path },
        width: '95vw',
        maxWidth: '400px',
      });
      faceRef.afterClosed().subscribe(face => {
        if (!face) return;
        import('../../features/gallery/person-selector-dialog.component').then(m2 => {
          const persons = this.store.persons().filter(p => p.name);
          const personRef = this.dialog.open(m2.PersonSelectorDialogComponent, {
            data: persons,
            width: '95vw',
            maxWidth: '400px',
          });
          personRef.afterClosed().subscribe(async result => {
            if (!result) return;
            if (result.kind === 'create') {
              const created = await this.store.createPerson(result.name, [face.id], photo.path);
              if (created) {
                this.snackBar.open(this.i18n.t(I18N.notifications.faces_assigned), '', { duration: 2000 });
                onAssigned?.();
              } else {
                this.snackBar.open(this.i18n.t(I18N.persons.create_error), '', { duration: 3000 });
              }
            } else if (result.kind === 'select') {
              const assigned = await this.store.assignFace(face.id, result.person.id, photo.path, result.person.name);
              if (assigned) {
                this.snackBar.open(this.i18n.t(I18N.notifications.faces_assigned), '', { duration: 2000 });
                onAssigned?.();
              } else {
                this.snackBar.open(this.i18n.t(I18N.errors.action_failed), '', { duration: 3000 });
              }
            }
          });
        });
      });
    });
  }
}
