import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { By } from '@angular/platform-browser';
import { vi } from 'vitest';
import { CompareSelectedDialogComponent } from './compare-selected-dialog.component';
import { FIT_ZOOM, MAX_COMPARE_PANES, SyncedZoomComponent } from './synced-zoom.component';
import { Photo } from '../../shared/models/photo.model';
import { I18nService } from '../../core/services/i18n.service';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';

const photo = (path: string): Photo => ({ path, filename: path.slice(1) } as Photo);

function build(paths: string[]) {
  const dialogRef = { close: vi.fn() };
  TestBed.configureTestingModule({
    imports: [CompareSelectedDialogComponent],
    providers: [
      { provide: MAT_DIALOG_DATA, useValue: { photos: paths.map(photo) } },
      { provide: MatDialogRef, useValue: dialogRef },
      { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
    ],
  });
  const fixture = TestBed.createComponent(CompareSelectedDialogComponent);
  fixture.detectChanges();
  return { fixture, dialogRef };
}

describe('CompareSelectedDialogComponent', () => {
  afterEach(() => TestBed.resetTestingModule());

  it('renders one synced pane per selected photo', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const panes = fixture.debugElement.nativeElement.querySelectorAll('app-synced-zoom');
    expect(panes.length).toBe(2);
  });

  it('renders a 2x2 grid for four photos', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
    expect(fixture.debugElement.nativeElement.querySelectorAll('app-synced-zoom').length).toBe(4);
  });

  it('drops photos beyond the pane cap rather than shrinking them all', () => {
    const paths = Array.from({ length: MAX_COMPARE_PANES + 3 }, (_, i) => `/p${i}.jpg`);
    const { fixture } = build(paths);
    expect(fixture.debugElement.nativeElement.querySelectorAll('app-synced-zoom').length)
      .toBe(MAX_COMPARE_PANES);
  });

  it('gives each pane its own stored thumbnail as placeholder, keyed by its frame', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const urls = new ThumbnailUrlPipe();
    const panes = fixture.debugElement.queryAll(By.directive(SyncedZoomComponent))
      .map(de => de.componentInstance as SyncedZoomComponent);
    expect(panes.map(p => p.placeholderSrc())).toEqual([urls.transform('/a.jpg', 640), urls.transform('/b.jpg', 640)]);
    expect(panes.map(p => p.frameKey())).toEqual(['/a.jpg', '/b.jpg']);
  });

  it('a zoom from one pane drives every other pane', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const panes = fixture.debugElement.queryAll(
      (de) => de.componentInstance instanceof SyncedZoomComponent,
    );
    const next = { scale: 3, tx: 12, ty: -8 };
    panes[0].componentInstance.zoomChange.emit(next);
    fixture.detectChanges();
    expect(panes[0].componentInstance.zoom()).toEqual(next);
    expect(panes[1].componentInstance.zoom()).toEqual(next);
  });

  it('starts fitted and offers the reset only once zoomed', () => {
    const { fixture } = build(['/a.jpg', '/b.jpg']);
    const resetSelector = 'button[aria-label="gallery.compare.reset_zoom"]';
    expect(fixture.debugElement.nativeElement.querySelector(resetSelector)).toBeNull();

    const pane = fixture.debugElement.query(
      (de) => de.componentInstance instanceof SyncedZoomComponent,
    );
    pane.componentInstance.zoomChange.emit({ scale: 2, tx: 0, ty: 0 });
    fixture.detectChanges();
    expect(fixture.debugElement.nativeElement.querySelector(resetSelector)).not.toBeNull();

    fixture.debugElement.nativeElement.querySelector(resetSelector).click();
    fixture.detectChanges();
    expect(pane.componentInstance.zoom()).toEqual(FIT_ZOOM);
  });

  it('closes through the dialog ref', () => {
    const { fixture, dialogRef } = build(['/a.jpg', '/b.jpg']);
    fixture.debugElement.nativeElement.querySelector('button[aria-label="dialog.close"]').click();
    expect(dialogRef.close).toHaveBeenCalled();
  });
});
