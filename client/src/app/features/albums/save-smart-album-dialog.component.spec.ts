import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { of, throwError } from 'rxjs';
import { AlbumService } from '../../core/services/album.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { SaveSmartAlbumDialogComponent } from './save-smart-album-dialog.component';

describe('SaveSmartAlbumDialogComponent', () => {
  let component: SaveSmartAlbumDialogComponent;
  let albumService: { create: Mock };
  let journal: { record: Mock };

  beforeEach(() => {
    albumService = { create: vi.fn(() => of({ id: 9, name: 'Best' })) };
    journal = { record: vi.fn() };
    TestBed.configureTestingModule({
      providers: [
        SaveSmartAlbumDialogComponent,
        { provide: AlbumService, useValue: albumService },
        { provide: MatDialogRef, useValue: { close: vi.fn() } },
        { provide: MAT_DIALOG_DATA, useValue: { filterJson: '{"min_score":"7"}' } },
        { provide: UserActivityJournal, useValue: journal },
      ],
    });
    component = TestBed.inject(SaveSmartAlbumDialogComponent);
  });

  it('journals one smart create with the id and name', async () => {
    component.name = 'Best';
    await component.save();
    expect(albumService.create).toHaveBeenCalledWith('Best', '', true, '{"min_score":"7"}');
    expect(journal.record).toHaveBeenCalledTimes(1);
    expect(journal.record).toHaveBeenCalledWith('album', [], { album_id: 9, action: 'create', name: 'Best', is_smart: true });
  });

  it('journals nothing when the request fails', async () => {
    component.name = 'Best';
    albumService.create.mockReturnValue(throwError(() => new Error('boom')));
    await component.save();
    expect(journal.record).not.toHaveBeenCalled();
  });
});
