import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import {
  FindMoreFacesDialogComponent,
  FIND_MORE_FETCH,
  FIND_MORE_MIN_SIMILARITY,
  FIND_MORE_PAGE,
  PossibleFace,
} from './find-more-faces-dialog.component';

const face = (face_id: number, similarity: number, person_name: string | null = null): PossibleFace => ({
  face_id,
  photo_path: `/p/${face_id}.jpg`,
  person_id: person_name ? 900 + face_id : null,
  person_name,
  similarity,
  distance: 1 - similarity,
});

describe('FindMoreFacesDialogComponent', () => {
  let component: FindMoreFacesDialogComponent;
  let mockApi: { get: Mock; post: Mock };
  let dialogRef: { close: Mock };

  function create(): void {
    TestBed.configureTestingModule({
      providers: [
        FindMoreFacesDialogComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: I18nService, useValue: { t: vi.fn((key: string) => key) } },
        { provide: MAT_DIALOG_DATA, useValue: { personId: 7, personName: 'Anna' } },
        { provide: MatDialogRef, useValue: dialogRef },
      ],
    });
    component = TestBed.inject(FindMoreFacesDialogComponent);
  }

  beforeEach(() => {
    mockApi = {
      get: vi.fn(() => of({ faces: [face(1, 0.8), face(2, 0.45), face(3, 0.7, 'Bob')] })),
      post: vi.fn(() => of({ success: true })),
    };
    dialogRef = { close: vi.fn() };
    create();
  });

  it('asks possible_faces for the person, across all faces by default', async () => {
    await component.ngOnInit();
    expect(mockApi.get).toHaveBeenCalledWith('/person/7/possible_faces', {
      scope: 'all',
      limit: FIND_MORE_FETCH,
      min_similarity: FIND_MORE_MIN_SIMILARITY,
    });
    expect(component.faces().map((f) => f.face_id)).toEqual([1, 2, 3]);
  });

  it('pre-ticks only strong matches that no named person owns', async () => {
    await component.ngOnInit();
    // 1 is strong and unowned; 2 is weak; 3 is strong but already Bob's.
    expect([...component.selectedIds()]).toEqual([1]);
    const rows = component.rows();
    expect(rows.find((r) => r.face_id === 1)?.selected).toBe(true);
    expect(rows.find((r) => r.face_id === 3)?.selected).toBe(false);
    expect(rows.find((r) => r.face_id === 1)?.percent).toBe(80);
  });

  it('pre-ticks a strong match owned by a same-named person, a split-off cluster', async () => {
    mockApi.get.mockReturnValue(of({ faces: [face(5, 0.9, 'Anna'), face(6, 0.9, 'Bob')] }));
    await component.ngOnInit();
    expect([...component.selectedIds()]).toEqual([5]);
  });

  it('shows at most one page of faces', async () => {
    mockApi.get.mockReturnValue(of({
      faces: Array.from({ length: FIND_MORE_PAGE + 10 }, (_, i) => face(i + 1, 0.4)),
    }));
    await component.ngOnInit();
    expect(component.faces().length).toBe(FIND_MORE_PAGE);
  });

  it('adds the ticked faces, then reloads without the faces it left unticked', async () => {
    await component.ngOnInit();
    component.toggle(2);
    mockApi.get.mockReturnValue(of({ faces: [face(3, 0.7, 'Bob'), face(4, 0.6)] }));

    await component.addSelected();

    expect(mockApi.post).toHaveBeenCalledWith('/persons/7/assign_faces', { face_ids: [1, 2] });
    expect(mockApi.get).toHaveBeenCalledTimes(2);
    // Face 3 was shown and left unticked, so the second round drops it.
    expect(component.faces().map((f) => f.face_id)).toEqual([4]);
    component.close();
    expect(dialogRef.close).toHaveBeenCalledWith({ added: 2 });
  });

  it('closes with nothing added when no round was confirmed', async () => {
    await component.ngOnInit();
    component.close();
    expect(dialogRef.close).toHaveBeenCalledWith({ added: 0 });
  });

  it('switching the scope reloads with the new scope', async () => {
    await component.ngOnInit();
    component.setScope('unnamed');
    await vi.waitFor(() => expect(mockApi.get).toHaveBeenCalledTimes(2));
    expect(mockApi.get.mock.calls[1][1]).toMatchObject({ scope: 'unnamed' });
  });

  it('select all and clear act on the faces shown', async () => {
    await component.ngOnInit();
    component.selectAll();
    expect(component.selectedIds().size).toBe(3);
    component.clearSelection();
    expect(component.selectedIds().size).toBe(0);
  });

  it('explains a missing centroid instead of failing silently', async () => {
    mockApi.get.mockReturnValue(throwError(() => new HttpErrorResponse({
      status: 412,
      error: { detail: 'This person has no centroid yet; run face clustering first' },
    })));
    await component.ngOnInit();
    expect(component.error()).toBe('persons.find_more_no_centroid');
    expect(component.faces()).toEqual([]);
  });

  it('passes the server detail through for a scan over the ceiling', async () => {
    const detail = '300000 faces would be scanned, over the ceiling of 192000; narrow the scan';
    mockApi.get.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 412, error: { detail } })));
    await component.ngOnInit();
    expect(component.error()).toBe(detail);
  });

  it('reports a failed add and keeps the dialog open', async () => {
    await component.ngOnInit();
    mockApi.post.mockReturnValue(throwError(() => new Error('boom')));
    await component.addSelected();
    expect(component.error()).toBe('persons.find_more_add_error');
    expect(component.busy()).toBe(false);
    expect(dialogRef.close).not.toHaveBeenCalled();
  });
});
