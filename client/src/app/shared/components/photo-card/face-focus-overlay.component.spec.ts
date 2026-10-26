import type { Mock } from 'vitest';
import { TestBed, ComponentFixture } from '@angular/core/testing';
import { of } from 'rxjs';
import { ApiService } from '../../../core/services/api.service';
import { FaceFocusOverlayComponent } from './face-focus-overlay.component';

const FACES = {
  faces: [
    { person_id: 95, box: [0.1, 0.2, 0.3, 0.6] },
    { person_id: 163, box: [0.5, 0.2, 0.7, 0.6] },
    { person_id: 95, box: null },
  ],
};

describe('FaceFocusOverlayComponent', () => {
  let fixture: ComponentFixture<FaceFocusOverlayComponent>;
  let mockApi: { get: Mock };

  async function render(personId: string, cover = false) {
    fixture = TestBed.createComponent(FaceFocusOverlayComponent);
    fixture.componentRef.setInput('path', '/p/a.jpg');
    fixture.componentRef.setInput('personId', personId);
    fixture.componentRef.setInput('imageWidth', 1000);
    fixture.componentRef.setInput('imageHeight', 500);
    fixture.componentRef.setInput('cover', cover);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  beforeEach(() => {
    mockApi = { get: vi.fn(() => of(FACES)) };
    TestBed.configureTestingModule({
      imports: [FaceFocusOverlayComponent],
      providers: [{ provide: ApiService, useValue: mockApi }],
    });
  });

  it('outlines only the filtered person, in the photo pixel frame', async () => {
    await render('95');
    expect(mockApi.get).toHaveBeenCalledWith('/photo/faces', { path: '/p/a.jpg' });
    const rects = [...fixture.nativeElement.querySelectorAll('rect')] as SVGRectElement[];
    expect(rects.length).toBe(1);
    expect(['x', 'y', 'width', 'height'].map((a) => Math.round(Number(rects[0].getAttribute(a)))))
      .toEqual([100, 100, 200, 200]);
    expect(rects[0].getAttribute('stroke')).toBe('#ef4444');
    expect(fixture.nativeElement.querySelector('svg').getAttribute('viewBox')).toBe('0 0 1000 500');
  });

  it('crops like an object-cover thumbnail when the tile is filled', async () => {
    await render('95', true);
    expect(fixture.nativeElement.querySelector('svg').getAttribute('preserveAspectRatio')).toBe('xMidYMid slice');
  });

  it('asks nothing and draws nothing without a single-person filter', async () => {
    await render('');
    expect(mockApi.get).not.toHaveBeenCalled();
    expect(fixture.nativeElement.querySelector('svg')).toBeNull();
    await render('95,163');
    expect(mockApi.get).not.toHaveBeenCalled();
  });

  it('draws nothing when the person has no trusted box in this photo', async () => {
    mockApi.get.mockReturnValue(of({ faces: [{ person_id: 95, box: null }] }));
    await render('95');
    expect(fixture.nativeElement.querySelector('svg')).toBeNull();
  });
});
