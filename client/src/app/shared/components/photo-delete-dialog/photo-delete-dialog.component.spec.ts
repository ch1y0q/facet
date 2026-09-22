import { TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { I18nService } from '../../../core/services/i18n.service';
import { PhotoDeleteDialogComponent, PhotoDeleteDialogData } from './photo-delete-dialog.component';

describe('PhotoDeleteDialogComponent', () => {
  let dialogClose: ReturnType<typeof vi.fn>;

  function buildRendered(data: PhotoDeleteDialogData) {
    dialogClose = vi.fn();
    // Reset first: a couple of tests below build two fixtures in one `it()`
    // to compare rendering with/without a flag, and TestBed refuses to
    // reconfigure a module it has already instantiated.
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [PhotoDeleteDialogComponent],
      providers: [
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
        { provide: MatDialogRef, useValue: { close: dialogClose } },
        { provide: MAT_DIALOG_DATA, useValue: data },
      ],
    });
    const fixture = TestBed.createComponent(PhotoDeleteDialogComponent);
    fixture.detectChanges();
    return fixture;
  }

  const baseData: PhotoDeleteDialogData = {
    surface: 'photo_detail',
    paths: ['/a.jpg'],
    count: 1,
    hasCompanion: false,
    hasSiblings: false,
    hasBracketLead: false,
  };

  it('renders the companion checkbox only when data.hasCompanion is true', () => {
    const withoutCompanion = buildRendered({ ...baseData, hasCompanion: false });
    expect(withoutCompanion.nativeElement.querySelector('mat-checkbox')).toBeNull();

    const withCompanion = buildRendered({ ...baseData, hasCompanion: true });
    const checkboxes = withCompanion.nativeElement.querySelectorAll('mat-checkbox');
    expect(checkboxes.length).toBe(1);
  });

  it('renders the sequence-sibling checkbox only when data.hasSiblings is true', () => {
    const withoutSiblings = buildRendered({ ...baseData, hasSiblings: false });
    expect(withoutSiblings.nativeElement.querySelector('mat-checkbox')).toBeNull();

    const withSiblings = buildRendered({ ...baseData, hasSiblings: true });
    expect(withSiblings.nativeElement.querySelectorAll('mat-checkbox').length).toBe(1);
  });

  it('renders both checkboxes when both data.hasCompanion and data.hasSiblings are true', () => {
    const fixture = buildRendered({ ...baseData, hasCompanion: true, hasSiblings: true });
    expect(fixture.nativeElement.querySelectorAll('mat-checkbox').length).toBe(2);
  });

  it('confirming with the companion checkbox OFF closes the dialog with includeCompanions: false', () => {
    const fixture = buildRendered({ ...baseData, hasCompanion: true });
    const confirmButton = Array.from(fixture.nativeElement.querySelectorAll('button'))
      .find((b) => (b as HTMLElement).textContent?.includes('photo_detail.delete.button_label')) as HTMLElement;
    confirmButton.click();

    expect(dialogClose).toHaveBeenCalledWith({ includeCompanions: false, includeSequenceSiblings: false });
  });

  it('confirming with the companion checkbox ON closes the dialog with includeCompanions: true', () => {
    const fixture = buildRendered({ ...baseData, hasCompanion: true });
    const checkbox = fixture.nativeElement.querySelector('input[type="checkbox"]') as HTMLInputElement;
    checkbox.click();
    fixture.detectChanges();
    const confirmButton = Array.from(fixture.nativeElement.querySelectorAll('button'))
      .find((b) => (b as HTMLElement).textContent?.includes('photo_detail.delete.button_label')) as HTMLElement;
    confirmButton.click();

    expect(dialogClose).toHaveBeenCalledWith({ includeCompanions: true, includeSequenceSiblings: false });
  });

  it('uses the bulk (cull.delete_*) copy and reuses cull checkbox labels on the bulk surface', () => {
    const fixture = buildRendered({ ...baseData, surface: 'bulk', hasCompanion: true, hasSiblings: true, count: 3 });
    const title = fixture.nativeElement.querySelector('h2').textContent;
    expect(title).toContain('cull.delete_confirm_title');
    const checkboxLabels = Array.from(fixture.nativeElement.querySelectorAll('mat-checkbox'))
      .map((el) => (el as HTMLElement).textContent?.trim());
    expect(checkboxLabels).toContain('cull.include_companions');
    expect(checkboxLabels).toContain('cull.include_sequence_siblings');
  });

  it('explains the bracket-lead refusal on the photo-detail surface when hasBracketLead is true', () => {
    const fixture = buildRendered({ ...baseData, hasBracketLead: true });
    const body = fixture.nativeElement.querySelector('mat-dialog-content p').textContent;
    expect(body).toBe('photo_detail.delete.confirm_body_bracket_refused');
  });

  // Finding 7: `bodyKey`'s `includeSequenceSiblings()` branch (line 92) was
  // never exercised by any test -- only the checkboxes' presence/absence and
  // `dialogClose`'s payload were asserted, never the rendered body text after
  // ticking the siblings checkbox. Ticking siblings ALONE cannot pin the
  // line order against line 93 (companion): with only one flag true, the
  // two independent `if`s return the same result whichever is checked
  // first. Both must be ticked so the siblings check's priority over the
  // companion check is what the assertion actually depends on -- pinning
  // both the confirm() payload AND the rendered <p> text together so lines
  // 92/93 cannot be swapped without failing here.
  it('ticking both the companion and sequence-sibling checkboxes gives the siblings body text priority, and confirms with both flags true', () => {
    const fixture = buildRendered({ ...baseData, hasCompanion: true, hasSiblings: true });

    const checkboxes = fixture.nativeElement.querySelectorAll('input[type="checkbox"]') as NodeListOf<HTMLInputElement>;
    expect(checkboxes.length).toBe(2);
    checkboxes[0].click(); // companion (rendered first)
    checkboxes[1].click(); // sequence siblings (rendered second)
    fixture.detectChanges();

    const body = fixture.nativeElement.querySelector('mat-dialog-content p').textContent;
    expect(body).toBe('photo_detail.delete.confirm_body_with_siblings');

    const confirmButton = Array.from(fixture.nativeElement.querySelectorAll('button'))
      .find((b) => (b as HTMLElement).textContent?.includes('photo_detail.delete.button_label')) as HTMLElement;
    confirmButton.click();

    expect(dialogClose).toHaveBeenCalledWith({ includeCompanions: true, includeSequenceSiblings: true });
  });
});
