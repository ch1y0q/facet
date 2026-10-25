import type { Mock } from 'vitest';
import { TestBed, ComponentFixture } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Router } from '@angular/router';
import { of } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from '../gallery/gallery.store';
import { PhotoFaceLayerComponent, PhotoFaceRow, DrawnFace } from './photo-face-layer.component';

const ROWS: PhotoFaceRow[] = [
  { id: 1, face_index: 0, person_id: 5, person_name: 'Valerie', box: [0.1, 0.2, 0.3, 0.6] },
  { id: 2, face_index: 1, person_id: null, person_name: null, box: [0.5, 0.0, 0.6, 0.2] },
  // Untrusted dimensions: the server sends no box, so nothing is drawn.
  { id: 3, face_index: 2, person_id: null, person_name: null, box: null },
];

describe('PhotoFaceLayerComponent', () => {
  let fixture: ComponentFixture<PhotoFaceLayerComponent>;
  let component: PhotoFaceLayerComponent;
  let mockApi: { get: Mock; post: Mock };
  let mockDialog: { open: Mock };
  let mockStore: { assignFace: Mock; createPerson: Mock; unassignPerson: Mock; reloadPersonOptions: Mock };
  let mockSnackBar: { open: Mock };
  let mockRouter: { navigate: Mock };

  async function render(rows: PhotoFaceRow[] = ROWS, width: number | null = 1000, height: number | null = 500) {
    mockApi.get.mockReturnValue(of({ faces: rows }));
    fixture = TestBed.createComponent(PhotoFaceLayerComponent);
    component = fixture.componentInstance;
    fixture.componentRef.setInput('path', '/p/a.jpg');
    fixture.componentRef.setInput('imageWidth', width);
    fixture.componentRef.setInput('imageHeight', height);
    fixture.componentRef.setInput('canEdit', true);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  beforeEach(() => {
    mockApi = { get: vi.fn(), post: vi.fn(() => of({})) };
    mockDialog = { open: vi.fn() };
    mockStore = {
      assignFace: vi.fn(async () => true),
      createPerson: vi.fn(async () => ({ id: 9, name: 'New', face_count: 1 })),
      unassignPerson: vi.fn(async () => undefined),
      reloadPersonOptions: vi.fn(async () => undefined),
    };
    mockSnackBar = { open: vi.fn() };
    mockRouter = { navigate: vi.fn(() => Promise.resolve(true)) };
    TestBed.configureTestingModule({
      imports: [PhotoFaceLayerComponent],
      providers: [
        { provide: ApiService, useValue: mockApi },
        { provide: MatDialog, useValue: mockDialog },
        { provide: GalleryStore, useValue: mockStore },
        { provide: MatSnackBar, useValue: mockSnackBar },
        { provide: Router, useValue: mockRouter },
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
      ],
    });
  });

  it('asks the server for the photo faces', async () => {
    await render();
    expect(mockApi.get).toHaveBeenCalledWith('/photo/faces', { path: '/p/a.jpg' });
  });

  it('draws each trusted face in the photo pixel frame', async () => {
    await render();
    const svg = fixture.nativeElement.querySelector('svg') as SVGElement;
    expect(svg.getAttribute('viewBox')).toBe('0 0 1000 500');
    const rects = [...fixture.nativeElement.querySelectorAll('rect')] as SVGRectElement[];
    expect(rects.length).toBe(2);
    expect(['x', 'y', 'width', 'height'].map((a) => Math.round(Number(rects[0].getAttribute(a))))).toEqual([100, 100, 200, 200]);
  });

  it('labels a named face with its name and an unnamed one as unknown', async () => {
    await render();
    const labels = [...fixture.nativeElement.querySelectorAll('text')].map((t) => (t as SVGTextElement).textContent?.trim());
    expect(labels[0]).toBe('Valerie');
    expect(labels[1]).toBe('photo_faces.unknown');
  });

  it('puts the label inside a box that touches the top edge', async () => {
    await render();
    const [named, top] = component.faces();
    expect(named.labelY).toBeLessThan(named.y);
    expect(top.labelY).toBeGreaterThan(top.y);
  });

  it('boxes named faces in white and unnamed faces in red', async () => {
    await render();
    const rects = [...fixture.nativeElement.querySelectorAll('rect')] as SVGRectElement[];
    expect(rects[0].getAttribute('stroke')).toBe('white');
    expect(rects[1].getAttribute('stroke')).toBe('#ef4444');
  });

  it('shows boxes only on hover by default, and always with showAll', async () => {
    await render();
    const rect = () => fixture.nativeElement.querySelector('rect') as SVGRectElement;
    expect(rect().classList.contains('opacity-0')).toBe(true);

    fixture.componentRef.setInput('showAll', true);
    fixture.detectChanges();

    expect(rect().classList.contains('opacity-0')).toBe(false);
    expect(rect().classList.contains('opacity-100')).toBe(true);
  });

  it('keeps the focused person boxed, thicker, without showAll', async () => {
    await render();
    fixture.componentRef.setInput('focusPersonIds', [5]);
    fixture.detectChanges();
    const [focused, other] = [...fixture.nativeElement.querySelectorAll('rect')] as SVGRectElement[];
    expect(focused.getAttribute('stroke-width')).toBe('4');
    expect(focused.classList.contains('opacity-100')).toBe(true);
    expect(other.getAttribute('stroke-width')).toBe('2');
    expect(other.classList.contains('opacity-0')).toBe(true);
  });

  it('sets the face as its person picture', async () => {
    await render();
    await component.usePicture(component.faces()[0]);
    expect(mockApi.post).toHaveBeenCalledWith('/person/5/avatar', { face_id: 1 });
    expect(mockStore.reloadPersonOptions).toHaveBeenCalled();
  });

  it('draws nothing without the photo dimensions', async () => {
    await render(ROWS, null, null);
    expect(fixture.nativeElement.querySelector('svg')).toBeNull();
  });

  it('read-only: a face with a person opens the menu, a face without one does not', async () => {
    await render();
    fixture.componentRef.setInput('canEdit', false);
    const menuFace = () => (component as unknown as { menuFace: () => DrawnFace | null }).menuFace();
    const loose: DrawnFace = { ...component.faces()[1], personId: null };

    component.onFaceClick(loose, new MouseEvent('click', { clientX: 5, clientY: 6 }));
    expect(menuFace()).toBeNull();

    component.onFaceClick(component.faces()[0], new MouseEvent('click', { clientX: 5, clientY: 6 }));
    expect(menuFace()?.id).toBe(1);
  });

  it('opens the gallery on all photos of the face person, named or not', async () => {
    await render();
    component.viewPhotos(component.faces()[0]);
    expect(mockRouter.navigate).toHaveBeenCalledWith(['/'], { queryParams: { person_id: '5' } });
  });

  it('moves a face to the chosen person, then reloads and tells the page', async () => {
    await render();
    const changed = vi.fn();
    component.changed.subscribe(changed);
    mockDialog.open.mockReturnValue({ afterClosed: () => of({ kind: 'select', person: { id: 7, name: 'Peter' } }) });

    await component.changePerson(component.faces()[0]);

    expect(mockStore.assignFace).toHaveBeenCalledWith(1, 7, '/p/a.jpg', 'Peter');
    expect(mockApi.get).toHaveBeenCalledTimes(2);
    expect(changed).toHaveBeenCalled();
  });

  it('names an unknown face as a new person', async () => {
    await render();
    mockDialog.open.mockReturnValue({ afterClosed: () => of({ kind: 'create', name: 'Aunt May' }) });

    await component.changePerson(component.faces()[1]);

    expect(mockStore.createPerson).toHaveBeenCalledWith('Aunt May', [2], '/p/a.jpg');
  });

  it('changes nothing when the picker is cancelled', async () => {
    await render();
    mockDialog.open.mockReturnValue({ afterClosed: () => of(undefined) });

    await component.changePerson(component.faces()[0]);

    expect(mockStore.assignFace).not.toHaveBeenCalled();
    expect(mockStore.createPerson).not.toHaveBeenCalled();
  });

  it('takes a face off its person', async () => {
    await render();
    await component.notThisPerson(component.faces()[0]);
    expect(mockStore.unassignPerson).toHaveBeenCalledWith('/p/a.jpg', 5);
  });

  it('opens find-more for the face person', async () => {
    await render();
    mockDialog.open.mockReturnValue({ afterClosed: () => of({ added: 2 }) });

    await component.findMore(component.faces()[0]);

    expect(mockDialog.open.mock.calls[0][1].data).toEqual({ personId: 5, personName: 'Valerie' });
    expect(mockSnackBar.open).toHaveBeenCalled();
  });
});
