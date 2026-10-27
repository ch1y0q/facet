import { ComponentFixture, TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { of } from 'rxjs';
import { MatSelect } from '@angular/material/select';
import { MatDialog } from '@angular/material/dialog';
import { MATERIAL_ANIMATIONS, provideNativeDateAdapter } from '@angular/material/core';
import { MatTooltip } from '@angular/material/tooltip';
import { By } from '@angular/platform-browser';
import { OverlayContainer } from '@angular/cdk/overlay';
import { GalleryStore } from './gallery.store';
import { GalleryFilterSidebarComponent } from './gallery-filter-sidebar.component';
import { I18N } from '../../core/i18n/keys';
import { I18nService } from '../../core/services/i18n.service';
import { AuthService } from '../../core/services/auth.service';
import { AlbumService } from '../../core/services/album.service';

describe('GalleryFilterSidebarComponent', () => {
  let component: GalleryFilterSidebarComponent;
  let mockStore: Record<string, unknown>;

  beforeEach(() => {
    mockStore = {
      filters: signal({
        hide_details: true, hide_blinks: true, hide_bursts: true, hide_duplicates: true,
        hide_rejected: true, favorites_only: false, is_monochrome: false,
        camera: '', lens: '', tag: '', composition_pattern: '', person_id: '',
        min_score: '', max_score: '', min_aesthetic: '', max_aesthetic: '',
        min_face_quality: '', max_face_quality: '', min_composition: '', max_composition: '',
        min_sharpness: '', max_sharpness: '', min_exposure: '', max_exposure: '',
        min_color: '', max_color: '', min_contrast: '', max_contrast: '',
        min_noise: '', max_noise: '', min_dynamic_range: '', max_dynamic_range: '',
        min_face_count: '', max_face_count: '', min_eye_sharpness: '', max_eye_sharpness: '',
        min_face_sharpness: '', max_face_sharpness: '', min_face_ratio: '', max_face_ratio: '',
        min_face_confidence: '', max_face_confidence: '', min_quality_score: '', max_quality_score: '',
        min_topiq: '', max_topiq: '', min_power_point: '', max_power_point: '',
        min_leading_lines: '', max_leading_lines: '', min_isolation: '', max_isolation: '',
        min_saturation: '', max_saturation: '', min_luminance: '', max_luminance: '',
        min_histogram_spread: '', max_histogram_spread: '', min_star_rating: '', max_star_rating: '',
        min_iso: '', max_iso: '', min_aperture: '', max_aperture: '',
        min_focal_length: '', max_focal_length: '', date_from: '', date_to: '',
        search: '', type: '', sort: 'aggregate', sort_direction: 'DESC', page: 1, per_page: 64,
        similar_to: '', similarity_mode: 'visual', min_similarity: '70',
        semanticQuery: '', search_threshold: '', album_id: '',
        min_aesthetic_iaa: '', max_aesthetic_iaa: '',
        min_face_quality_iqa: '', max_face_quality_iqa: '',
        min_liqe: '', max_liqe: '',
        min_qrealign: '', max_qrealign: '',
        min_aesthetic_v25: '', max_aesthetic_v25: '',
        min_deqa: '', max_deqa: '',
        min_subject_sharpness: '', max_subject_sharpness: '',
        min_subject_prominence: '', max_subject_prominence: '',
        min_subject_placement: '', max_subject_placement: '',
        min_bg_separation: '', max_bg_separation: '',
        path_prefix: '',
      }),
      filterDrawerOpen: signal(true),
      reviewProgressVisible: signal(true), setReviewProgressVisible: vi.fn(),
      cameras: signal([]),
      lenses: signal([]),
      tags: signal([]),
      persons: signal([]),
      compositionPatterns: signal([]),
      metricRanges: signal({}),
      config: signal(null),
      activeFilterCount: signal(0),
      updateFilter: vi.fn(),
      updateFilterDebounced: vi.fn(),
      updateFilters: vi.fn(),
      resetFilters: vi.fn(),
      setFilterDrawerOpen: vi.fn(),
    };

    TestBed.configureTestingModule({
      providers: [
        GalleryFilterSidebarComponent,
        { provide: GalleryStore, useValue: mockStore },
        { provide: I18nService, useValue: { t: vi.fn((k: string) => k), currentLang: vi.fn(() => 'en'), translations: vi.fn(() => ({})) } },
        { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
        { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })) } },
        { provide: MatDialog, useValue: { open: vi.fn() } },
      ],
    });
    component = TestBed.inject(GalleryFilterSidebarComponent);
  });

  it('should create', () => {
    expect(component).toBeTruthy();
  });

  describe('unavailable metrics (commercial mode)', () => {
    const ids = () => component.advancedFilterGroups().flatMap(g => g.filters.map(f => f.id));

    it('lists the extended-quality filters in default mode', () => {
      expect(ids()).toEqual(expect.arrayContaining(['liqe_range', 'aesthetic_iaa_range', 'face_quality_iqa_range']));
    });

    it('drops filters for hidden metrics but keeps the rest', () => {
      (mockStore['config'] as ReturnType<typeof signal<unknown>>).set({
        unavailable_metrics: ['liqe_score', 'aesthetic_iaa', 'face_quality_iqa'],
      });
      const shown = ids();
      expect(shown).not.toContain('liqe_range');
      expect(shown).not.toContain('aesthetic_iaa_range');
      expect(shown).not.toContain('face_quality_iqa_range');
      expect(shown).toContain('qrealign_range');
      expect(shown).toContain('face_quality_range');
    });

    it('does not count an active hidden filter in the section badge', () => {
      (mockStore['config'] as ReturnType<typeof signal<unknown>>).set({ unavailable_metrics: ['liqe_score'] });
      const filters = mockStore['filters'] as ReturnType<typeof signal<Record<string, unknown>>>;
      filters.update(f => ({ ...f, min_liqe: '4' }));
      expect(component.sectionActiveCounts()['gallery.sidebar.extended_quality']).toBe(0);
    });
  });

  describe('clampDef', () => {
    const scoreDef = {
      id: 'score_range', minKey: 'min_score', maxKey: 'max_score',
      sliderMin: 0, sliderMax: 10, step: 0.5,
    };

    it('clamps slider bounds to the data-driven range when no value is out of range', () => {
      const store = (component as any).store;
      store.metricRanges.set({ min_score: { min: 5, max: 9, buckets: [] } });
      store.filters.set({ ...store.filters(), min_score: '', max_score: '' });
      const clamped = (component as any).clampDef(scoreDef);
      expect(clamped.sliderMin).toBe(5);
      expect(clamped.sliderMax).toBe(9);
    });

    it('widens bounds so an active value below the data min stays reachable', () => {
      const store = (component as any).store;
      store.metricRanges.set({ min_score: { min: 5, max: 9, buckets: [] } });
      // A persisted/URL min of 2 sits below the data minimum of 5.
      store.filters.set({ ...store.filters(), min_score: '2', max_score: '' });
      const clamped = (component as any).clampDef(scoreDef);
      expect(clamped.sliderMin).toBeLessThanOrEqual(2); // not pinned to 5 — reachable
      expect(clamped.sliderMax).toBe(9);                // data max unchanged
    });
  });

  describe('filename search', () => {
    const input = (value: string) => ({ target: { value } }) as unknown as Event;

    afterEach(() => vi.useRealTimers());

    it('filters 400 ms after the last keystroke, once', () => {
      vi.useFakeTimers();
      const store = (component as any).store;
      component.onSidebarSearchChange(input('IMG'));
      component.onSidebarSearchChange(input('IMG_1'));
      vi.advanceTimersByTime(399);
      expect(store.updateFilter).not.toHaveBeenCalled();
      vi.advanceTimersByTime(1);
      expect(store.updateFilter).toHaveBeenCalledTimes(1);
      expect(store.updateFilter).toHaveBeenCalledWith('search', 'IMG_1');
    });

    it('Enter commits at once and drops the pending debounce', () => {
      vi.useFakeTimers();
      const store = (component as any).store;
      component.onSidebarSearchChange(input('IMG'));
      component.onSidebarSearchCommit(input('IMG_2'));
      vi.advanceTimersByTime(1000);
      expect(store.updateFilter.mock.calls).toEqual([['search', 'IMG_2']]);
    });

    it('a semantic keystroke does not cancel a pending filename update', () => {
      vi.useFakeTimers();
      const store = (component as any).store;
      component.onSidebarSearchChange(input('IMG'));
      component.onSemanticSearch(input('sunset'));
      vi.advanceTimersByTime(1000);
      expect(store.updateFilter).toHaveBeenCalledWith('search', 'IMG');
    });
  });

  describe('sectionActiveCounts', () => {
    it('returns 0 for all sections when no filters are active', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), hide_rejected: false });
      const counts = component.sectionActiveCounts();
      expect(counts['date']).toBe(0);
      expect(counts['content']).toBe(0);
      expect(counts['equipment']).toBe(0);
      expect(counts['refine']).toBe(0);
      expect(counts['gallery.sidebar.quality']).toBe(0);
      expect(counts['gallery.sidebar.face']).toBe(0);
    });

    it('counts date_from and date_to independently', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), date_from: '2024-01-01' });
      expect(component.sectionActiveCounts()['date']).toBe(1);
      mockStore.filters.set({ ...mockStore.filters(), date_to: '2024-12-31' });
      expect(component.sectionActiveCounts()['date']).toBe(2);
    });

    it('counts tag and composition_pattern for content section', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), tag: 'landscape' });
      expect(component.sectionActiveCounts()['content']).toBe(1);
      mockStore.filters.set({ ...mockStore.filters(), composition_pattern: 'rule_of_thirds' });
      expect(component.sectionActiveCounts()['content']).toBe(2);
    });

    it('counts camera and lens for equipment section', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), camera: 'Sony A7', lens: 'FE 85mm' });
      expect(component.sectionActiveCounts()['equipment']).toBe(2);
    });

    it('counts an active path_prefix for the folder section', () => {
      const mockStore = (component as any).store;
      expect(component.sectionActiveCounts()['folder']).toBe(0);
      mockStore.filters.set({ ...mockStore.filters(), path_prefix: '/photos/Family/' });
      expect(component.sectionActiveCounts()['folder']).toBe(1);
    });

    it('counts favorites_only, is_monochrome, hide_rejected for refine section', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), favorites_only: true, is_monochrome: true, hide_rejected: true });
      expect(component.sectionActiveCounts()['refine']).toBe(3);
    });

    it('counts manual_faces_need_review once in the refine section', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), hide_rejected: false });
      const before = component.sectionActiveCounts()['refine'];
      mockStore.filters.set({ ...mockStore.filters(), manual_faces_need_review: true });
      expect(component.sectionActiveCounts()['refine']).toBe(before + 1);
    });

    it('counts active metric filters by min/max key', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), min_score: '7', min_aesthetic: '6' });
      expect(component.sectionActiveCounts()['gallery.sidebar.quality']).toBe(2);
    });

    it('counts a metric filter once even when both min and max are set', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), min_score: '5', max_score: '9' });
      expect(component.sectionActiveCounts()['gallery.sidebar.quality']).toBe(1);
    });
  });

  describe('onDynamicRangeChange', () => {
    const iaaFilter = {
      id: 'aesthetic_iaa_range', labelKey: 'gallery.aesthetic_iaa_range',
      sectionKey: 'gallery.sidebar.extended_quality',
      minKey: 'min_aesthetic_iaa' as const, maxKey: 'max_aesthetic_iaa' as const,
      sliderMin: 0, sliderMax: 10, step: 0.5, spanWidth: 'w-16',
    };

    const isoFilter = {
      id: 'iso_range', labelKey: 'gallery.iso_range',
      sectionKey: 'gallery.sidebar.exposure_range',
      minKey: 'min_iso' as const, maxKey: 'max_iso' as const,
      sliderMin: 50, sliderMax: 25600, step: 50, spanWidth: 'w-20',
    };

    it('clears min filter at slider minimum', () => {
      const mockStore = (component as any).store;
      component.onDynamicRangeChange(iaaFilter, 'min', 0);
      expect(mockStore.updateFilterDebounced).toHaveBeenCalledWith('min_aesthetic_iaa', '');
    });

    it('redirects max to min when min is at default', () => {
      const mockStore = (component as any).store;
      component.onDynamicRangeChange(iaaFilter, 'max', 7.5);
      expect(mockStore.updateFilterDebounced).toHaveBeenCalledWith('min_aesthetic_iaa', '7.5');
    });

    it('clears max filter at slider maximum when min is set', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), min_aesthetic_iaa: '5' });
      component.onDynamicRangeChange(iaaFilter, 'max', 10);
      expect(mockStore.updateFilterDebounced).toHaveBeenCalledWith('max_aesthetic_iaa', '');
    });

    it('stores string value for non-boundary min', () => {
      const mockStore = (component as any).store;
      component.onDynamicRangeChange(iaaFilter, 'min', 6.5);
      expect(mockStore.updateFilterDebounced).toHaveBeenCalledWith('min_aesthetic_iaa', '6.5');
    });

    it('stores string value for non-boundary max when min is set', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), min_aesthetic_iaa: '3' });
      component.onDynamicRangeChange(iaaFilter, 'max', 7.5);
      expect(mockStore.updateFilterDebounced).toHaveBeenCalledWith('max_aesthetic_iaa', '7.5');
    });

    it('clears min at non-zero boundary (ISO 50)', () => {
      const mockStore = (component as any).store;
      component.onDynamicRangeChange(isoFilter, 'min', 50);
      expect(mockStore.updateFilterDebounced).toHaveBeenCalledWith('min_iso', '');
    });

    it('clears max at non-standard boundary (ISO 25600) when min is set', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), min_iso: '100' });
      component.onDynamicRangeChange(isoFilter, 'max', 25600);
      expect(mockStore.updateFilterDebounced).toHaveBeenCalledWith('max_iso', '');
    });
  });

  describe('folder filter', () => {
    it('clearFolderFilter empties path_prefix', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), path_prefix: '/photos/Family/' });
      component.clearFolderFilter();
      expect(mockStore.updateFilter).toHaveBeenCalledWith('path_prefix', '');
    });

    it('currentFolderName shows the last segment of the active prefix', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), path_prefix: '/photos/Family/2026/' });
      expect(component.currentFolderName()).toBe('2026');
    });
  });

  describe('semantic search threshold slider', () => {
    // Note: this suite tests the component's methods/computeds directly, the
    // same style every other describe block in this file uses -- the harness
    // never renders the template via fixture.createComponent/detectChanges,
    // so panel-visibility (@if show_semantic_search, pre-existing/unchanged)
    // is not exercised here either.
    beforeEach(() => {
      vi.useFakeTimers();
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it('searchThresholdValue mirrors the string filter as a number for the slider [value] binding', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), search_threshold: '12' });
      expect((component as any).searchThresholdValue()).toBe(12);
    });

    it('searchThresholdValue falls back to 0 when unseeded and config has not loaded', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), search_threshold: '' });
      mockStore.config.set(null);
      expect((component as any).searchThresholdValue()).toBe(0);
    });

    it('searchThresholdValue falls back to the config default (as a percent) when unseeded -- never a bare 0/blank readout while the server actually gates at its own default', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), search_threshold: '' });
      mockStore.config.set({ search_threshold_default: 0.05 });
      expect((component as any).searchThresholdValue()).toBe(5);
    });

    it('onSearchThresholdChange debounces the filter update by 400ms', () => {
      const mockStore = (component as any).store;
      component.onSearchThresholdChange(20);
      expect(mockStore.updateFilter).not.toHaveBeenCalled();

      vi.advanceTimersByTime(400);

      expect(mockStore.updateFilter).toHaveBeenCalledWith('search_threshold', '20');
    });

    it('the readout follows the drag immediately, rather than freezing for the debounce', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), search_threshold: '12' });

      component.onSearchThresholdChange(31);

      expect((component as any).searchThresholdValue()).toBe(31);
      expect(mockStore.updateFilter).not.toHaveBeenCalled();
    });

    it('drops the draft once the debounce fires, so the filter is the single source again', () => {
      const mockStore = (component as any).store;
      mockStore.filters.set({ ...mockStore.filters(), search_threshold: '12' });
      component.onSearchThresholdChange(31);

      vi.advanceTimersByTime(400);
      // The mock store never applies updateFilter, so the filter is still '12':
      // a draft that outlived the timeout would keep reading 31.
      expect((component as any).searchThresholdValue()).toBe(12);
    });

    it('a second drag replaces the draft rather than queueing a stale readout', () => {
      component.onSearchThresholdChange(31);
      vi.advanceTimersByTime(200);
      component.onSearchThresholdChange(44);

      expect((component as any).searchThresholdValue()).toBe(44);

      vi.advanceTimersByTime(400);

      expect((component as any).store.updateFilter).toHaveBeenCalledTimes(1);
      expect((component as any).store.updateFilter).toHaveBeenCalledWith('search_threshold', '44');
    });

    it('uses its own debounce timer, independent of the semantic-query search timer', () => {
      const mockStore = (component as any).store;
      const inputEvent = { target: { value: 'sunset' } } as unknown as Event;

      component.onSemanticSearch(inputEvent);
      component.onSearchThresholdChange(30);
      vi.advanceTimersByTime(400);

      expect(mockStore.updateFilter).toHaveBeenCalledWith('semanticQuery', 'sunset');
      expect(mockStore.updateFilter).toHaveBeenCalledWith('search_threshold', '30');
    });
  });

  describe('semantic search threshold slider (rendered)', () => {
    // The only block in this file that renders the template: the slider is Material
    // markup, so [value]/(valueChange) wiring and the aria attributes cannot be
    // reached through the component's methods alone.
    let fixture: ComponentFixture<GalleryFilterSidebarComponent>;
    let thumb: HTMLInputElement;

    beforeEach(() => {
      TestBed.resetTestingModule();
      const renderedStore = {
        ...mockStore,
        config: signal({ features: { show_semantic_search: true }, search_threshold_default: 0.05 }),
        cardWidth: signal(220),
        colorTemps: signal([]),
        hueBuckets: signal([]),
        patterns: signal([]),
        types: signal([]),
        currentAlbum: signal(null),
        galleryMode: signal('grid'),
        gpsLocationName: signal(''),
        virtualScroll: signal(false),
        setCardWidth: vi.fn(),
        setGalleryMode: vi.fn(),
        setVirtualScroll: vi.fn(),
      };

      TestBed.configureTestingModule({
        providers: [
          provideNativeDateAdapter(),
          // Tooltip hides wait for an animationend jsdom never fires unless animations are off.
          { provide: MATERIAL_ANIMATIONS, useValue: { animationsDisabled: true } },
          { provide: GalleryStore, useValue: renderedStore },
          { provide: I18nService, useValue: { t: vi.fn((k: string) => k), currentLang: vi.fn(() => 'en'), translations: vi.fn(() => ({})) } },
          { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
          { provide: AlbumService, useValue: { list: vi.fn(() => of({ albums: [] })) } },
          { provide: MatDialog, useValue: { open: vi.fn() } },
        ],
      });

      fixture = TestBed.createComponent(GalleryFilterSidebarComponent);
      fixture.detectChanges();
      thumb = fixture.nativeElement.querySelector('mat-slider input');
    });

    it('lists the advanced metric sections as top-level sections, with no wrapping panel', () => {
      const advanced = fixture.componentInstance.advancedFilterGroups();
      expect(advanced.length).toBeGreaterThan(0);
      const panels = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('mat-expansion-panel'));
      for (const group of advanced) {
        const panel = panels.find(el => el.querySelector('mat-panel-title')?.textContent?.includes(group.sectionKey));
        expect(panel, group.sectionKey).toBeDefined();
        expect(panel!.parentElement!.closest('mat-expansion-panel'), group.sectionKey).toBeNull();
      }
    });

    for (const [value, label] of [
      ['undecided', I18N.review.needs_review], ['kept', I18N.review.kept], ['rejected', I18N.review.rejected],
    ] as const) {
      it(`selects ${value}, blocks Hide rejected, and restores the toggle after All`, () => {
        const store = TestBed.inject(GalleryStore);
        store.filters.update(filters => ({ ...filters, review_status: '', hide_rejected: true }));
        fixture.detectChanges();
        const select = fixture.debugElement.queryAll(By.directive(MatSelect))
          .find(el => el.nativeElement.closest('mat-form-field')?.textContent.includes(I18N.review.status))!
          .injector.get(MatSelect);
        const container = TestBed.inject(OverlayContainer).getContainerElement();
        const hideRejected = () => Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('mat-checkbox'))
          .find(el => el.textContent?.includes(I18N.gallery.hide_rejected))!
          .querySelector('input') as HTMLInputElement;
        const choose = (text: string) => {
          select.open();
          fixture.detectChanges();
          const options = Array.from(container.querySelectorAll('mat-option'));
          expect(options.map(option => option.textContent?.trim())).toEqual([
            I18N.review.all, I18N.review.needs_review, I18N.review.kept, I18N.review.rejected,
          ]);
          const option = options.find(el => el.textContent?.trim() === text) as HTMLElement;
          option.click();
          fixture.detectChanges();
          expect(select.panelOpen).toBe(false);
        };

        // Review browsing remains available to a read-only viewer.
        expect(TestBed.inject(AuthService).isEdition()).toBe(false);
        expect(hideRejected().disabled).toBe(false);
        expect(hideRejected().checked).toBe(true);
        choose(label);
        expect(mockStore['updateFilter']).toHaveBeenLastCalledWith('review_status', value);
        store.filters.update(filters => ({ ...filters, review_status: value }));
        fixture.detectChanges();
        expect(select.value).toBe(value);
        expect(hideRejected().disabled).toBe(true);
        expect(hideRejected().checked).toBe(true);
        vi.mocked(store.updateFilter).mockClear();
        hideRejected().click();
        expect(store.updateFilter).not.toHaveBeenCalled();

        choose(I18N.review.all);
        expect(store.updateFilter).toHaveBeenLastCalledWith('review_status', '');
        store.filters.update(filters => ({ ...filters, review_status: '' }));
        fixture.detectChanges();
        expect(hideRejected().disabled).toBe(false);
        expect(hideRejected().checked).toBe(true);
        hideRejected().click();
        expect(store.updateFilter).toHaveBeenLastCalledWith('hide_rejected', false);
      });
    }

    it('offers face naming in People with no people and semantic search disabled', () => {
      TestBed.inject(GalleryStore).config.update(config => config ? {
        ...config, features: { ...config.features, show_semantic_search: false },
      } : config);
      fixture.detectChanges();
      const controls = Array.from(fixture.nativeElement.querySelectorAll('mat-checkbox')) as HTMLElement[];
      const control = controls.find(el => el.textContent?.includes('gallery.faces_need_names'))!;
      expect(control).toBeTruthy();
      expect(control.closest('mat-expansion-panel')?.textContent).toContain('gallery.sidebar.persons');
      (control.querySelector('input') as HTMLInputElement).click();
      expect(mockStore['updateFilter']).toHaveBeenCalledWith('faces_need_names', true);
    });

    it.each([false, true])('renders the manual-face review checkbox only for edition (edition=%s)', edition => {
      const auth = TestBed.inject(AuthService);
      vi.mocked(auth.isEdition).mockReturnValue(edition);
      fixture.detectChanges();
      const controls = Array.from(fixture.nativeElement.querySelectorAll('mat-checkbox')) as HTMLElement[];
      const control = controls.find(el => el.textContent?.includes('gallery.manual_faces_need_review'));
      expect(!!control).toBe(edition);
      if (control) {
        (control.querySelector('input') as HTMLInputElement).click();
        expect(mockStore['updateFilter']).toHaveBeenCalledWith('manual_faces_need_review', true);
      }
    });

    it.each([false, true])('describes face naming using actions available in edition=%s', edition => {
      const auth = TestBed.inject(AuthService);
      vi.mocked(auth.isEdition).mockReturnValue(edition);
      TestBed.inject(GalleryStore).filters.update(filters => ({ ...filters, faces_need_names: true }));
      fixture.detectChanges();
      const hint = fixture.nativeElement.querySelector('#face-naming-hint');
      expect(hint.textContent).toContain(edition ? 'gallery.faces_need_names_hint' : 'gallery.faces_need_names_readonly_hint');
      const input = fixture.nativeElement.querySelector('input[aria-describedby="face-naming-hint"]');
      expect(input).toBeTruthy();
    });

    it('closes its select overlay when the gallery parks', () => {
      const select = fixture.debugElement.query(By.directive(MatSelect)).injector.get(MatSelect);
      select.open();
      fixture.detectChanges();
      expect(select.panelOpen).toBe(true);
      fixture.componentInstance.closeOverlays();
      expect(select.panelOpen).toBe(false);
    });

    it.each(['kept', 'undecided', 'rejected'] as const)('disables rejected-only while review status is %s and restores it after clearing', status => {
      const filters = TestBed.inject(GalleryStore).filters;
      filters.update(current => ({ ...current, review_status: status, show_rejected: false }));
      fixture.detectChanges();
      const control = (Array.from(fixture.nativeElement.querySelectorAll('mat-checkbox')) as HTMLElement[])
        .find(element => element.textContent?.includes('rating.show_rejected'))!;
      const input = control.querySelector('input') as HTMLInputElement;
      expect(input.disabled).toBe(true);
      input.click();
      expect(mockStore['updateFilter']).not.toHaveBeenCalled();
      filters.update(current => ({ ...current, review_status: '' }));
      fixture.detectChanges();
      expect(input.disabled).toBe(false);
      input.click();
      expect(mockStore['updateFilter']).toHaveBeenCalledExactlyOnceWith('show_rejected', true);
    });

    it('offers no geolocation without the map feature and forwards the checkbox', () => {
      const labels = Array.from(fixture.nativeElement.querySelectorAll('mat-checkbox')) as HTMLElement[];
      const control = labels.find(el => el.textContent?.includes('gallery.no_geolocation'))!;
      expect(control).toBeTruthy();
      (control.querySelector('input') as HTMLInputElement).click();
      expect(mockStore['updateFilter']).toHaveBeenCalledWith('no_gps', '1');
    });

    it('renders the thumb seeded from the config default, announced with its unit', () => {
      expect(thumb).toBeTruthy();
      expect(thumb.value).toBe('5');
      expect(thumb.getAttribute('aria-valuetext')).toBe('5%');
      expect(thumb.getAttribute('aria-describedby')).toBe('semantic-search-threshold-hint');
      expect(fixture.nativeElement.querySelector('#semantic-search-threshold-hint')).toBeTruthy();
    });

    it('shows the grid / mosaic layout toggle below md too', () => {
      const label = [...(fixture.nativeElement as HTMLElement).querySelectorAll('span')]
        .find(e => e.textContent?.trim() === 'gallery.layout_mode');
      expect(label).toBeTruthy();
      const row = label!.parentElement!;
      expect(row.classList.contains('hidden')).toBe(false);
      expect(row.classList.contains('flex')).toBe(true);
    });

    it('hideTooltips takes a showing tooltip off the page', async () => {
      const tooltip = fixture.debugElement.queryAll(By.directive(MatTooltip))[0].injector.get(MatTooltip);
      tooltip.show(0);
      await new Promise(resolve => setTimeout(resolve, 30));
      const container = TestBed.inject(OverlayContainer).getContainerElement();
      expect(container.querySelector('.mat-mdc-tooltip')).not.toBeNull();
      fixture.componentInstance.hideTooltips();
      await new Promise(resolve => setTimeout(resolve, 30));
      expect(container.querySelector('.mat-mdc-tooltip')).toBeNull();
      expect(tooltip._isTooltipVisible()).toBe(false);
    });

    it('wires the thumb back to the component, readout and valuetext following the drag', () => {
      thumb.value = '31';
      thumb.dispatchEvent(new Event('input'));
      thumb.dispatchEvent(new Event('change'));
      fixture.detectChanges();

      expect(fixture.nativeElement.textContent).toContain('31%');
      expect(thumb.getAttribute('aria-valuetext')).toBe('31%');
    });
  });
});
