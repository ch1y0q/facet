import type { Mock } from 'vitest';
import { TestBed, ComponentFixture } from '@angular/core/testing';
import { MatDialog } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { signal } from '@angular/core';
import { of } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from './gallery.store';
import { PersonNamingBarComponent, sameName } from './person-naming-bar.component';

const OPTIONS = {
  persons: [
    [163, 'Jirjet Salem', 257],
    [144, 'Peter Salem', 298],
    [95, null, 25],
    [96, null, 4],
  ],
};

describe('PersonNamingBarComponent', () => {
  let fixture: ComponentFixture<PersonNamingBarComponent>;
  let component: PersonNamingBarComponent;
  let mockApi: { get: Mock; post: Mock };
  let mockDialog: { open: Mock };
  interface HiddenSummary { total: number; blinks: number; bursts: number; duplicates: number; brackets: number; panoramas: number }
  const NONE_HIDDEN: HiddenSummary = { total: 0, blinks: 0, bursts: 0, duplicates: 0, brackets: 0, panoramas: 0 };
  let mockStore: {
    reloadPersonOptions: Mock; updateFilters: Mock; showAllHidden: Mock; restoreHidden: Mock;
    total: ReturnType<typeof signal<number>>;
    hiddenSummary: ReturnType<typeof signal<HiddenSummary>>;
    hiddenFiltersStash: ReturnType<typeof signal<object | null>>;
  };

  async function render(personId = 95, canEdit = true) {
    fixture = TestBed.createComponent(PersonNamingBarComponent);
    component = fixture.componentInstance;
    fixture.componentRef.setInput('personId', personId);
    fixture.componentRef.setInput('canEdit', canEdit);
    fixture.detectChanges();
    await fixture.whenStable();
    fixture.detectChanges();
  }

  function type(name: string) {
    (component as unknown as { draft: string }).draft = name;
  }

  beforeEach(() => {
    mockApi = { get: vi.fn(() => of(OPTIONS)), post: vi.fn(() => of({ success: true })) };
    mockDialog = { open: vi.fn(() => ({ afterClosed: () => of(true) })) };
    mockStore = {
      reloadPersonOptions: vi.fn(async () => undefined), updateFilters: vi.fn(async () => undefined),
      showAllHidden: vi.fn(), restoreHidden: vi.fn(),
      total: signal(3), hiddenSummary: signal(NONE_HIDDEN), hiddenFiltersStash: signal<object | null>(null),
    };
    TestBed.configureTestingModule({
      imports: [PersonNamingBarComponent],
      providers: [
        { provide: ApiService, useValue: mockApi },
        { provide: MatDialog, useValue: mockDialog },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: GalleryStore, useValue: mockStore },
        { provide: I18nService, useValue: { t: (k: string) => k, translations: () => ({}) } },
      ],
    });
  });

  it('loads the person list forcing this person in, and shows who it is', async () => {
    await render();
    expect(mockApi.get).toHaveBeenCalledWith('/filter_options/persons', { ids: '95' });
    expect(component.person()).toEqual({ id: 95, name: null, count: 25 });
    expect(fixture.nativeElement.textContent).toContain('gallery.person_bar.unnamed');
  });

  it('suggests every other named person, never itself or the unnamed', async () => {
    await render(163);
    expect(component.otherNames()).toEqual(['Peter Salem']);
  });

  it('a new name renames the person', async () => {
    await render();
    type('  Aunt May ');
    await component.assign();
    expect(mockApi.post).toHaveBeenCalledWith('/persons/95/rename', { name: 'Aunt May' });
    expect(mockDialog.open).not.toHaveBeenCalled();
    expect(mockStore.reloadPersonOptions).toHaveBeenCalled();
  });

  it('an existing name, in any case, merges into that person and shows its photos', async () => {
    await render();
    type('jirjet salem');
    await component.assign();
    expect(mockDialog.open).toHaveBeenCalled();
    expect(mockApi.post).toHaveBeenCalledWith('/persons/merge', { source_id: 95, target_id: 163 });
    expect(mockStore.updateFilters).toHaveBeenCalledWith({ person_id: '163' });
  });

  it('cancelling the merge changes nothing', async () => {
    mockDialog.open.mockReturnValue({ afterClosed: () => of(false) });
    await render();
    type('Jirjet Salem');
    await component.assign();
    expect(mockApi.post).not.toHaveBeenCalled();
    expect(mockStore.updateFilters).not.toHaveBeenCalled();
  });

  it('typing the name it already has does nothing', async () => {
    await render(163);
    type('JIRJET SALEM');
    await component.assign();
    expect(mockApi.post).not.toHaveBeenCalled();
  });

  it('read-only shows the person but no name field', async () => {
    await render(95, false);
    expect(fixture.nativeElement.querySelector('input')).toBeNull();
    expect(fixture.nativeElement.textContent).toContain('gallery.person_bar.photos');
  });

  it('says how many photos are hidden and why, and offers to show them', async () => {
    mockStore.total.set(2);
    mockStore.hiddenSummary.set({ ...NONE_HIDDEN, total: 1, bursts: 1 });
    await render();
    expect(component.hiddenCount()).toBe(1);
    expect(component.hiddenReasons()).toBe('gallery.person_bar.reason_bursts');
    const text = fixture.nativeElement.textContent as string;
    expect(text).toContain('gallery.person_bar.shown_of');
    expect(text).toContain('gallery.person_bar.hidden_why');
    const showAll = [...fixture.nativeElement.querySelectorAll('button')]
      .find((b) => (b as HTMLElement).textContent?.includes('gallery.person_bar.show_all')) as HTMLElement;
    showAll.click();
    expect(mockStore.showAllHidden).toHaveBeenCalled();
  });

  it('lists every reason that applies', async () => {
    mockStore.hiddenSummary.set({ ...NONE_HIDDEN, total: 3, bursts: 2, blinks: 1 });
    await render();
    expect(component.hiddenReasons()).toBe('gallery.person_bar.reason_bursts, gallery.person_bar.reason_blinks');
  });

  it('offers to hide repeats again after Show all', async () => {
    mockStore.hiddenFiltersStash.set({ hide_bursts: true });
    await render();
    const again = [...fixture.nativeElement.querySelectorAll('button')]
      .find((b) => (b as HTMLElement).textContent?.includes('gallery.person_bar.hide_again')) as HTMLElement;
    again.click();
    expect(mockStore.restoreHidden).toHaveBeenCalled();
  });

  it('sameName ignores case and outer spaces', () => {
    expect(sameName(' Peter Salem', 'peter salem ')).toBe(true);
    expect(sameName('Peter', 'Peter Salem')).toBe(false);
    expect(sameName(null, 'x')).toBe(false);
  });
});
