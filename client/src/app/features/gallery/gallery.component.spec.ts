import type { Mock } from 'vitest';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { computed, signal, TemplateRef, WritableSignal } from '@angular/core';
import { ActivatedRoute } from '@angular/router';
import { By } from '@angular/platform-browser';
import { PhotoCardComponent } from '../../shared/components/photo-card/photo-card.component';
import { GalleryPhotoMenuComponent } from './gallery-photo-menu.component';
import { PhotoTooltipComponent } from './photo-tooltip.component';
import { HttpErrorResponse } from '@angular/common/http';
import { Subject, of, throwError } from 'rxjs';
import { MatDialog } from '@angular/material/dialog';
import { MatBottomSheet } from '@angular/material/bottom-sheet';
import { MatTooltip } from '@angular/material/tooltip';
import { MatSidenav } from '@angular/material/sidenav';
import { provideNativeDateAdapter } from '@angular/material/core';
import { MatSnackBar } from '@angular/material/snack-bar';
import { LiveAnnouncer } from '@angular/cdk/a11y';
import { GalleryStore, GalleryFilters, DEFAULT_FILTERS } from './gallery.store';
import { buildApiParams, DISPLAY_OPTIONS_KEY } from './gallery-filters.util';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { AlbumService } from '../../core/services/album.service';
import { GalleryComponent } from './gallery.component';
import { I18N } from '../../core/i18n/keys';
import { ScoreClassPipe } from '../../shared/pipes/score.pipes';
import { MAX_COMPARE_PANES } from './synced-zoom.component';
import { gridColumnCount } from './gallery-rows.util';
import { ScanService } from '../../core/services/scan.service';
import { UndoService } from '../../core/services/undo.service';
import { SequenceKind } from '../../core/services/sequence-override.service';

describe('GalleryComponent', () => {
  let component: GalleryComponent;

   
  let mockStore: any;
  let mockApi: { thumbnailUrl: Mock; post: Mock; downloadUrl: Mock; getRaw: Mock };
  let mockAuth: Record<string, unknown>;
  // `translations` and `lang` are only read once the real template renders:
  // the translate pipe subscribes to the bundle even when `t` is stubbed.
  let mockI18n: {
    t: Mock;
    translations: WritableSignal<Record<string, unknown>>;
    lang: WritableSignal<string>;
  };
  let routeMock: { snapshot: { paramMap: { get: Mock }; queryParams: Record<string, string> } };

  beforeEach(() => {
    mockStore = {
      filters: signal<GalleryFilters>({ ...DEFAULT_FILTERS }),
      types: signal([
        { id: 'portrait', label: 'Portrait', count: 100 },
        { id: 'landscape', label: 'Landscape', count: 200 },
        { id: 'macro', label: 'Macro', count: 50 },
      ]),
      photos: signal([]),
      focusedPath: signal<string | null>(null),
      total: signal(0),
      loading: signal(false),
      loadError: signal(false),
      loadErrorKey: signal<string | undefined>(undefined),
      hasMore: signal(false),
      cameras: signal([]),
      lenses: signal([]),
      tags: signal([]),
      persons: signal([]),
      config: signal(null),
      activeFilterCount: signal(0),
      filterDrawerOpen: signal(false),
      currentAlbum: signal(null),
      initializing: signal(false),
      galleryMounts: signal(0),
      galleryMode: signal('mosaic'),
      cardWidth: signal(300),
      virtualScroll: signal(false),
      setFilterDrawerOpen: vi.fn(),
      loadConfig: vi.fn(() => Promise.resolve()),
      loadFilterOptions: vi.fn(() => Promise.resolve()),
      loadTypeCounts: vi.fn(() => Promise.resolve()),
      loadPhotos: vi.fn(() => Promise.resolve()),
      reloadPhotos: vi.fn(() => Promise.resolve()),
      updateFilter: vi.fn(() => Promise.resolve()),
      resetFilters: vi.fn(() => Promise.resolve()),
      nextPage: vi.fn(() => Promise.resolve()),
      toggleFavorite: vi.fn(),
      toggleRejected: vi.fn(),
      selectedPaths: signal(new Set<string>()),
      excludedPaths: signal(new Set<string>()),
      selectionScope: signal<'paths' | 'view'>('paths'),
      viewScopeSelected: signal(false),
      canScopeSelectionToView: signal(true),
      selectionCount: signal(0),
      selectedLoadedPaths: computed(() => {
        const selected = mockStore.selectedPaths() as Set<string>;
        const excluded = mockStore.excludedPaths() as Set<string>;
        return (mockStore.photos() as { path: string }[])
          .filter(p => (mockStore.viewScopeSelected() ? !excluded.has(p.path) : selected.has(p.path)))
          .map(p => p.path);
      }),
      toggleSelection: vi.fn(),
      selectAll: vi.fn(),
      selectAllLoaded: vi.fn(),
      selectWholeView: vi.fn(),
      invertSelection: vi.fn(),
      clearSelection: vi.fn(),
      restoreSelection: vi.fn(),
      restoreSnapshot: vi.fn(() => Promise.resolve()),
      countInView: vi.fn(() => Promise.resolve(650)),
      pathsInView: vi.fn(() => Promise.resolve([] as string[])),
      filterPayload: vi.fn(() => ({ page: '1' })),
      viewSnapshot: signal(null),
      pinnedPaths: signal<string[] | null>(null),
      pinnedGroups: signal(new Map<string, number>()),
      pinnedMarks: signal(new Map<string, 'keep' | 'remove'>()),
      userMarks: signal(new Map<string, 'keep' | 'remove'>()),
      hasReview: signal(false),
      reviewLegend: signal({ groups: 0, keep: 0, remove: 0 }),
      reviewGroupCounts: signal(new Map<number, { count: number; keep: number; remove: number }>()),
      pinnedLabels: signal(new Map<number, { key: string; params: Record<string, string | number> }>()),
      pinnedKinds: signal(new Map<number, string>()),
      pinnedReasons: signal(new Map<string, { key: string; value?: number }>()),
      reviewChanges: signal({ changed: 0, keep: 0, remove: 0 }),
      appliedMarks: signal(new Map<string, { mark: 'keep' | 'remove'; receiptId: string }>()),
      appliedGroups: signal(new Map<number, { receiptId: string; keptWhole: number; unavailable: boolean }>()),
      appliedReceiptList: signal([] as Record<string, unknown>[]),
      applyPlan: signal({ units: [] as Record<string, unknown>[], byGroup: new Map<number, Record<string, unknown>>(), counts: { groups: 0, reject: 0, unreject: 0 } }),
      applying: signal(false),
      applyGroups: vi.fn(() => Promise.resolve(true)),
      undoApplied: vi.fn(() => Promise.resolve()),
      review: signal({ keep: [] as string[], remove: [] as string[], groups_total: 0, groups_visited: 0, groups_changed: 0 }),
      markGroupsVisited: vi.fn(),
      setGroupMarks: vi.fn(),
      setReviewMark: vi.fn(),
      clearPinned: vi.fn(() => Promise.resolve()),
      filterKey: vi.fn((f?: GalleryFilters) => JSON.stringify(buildApiParams(f ?? mockStore.filters(), false))),
      hiddenSummary: signal({ total: 0, blinks: 0, bursts: 0, duplicates: 0 }),
      hiddenFiltersStash: signal(null),
      showAllHidden: vi.fn(),
      restoreHidden: vi.fn(),
      updateFilters: vi.fn(() => Promise.resolve()),
      setRating: vi.fn(),
      batchFavorite: vi.fn(() => Promise.resolve({ snapshot: new Map(), targeted: 0, count: 0 })),
      batchReject: vi.fn(() => Promise.resolve({ snapshot: new Map(), targeted: 0, count: 0 })),
      batchRating: vi.fn(() => Promise.resolve({ snapshot: new Map(), targeted: 0, count: 0 })),
      patchSequenceOverride: vi.fn(),
      removePhotos: vi.fn(),
      // Read only once the real template renders -- the toolbar, the filter
      // sidebar and the slideshow all pull off the store directly.
      slideshowActive: signal(false),
      patterns: signal([]),
      colorTemps: signal([]),
      hueBuckets: signal([]),
      metricRanges: signal({}),
      gpsLocationName: signal(''),
      viewFilterParams: signal({}),
    };

    mockApi = {
      thumbnailUrl: vi.fn((path: string) => `/thumbnail?path=${path}`),
      post: vi.fn(() => of({ success: true, overridden: 0, skipped: 0, kind: null })),
      downloadUrl: vi.fn((path: string) => `/download?path=${path}`),
      getRaw: vi.fn(() => of(new Blob(['x']))),
    };

    mockAuth = {
      identity: vi.fn(() => '0|'),
      isEdition: vi.fn(() => false),
      downloadProfiles: vi.fn(() => []),
      hasFeature: vi.fn(() => false),
      isMultiUser: vi.fn(() => false),
      isSuperadmin: vi.fn(() => false),
      editionPasswordRequired: vi.fn(() => false),
      loginPasswordRequired: vi.fn(() => false),
    };

    mockI18n = {
      t: vi.fn((key: string) => key),
      translations: signal<Record<string, unknown>>({}),
      lang: signal('en'),
    };

    routeMock = { snapshot: { paramMap: { get: vi.fn(() => null) }, queryParams: {} } };

    TestBed.configureTestingModule({
      providers: [
        provideNativeDateAdapter(),
        { provide: GalleryStore, useValue: mockStore },
        { provide: ApiService, useValue: mockApi },
        { provide: AuthService, useValue: mockAuth },
        { provide: I18nService, useValue: mockI18n },
        {
          provide: AlbumService,
          useValue: {
            list: vi.fn(() => of({ albums: [] })),
            get: vi.fn(() => of({})),
            addPhotos: vi.fn(() => of({ added: 0 })),
          },
        },
        { provide: ActivatedRoute, useValue: routeMock },
        { provide: ScanService, useValue: { canLaunch: signal(false), openLauncher: vi.fn(() => Promise.resolve(false)) } },
        { provide: MatDialog, useValue: { open: vi.fn() } },
        { provide: MatBottomSheet, useValue: { open: vi.fn() } },
        { provide: LiveAnnouncer, useValue: { announce: vi.fn(() => Promise.resolve()) } },
        // Returns a ref stub, not undefined: UndoService reads onAction() /
        // afterDismissed() off whatever open() hands back.
        {
          provide: MatSnackBar,
          useValue: {
            open: vi.fn(() => ({
              onAction: () => new Subject<void>(),
              afterDismissed: () => new Subject<void>(),
            })),
          },
        },
      ],
    });
    component = TestBed.runInInjectionContext(() => new GalleryComponent());
  });

  it('renders the translated reason a similar search cannot run instead of a silent empty gallery', () => {
    mockStore.loadError.set(true);
    mockStore.loadErrorKey.set(I18N.similar.no_visual_features);
    const fixture = TestBed.createComponent(GalleryComponent);
    fixture.detectChanges();
    const alerts = fixture.nativeElement.querySelectorAll('[role="alert"]');
    expect(alerts).toHaveLength(1);
    expect(alerts[0].textContent).toContain(I18N.similar.no_visual_features);
    expect(alerts[0].textContent).not.toContain(I18N.gallery.load_error.message);
    fixture.destroy();
  });

  it('falls back to the generic load-error message when the server gave no reason', () => {
    mockStore.loadError.set(true);
    const fixture = TestBed.createComponent(GalleryComponent);
    fixture.detectChanges();
    expect(fixture.nativeElement.querySelector('[role="alert"]')?.textContent).toContain(I18N.gallery.load_error.message);
    fixture.destroy();
  });

  // Shared by every cursor describe below. The component is built without a
  // fixture, so each of these stands in for something the template would
  // otherwise wire up, invoked straight on the instance.
  function activeIndex(): number {
    return (component as unknown as { activeIndex(): number }).activeIndex();
  }

  function hasActivePhoto(): boolean {
    return (component as unknown as { hasActivePhoto(): boolean }).hasActivePhoto();
  }

  function click(photo: { path: string }, index: number): void {
    (component as unknown as {
      toggleSelection(p: unknown, e: MouseEvent | undefined, i: number): void;
    }).toggleSelection(photo, undefined, index);
  }

  function press(key: string): void {
    const ev = new KeyboardEvent('keydown', { key });
    Object.defineProperty(ev, 'target', { value: null, configurable: true });
    (component as unknown as { onGridKeydown(e: KeyboardEvent): void }).onGridKeydown(ev);
  }

  describe('ScoreClassPipe', () => {
    let pipe: ScoreClassPipe;

    beforeEach(() => {
      pipe = new ScoreClassPipe();
    });

    it('should return green class for score >= 8 (no config)', () => {
      expect(pipe.transform(8, null)).toBe('bg-green-600 text-white');
      expect(pipe.transform(9.5, null)).toBe('bg-green-600 text-white');
      expect(pipe.transform(10, null)).toBe('bg-green-600 text-white');
    });

    it('should return yellow class for score >= 6 and < 8 (no config)', () => {
      expect(pipe.transform(6, null)).toBe('bg-yellow-600 text-white');
      expect(pipe.transform(7.9, null)).toBe('bg-yellow-600 text-white');
    });

    it('should return orange class for score >= 4 and < 6 (no config)', () => {
      expect(pipe.transform(4, null)).toBe('bg-orange-600 text-white');
      expect(pipe.transform(5.9, null)).toBe('bg-orange-600 text-white');
    });

    it('should return red class for score < 4 (no config)', () => {
      expect(pipe.transform(3.9, null)).toBe('bg-red-600 text-white');
      expect(pipe.transform(0, null)).toBe('bg-red-600 text-white');
      expect(pipe.transform(1, null)).toBe('bg-red-600 text-white');
    });

    it('should use config thresholds when provided', () => {
      const config = { quality_thresholds: { excellent: 9, great: 7, good: 5, best: 10 } };
      expect(pipe.transform(9, config)).toBe('bg-green-600 text-white');
      expect(pipe.transform(7, config)).toBe('bg-yellow-600 text-white');
      expect(pipe.transform(5, config)).toBe('bg-orange-600 text-white');
      expect(pipe.transform(4, config)).toBe('bg-red-600 text-white');
    });
  });

  describe('keyboard rate-and-advance (onGridKeydown)', () => {
    function keyEvent(key: string, target: Partial<HTMLElement> | null = null): KeyboardEvent {
      const ev = new KeyboardEvent('keydown', { key });
      Object.defineProperty(ev, 'target', { value: target, configurable: true });
      return ev;
    }

    beforeEach(() => {
      mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }, { path: '/c.jpg' }]);
      mockStore.config.set({ features: { show_rating_controls: true } });
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      (component as unknown as { activeIndex: { set(v: number): void } }).activeIndex.set(0);
    });

    function fire(ev: KeyboardEvent) {
      (component as unknown as { onGridKeydown(e: KeyboardEvent): void }).onGridKeydown(ev);
    }

    it('sets the star rating and advances on digit keys', () => {
      fire(keyEvent('3'));
      expect(mockStore.setRating).toHaveBeenCalledWith('/a.jpg', 3);
      expect(activeIndex()).toBe(1);
    });

    it('rejects and advances on X', () => {
      fire(keyEvent('x'));
      expect(mockStore.toggleRejected).toHaveBeenCalledWith('/a.jpg');
      expect(activeIndex()).toBe(1);
    });

    it('toggles favorite WITHOUT advancing on F', () => {
      fire(keyEvent('f'));
      expect(mockStore.toggleFavorite).toHaveBeenCalledWith('/a.jpg');
      expect(activeIndex()).toBe(0);
    });

    it('ignores rating keys while typing in an input', () => {
      fire(keyEvent('1', { tagName: 'INPUT' } as HTMLElement));
      expect(mockStore.setRating).not.toHaveBeenCalled();
    });

    it('ignores rating keys for non-edition users', () => {
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => false);
      fire(keyEvent('1'));
      expect(mockStore.setRating).not.toHaveBeenCalled();
    });

    it('ignores rating keys when the feature flag is off', () => {
      mockStore.config.set({ features: { show_rating_controls: false } });
      fire(keyEvent('1'));
      expect(mockStore.setRating).not.toHaveBeenCalled();
    });
  });

  describe('the current photo', () => {
    beforeEach(() => {
      mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }, { path: '/c.jpg' }]);
      mockStore.config.set({ features: { show_rating_controls: true } });
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
    });

    describe('the focused-photo mirror read by ui_get_context', () => {
      const setCursor = (index: number): void =>
        (component as unknown as { setCursor(i: number): void }).setCursor(index);
      let hasFocus: ReturnType<typeof vi.spyOn>;
      beforeEach(() => {
        hasFocus = vi.spyOn(document, 'hasFocus').mockReturnValue(true);
      });
      afterEach(() => hasFocus.mockRestore());

      it('follows the keyboard cursor', () => {
        click({ path: '/a.jpg' }, 0);
        press('ArrowRight');
        expect(mockStore.focusedPath()).toBe('/b.jpg');
      });

      it('clears on setCursor(-1) while the window has focus', () => {
        click({ path: '/b.jpg' }, 1);
        setCursor(-1);
        expect(mockStore.focusedPath()).toBeNull();
      });

      it('clears when the panel is released', () => {
        click({ path: '/b.jpg' }, 1);
        (component as unknown as { releasePanel(): void }).releasePanel();
        expect(mockStore.focusedPath()).toBeNull();
      });

      it('survives the window losing focus, although the cursor itself goes', () => {
        click({ path: '/b.jpg' }, 1);
        hasFocus.mockReturnValue(false);
        (component as unknown as { onGridFocusOut(e: FocusEvent): void })
          .onGridFocusOut({ relatedTarget: null } as unknown as FocusEvent);
        expect(activeIndex()).toBe(-1);
        expect(mockStore.focusedPath()).toBe('/b.jpg');
      });

      it('is not touched by hover', () => {
        click({ path: '/b.jpg' }, 1);
        (component as unknown as { tooltipPhoto: { set(p: unknown): void } }).tooltipPhoto.set({ path: '/c.jpg' });
        expect(mockStore.focusedPath()).toBe('/b.jpg');
      });

      it('clears once its photo leaves the list, even with the cursor already dropped', () => {
        click({ path: '/b.jpg' }, 1);
        hasFocus.mockReturnValue(false);
        (component as unknown as { onGridFocusOut(e: FocusEvent): void })
          .onGridFocusOut({ relatedTarget: null } as unknown as FocusEvent);
        mockStore.photos.set([{ path: '/a.jpg' }, { path: '/c.jpg' }]);
        TestBed.tick();
        expect(mockStore.focusedPath()).toBeNull();
      });
    });

    it('marks nothing before the cursor has ever moved, so nothing is dimmed at rest', () => {
      expect(activeIndex()).toBe(-1);
      expect(hasActivePhoto()).toBe(false);
    });

    it('moves onto the photo the pointer just clicked', () => {
      click({ path: '/c.jpg' }, 2);
      expect(activeIndex()).toBe(2);
      expect(hasActivePhoto()).toBe(true);
    });

    it('still hands the click to the store', () => {
      const photo = { path: '/b.jpg' };
      click(photo, 1);
      expect(mockStore.toggleSelection).toHaveBeenCalledWith(photo, undefined);
    });

    it('rates the photo that was clicked, not the one the arrow keys were left on', () => {
      // The defect: the pointer never moved the cursor, so a rating typed after
      // a click landed on whatever the keyboard had been on. Silently.
      press('ArrowRight');
      expect(activeIndex()).toBe(1);
      click({ path: '/c.jpg' }, 2);
      press('3');
      expect(mockStore.setRating).toHaveBeenCalledWith('/c.jpg', 3);
    });

    it('still moves with the arrow keys once a click has placed it', () => {
      click({ path: '/a.jpg' }, 0);
      press('ArrowRight');
      expect(activeIndex()).toBe(1);
      press('ArrowLeft');
      expect(activeIndex()).toBe(0);
      press('End');
      expect(activeIndex()).toBe(2);
    });

    it('reports no current photo when a shorter result set leaves the cursor past the end', () => {
      // Otherwise the grid would render every card dimmed with none marked.
      click({ path: '/c.jpg' }, 2);
      mockStore.photos.set([{ path: '/a.jpg' }]);
      expect(hasActivePhoto()).toBe(false);
    });

    describe('follows the photo, not the slot it was in', () => {
      // A bounds check only catches the result set getting shorter. One of the
      // same length or longer keeps the index legal, so the marker reframes
      // whatever photo has moved into that slot -- and the next rating keystroke
      // lands there.
      it('re-finds the marked photo when the results are reordered', () => {
        click({ path: '/c.jpg' }, 2);

        mockStore.photos.set([{ path: '/c.jpg' }, { path: '/a.jpg' }, { path: '/b.jpg' }]);
        TestBed.tick();

        expect(activeIndex()).toBe(0);
        press('3');
        expect(mockStore.setRating).toHaveBeenCalledWith('/c.jpg', 3);
      });

      it('drops the cursor when the marked photo is gone but the count is not', () => {
        click({ path: '/c.jpg' }, 2);

        mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }, { path: '/d.jpg' }]);
        TestBed.tick();

        expect(activeIndex()).toBe(-1);
        expect(hasActivePhoto()).toBe(false);
      });

      it('leaves the cursor alone when the photo has not moved', () => {
        click({ path: '/b.jpg' }, 1);

        mockStore.photos.set([
          { path: '/a.jpg' }, { path: '/b.jpg' }, { path: '/c.jpg' }, { path: '/d.jpg' },
        ]);
        TestBed.tick();

        expect(activeIndex()).toBe(1);
      });

      it('does nothing at all before the cursor has been placed', () => {
        mockStore.photos.set([{ path: '/x.jpg' }, { path: '/y.jpg' }]);
        TestBed.tick();

        expect(activeIndex()).toBe(-1);
      });

      // The three sites that move the cursor have to record the photo as well
      // as the index; a missed one leaves the marker following the slot again.
      it('follows a cursor the arrow keys placed', () => {
        press('ArrowRight');
        expect(activeIndex()).toBe(1);

        mockStore.photos.set([{ path: '/c.jpg' }, { path: '/a.jpg' }, { path: '/b.jpg' }]);
        TestBed.tick();

        expect(activeIndex()).toBe(2);
      });

      it('follows a cursor the rate-and-advance keys left behind', () => {
        click({ path: '/a.jpg' }, 0);
        press('3');
        expect(activeIndex()).toBe(1);

        mockStore.photos.set([{ path: '/b.jpg' }, { path: '/a.jpg' }, { path: '/c.jpg' }]);
        TestBed.tick();

        expect(activeIndex()).toBe(0);
      });
    });
  });

  describe('focus follows the current photo', () => {
    let grid: HTMLElement;
    let barRoot: HTMLElement;
    let bar: HTMLButtonElement;

    beforeEach(() => {
      mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }, { path: '/c.jpg' }]);
      mockStore.config.set({ features: { show_rating_controls: true } });
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);

      // The component is built without a fixture, so the grid its template
      // would render is stood up by hand: focusCard looks a card up by its
      // data-pidx and focuses the first [tabindex] inside it, and the key
      // handler is bound on the role="grid" ancestor.
      grid = document.createElement('div');
      grid.setAttribute('role', 'grid');
      grid.tabIndex = 0;
      for (const index of [0, 1, 2]) {
        const card = document.createElement('div');
        card.setAttribute('data-pidx', String(index));
        const tile = document.createElement('div');
        tile.tabIndex = 0;
        // jsdom lays nothing out and so implements no scrolling, but focusCard
        // really does make the call and it has to land somewhere. Both ends of
        // the card are stubbed because which one is scrolled is the point: the
        // tile takes focus, the card -- which is where scroll-margin lives --
        // is what gets scrolled.
        card.scrollIntoView = vi.fn();
        tile.scrollIntoView = vi.fn();
        card.appendChild(tile);
        grid.appendChild(card);
      }
      document.body.appendChild(grid);

      // Stands in for the action bar's Clear button: outside the grid, and
      // about to be unmounted by the very click that put focus on it. The
      // wrapper carries the marker the grid's focusout handler looks for.
      barRoot = document.createElement('div');
      barRoot.setAttribute('data-selection-bar', '');
      bar = document.createElement('button');
      barRoot.appendChild(bar);
      document.body.appendChild(barRoot);
    });

    afterEach(() => {
      grid.remove();
      barRoot.remove();
    });

    function cardAt(index: number): HTMLElement {
      return grid.querySelector(`[data-pidx="${index}"]`) as HTMLElement;
    }

    function tileAt(index: number): HTMLElement {
      return grid.querySelector(`[data-pidx="${index}"] [tabindex]`) as HTMLElement;
    }

    function clear(): void {
      (component as unknown as { clearSelection(): void }).clearSelection();
    }

    function focusOut(next: HTMLElement | null): void {
      (component as unknown as { onGridFocusOut(e: FocusEvent): void })
        .onGridFocusOut({ relatedTarget: next } as unknown as FocusEvent);
    }

    it('puts the cursor and the focus on the same card when a photo is clicked', () => {
      click({ path: '/c.jpg' }, 2);
      expect(activeIndex()).toBe(2);
      expect(document.activeElement).toBe(tileAt(2));
      // The card, not the tile: scroll-margin does not inherit, and the
      // clearance that lifts the photo out from under the action bar is
      // declared on the card host. Scrolling the tile asks an element that
      // carries none, so the clearance is silently dropped.
      expect(cardAt(2).scrollIntoView).toHaveBeenCalledWith({ block: 'nearest' });
      expect(tileAt(2).scrollIntoView).not.toHaveBeenCalled();
    });

    it('hands focus back to the marked photo when the selection is cleared', () => {
      click({ path: '/b.jpg' }, 1);
      bar.focus();
      expect(document.activeElement).toBe(bar);

      clear();

      expect(document.activeElement).toBe(tileAt(1));
    });

    it('leaves focus somewhere the grid key handler still receives events', () => {
      // The invariant as the user meets it: a marker is drawn, so the arrow
      // keys have to work. onGridKeydown is bound on the grid, which makes that
      // true only while focus is inside one -- and <body> is not.
      click({ path: '/b.jpg' }, 1);
      bar.focus();
      clear();

      const seen: string[] = [];
      grid.addEventListener('keydown', event => seen.push((event as KeyboardEvent).key));
      (document.activeElement as HTMLElement)
        .dispatchEvent(new KeyboardEvent('keydown', { key: 'ArrowRight', bubbles: true }));

      expect(seen).toEqual(['ArrowRight']);
    });

    it('keeps the marker and the keystroke target agreeing after a clear', () => {
      click({ path: '/b.jpg' }, 1);
      bar.focus();
      clear();

      expect(activeIndex()).toBe(1);
      expect(document.activeElement).toBe(tileAt(1));
      press('3');
      expect(mockStore.setRating).toHaveBeenCalledWith('/b.jpg', 3);
    });

    it('brings focus back from a batch action that empties the selection too', async () => {
      // The Clear button is only the shortest way in. Every batch action ends
      // the same way, from a control on the same bar.
      click({ path: '/b.jpg' }, 1);
      bar.focus();

      await (component as unknown as { batchFavorite(): Promise<void> }).batchFavorite();

      expect(mockStore.clearSelection).toHaveBeenCalled();
      expect(document.activeElement).toBe(tileAt(1));
    });

    it('does not re-focus or re-scroll for an Escape that came from the grid', () => {
      click({ path: '/b.jpg' }, 1);
      mockStore.selectionCount.set(1);
      (cardAt(1).scrollIntoView as unknown as Mock).mockClear();

      press('Escape');

      expect(mockStore.clearSelection).toHaveBeenCalled();
      expect(document.activeElement).toBe(tileAt(1));
      expect(cardAt(1).scrollIntoView).not.toHaveBeenCalled();
    });

    it('does not chase a cursor a narrower filter has left pointing past the end', () => {
      // Nothing is marked in that state, so there is no promise to keep, and
      // the card still standing at that index until the grid re-renders is not
      // the photo the cursor means.
      click({ path: '/c.jpg' }, 2);
      mockStore.photos.set([{ path: '/a.jpg' }]);
      bar.focus();

      clear();

      expect(document.activeElement).toBe(bar);
    });

    it('hands focus back without moving the viewport', () => {
      // The card is still exactly where the user left it, and the action bar
      // unmounting is not a reason to scroll the gallery under them.
      click({ path: '/b.jpg' }, 1);
      (cardAt(1).scrollIntoView as unknown as Mock).mockClear();
      bar.focus();

      clear();

      expect(document.activeElement).toBe(tileAt(1));
      expect(cardAt(1).scrollIntoView).not.toHaveBeenCalled();
    });

    describe('the cursor is dropped when focus leaves the grid', () => {
      // Without this, one mouse click dims the gallery for the rest of the
      // session: the marker fades every other card, and a mouse-only user
      // never puts focus back into a grid to move it off.
      it('resets when focus moves to something outside the grid', () => {
        const sidebar = document.createElement('input');
        document.body.appendChild(sidebar);
        click({ path: '/b.jpg' }, 1);

        focusOut(sidebar);

        expect(activeIndex()).toBe(-1);
        expect(hasActivePhoto()).toBe(false);
        sidebar.remove();
      });

      it('resets when focus falls to the page rather than to an element', () => {
        click({ path: '/b.jpg' }, 1);

        focusOut(null);

        expect(activeIndex()).toBe(-1);
      });

      it('does not reset while the cursor is only moving between cards', () => {
        click({ path: '/a.jpg' }, 0);

        focusOut(tileAt(2));

        expect(activeIndex()).toBe(0);
      });

      it('does not reset for the action bar, which still has to hand focus back', () => {
        click({ path: '/b.jpg' }, 1);

        focusOut(bar);
        expect(activeIndex()).toBe(1);

        clear();
        expect(document.activeElement).toBe(tileAt(1));
      });
    });
  });

  // Every other spec in this file hand-builds the grid, so the three template
  // expressions the marker rides on -- `row.startIndex + i` in the windowed and
  // mosaic branches, a bare `i` in the plain grid -- are never rendered.
  // Dropping `row.startIndex +` from one of them would put the marker on the
  // wrong photo with the whole suite green. These render the real template and
  // identify cards by their position in the grid, never by the data-pidx the
  // same expression writes.
  describe('the marker lands on the card that was clicked (rendered)', () => {
    const photos = Array.from({ length: 12 }, (_, n) => ({
      path: `/p${n}.jpg`, filename: `p${n}.jpg`, image_width: 4000, image_height: 3000,
    }));
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
      vi.unstubAllGlobals();
    });

    function render(mode: 'grid' | 'mosaic', virtual: boolean): HTMLElement[] {
      mockStore.photos.set(photos);
      mockStore.config.set({ features: { show_rating_controls: true } });
      mockStore.galleryMode.set(mode);
      mockStore.virtualScroll.set(virtual);
      fixture = TestBed.createComponent(GalleryComponent);
      const instance = fixture.componentInstance as unknown as {
        desktop: { setup(): void };
        containerWidth: { set(v: number): void };
      };
      if (mode === 'mosaic' || virtual) {
        // The row-based branches need a desktop-width container that has been
        // measured, and jsdom lays nothing out: widen the media query the way
        // the rail specs do, and feed the width the ResizeObserver would have.
        vi.stubGlobal('matchMedia', (media: string) => ({
          matches: true, media, addEventListener() {}, removeEventListener() {},
        }));
        instance.desktop.setup();
        instance.containerWidth.set(1200);
      }
      fixture.detectChanges();
      // A branch that quietly fell back to the plain grid would satisfy every
      // assertion below without ever rendering the expression under test.
      expect(fixture.componentInstance.effectiveGalleryMode()).toBe(mode);
      expect(fixture.componentInstance.virtualOn()).toBe(virtual);
      const cards = [...fixture.nativeElement.querySelectorAll('app-photo-card')] as HTMLElement[];
      // Two rows at least, so the card the specs reach for is never in the first.
      expect(cards.length).toBeGreaterThan(gridColumnCount(1200 - 32, 300, 8, true));
      return cards;
    }

    function clickCard(card: HTMLElement): void {
      (card.querySelector('[role="button"]') as HTMLElement).click();
      fixture!.detectChanges();
    }

    function markedCard(cards: HTMLElement[]): number {
      return cards.findIndex(c => c.querySelector('[aria-current="true"]'));
    }

    for (const [name, mode, virtual] of [
      ['plain grid', 'grid', false],
      ['mosaic', 'mosaic', false],
      ['windowed rows', 'mosaic', true],
    ] as const) {
      it(`indexes every card by its place in the results (${name})`, () => {
        const cards = render(mode, virtual);
        expect(cards.map(c => c.getAttribute('data-pidx')))
          .toEqual(cards.map((_, n) => String(n)));
      });

      it(`marks the card that was clicked, not the one at its offset in the row (${name})`, () => {
        const cards = render(mode, virtual);
        const target = cards.length - 2; // past the first row in every branch

        clickCard(cards[target]);

        expect(markedCard(cards)).toBe(target);
      });

      // The handler is unit-tested above; what only a rendered template can say
      // is that all three grid containers are actually bound to it.
      it(`drops the marker when focus leaves the grid (${name})`, () => {
        const cards = render(mode, virtual);
        clickCard(cards[cards.length - 2]);
        expect(markedCard(cards)).toBeGreaterThan(-1);

        (fixture!.nativeElement.querySelector('[role="grid"]') as HTMLElement)
          .dispatchEvent(new FocusEvent('focusout', { bubbles: true, relatedTarget: null }));
        fixture!.detectChanges();

        expect(markedCard(cards)).toBe(-1);
      });
    }
  });

  describe('ngOnInit()', () => {
    it('should call store.loadConfig, loadFilterOptions, loadTypeCounts, and loadPhotos', async () => {
      await component.ngOnInit();

      expect(mockStore.loadConfig).toHaveBeenCalled();
      expect(mockStore.loadFilterOptions).toHaveBeenCalled();
      expect(mockStore.loadTypeCounts).toHaveBeenCalled();
      expect(mockStore.loadPhotos).toHaveBeenCalled();
    });

    it('should call loadConfig before loadFilterOptions and loadTypeCounts', async () => {
      const callOrder: string[] = [];
      mockStore.loadConfig.mockImplementation(() => {
        callOrder.push('loadConfig');
        return Promise.resolve();
      });
      mockStore.loadFilterOptions.mockImplementation(() => {
        callOrder.push('loadFilterOptions');
        return Promise.resolve();
      });
      mockStore.loadTypeCounts.mockImplementation(() => {
        callOrder.push('loadTypeCounts');
        return Promise.resolve();
      });
      mockStore.loadPhotos.mockImplementation(() => {
        callOrder.push('loadPhotos');
        return Promise.resolve();
      });

      await component.ngOnInit();

      expect(callOrder.indexOf('loadConfig')).toBeLessThan(
        callOrder.indexOf('loadFilterOptions'),
      );
      expect(callOrder.indexOf('loadConfig')).toBeLessThan(
        callOrder.indexOf('loadTypeCounts'),
      );
    });

    it('should call loadPhotos before loadFilterOptions and loadTypeCounts', async () => {
      const callOrder: string[] = [];
      mockStore.loadConfig.mockImplementation(() => {
        callOrder.push('loadConfig');
        return Promise.resolve();
      });
      mockStore.loadFilterOptions.mockImplementation(() => {
        callOrder.push('loadFilterOptions');
        return Promise.resolve();
      });
      mockStore.loadTypeCounts.mockImplementation(() => {
        callOrder.push('loadTypeCounts');
        return Promise.resolve();
      });
      mockStore.loadPhotos.mockImplementation(() => {
        callOrder.push('loadPhotos');
        return Promise.resolve();
      });

      await component.ngOnInit();

      expect(callOrder.indexOf('loadPhotos')).toBeLessThan(
        callOrder.indexOf('loadFilterOptions'),
      );
      expect(callOrder.indexOf('loadPhotos')).toBeLessThan(
        callOrder.indexOf('loadTypeCounts'),
      );
    });

    it('reloads instead of restoring when the URL carries different query params (issue #70)', async () => {
      mockStore.photos.set([{ path: '/a.jpg' }]);
      mockStore.viewSnapshot.set({ scrollTop: 0, albumId: null, filterKey: mockStore.filterKey() });
      routeMock.snapshot.queryParams = {
        date_from: '2026-01-01', date_to: '2026-01-01', sort: 'date_taken', sort_direction: 'DESC',
      };

      await component.ngOnInit();

      expect(mockStore.loadConfig).toHaveBeenCalled();
      expect(mockStore.loadPhotos).toHaveBeenCalled();
    });

    it('restores the previous view when the URL matches the snapshot', async () => {
      mockStore.photos.set([{ path: '/a.jpg' }]);
      mockStore.viewSnapshot.set({ scrollTop: 0, albumId: null, filterKey: mockStore.filterKey() });

      await component.ngOnInit();

      expect(mockStore.loadConfig).not.toHaveBeenCalled();
      expect(mockStore.loadPhotos).not.toHaveBeenCalled();
      expect(mockStore.loadTypeCounts).toHaveBeenCalled();
    });

    it('should show photos and stop initializing when a filter-option request never resolves', async () => {
      mockStore.loadFilterOptions.mockImplementation(() => new Promise<void>(() => {}));
      mockStore.loadPhotos.mockImplementation(() => {
        mockStore.photos.set([{ path: '/a.jpg' }]);
        return Promise.resolve();
      });

      await component.ngOnInit();

      expect(mockStore.loadPhotos).toHaveBeenCalled();
      expect(mockStore.photos()).toHaveLength(1);
      expect(mockStore.initializing()).toBe(false);
    });

    describe('set scope carried from photo-detail navigation state', () => {
      afterEach(() => {
        history.replaceState({}, '', '/');
      });

      it('applies the scope before the first load, then clears it so a reload falls back to the plain gallery', async () => {
        history.replaceState({
          setScope: {
            sequence_group_id: '68', sequence_kind: 'bracket', burst_group_id: '', duplicate_group_id: '',
            hide_brackets: false,
          },
        }, '', '/');

        await component.ngOnInit();

        expect(mockStore.loadConfig).toHaveBeenCalled();
        expect(mockStore.filters()).toMatchObject({
          sequence_group_id: '68', sequence_kind: 'bracket', hide_brackets: false,
        });
        // Cleared immediately: browsers keep history.state for the current
        // entry across a reload, so leaving it would resolve a reload to a
        // possibly different (renumbered) set instead of the plain gallery.
        expect((history.state as Record<string, unknown> | null)?.['setScope']).toBeUndefined();
      });

      it('bypasses the restore-previous-view fast path even when the snapshot matches', async () => {
        // Same setup as 'restores the previous view when the URL matches the
        // snapshot' above, which normally skips loadConfig/loadPhotos entirely
        // -- a scoped "open this set" request must still get a fresh load.
        mockStore.photos.set([{ path: '/a.jpg' }]);
        mockStore.viewSnapshot.set({ scrollTop: 0, albumId: null, filterKey: mockStore.filterKey() });
        history.replaceState({
          setScope: {
            sequence_group_id: '5', sequence_kind: 'panorama', burst_group_id: '', duplicate_group_id: '',
            hide_panoramas: false,
          },
        }, '', '/');

        await component.ngOnInit();

        expect(mockStore.loadConfig).toHaveBeenCalled();
        expect(mockStore.loadPhotos).toHaveBeenCalled();
        expect(mockStore.filters()).toMatchObject({
          sequence_group_id: '5', sequence_kind: 'panorama', hide_panoramas: false,
        });
      });

      it('preserves unrelated history-state keys when clearing the consumed scope', async () => {
        history.replaceState({
          setScope: {
            sequence_group_id: '1', sequence_kind: '', burst_group_id: '1', duplicate_group_id: '',
            hide_bursts: false,
          },
          unrelated: 'keep-me',
        }, '', '/');

        await component.ngOnInit();

        const state = history.state as Record<string, unknown>;
        expect(state['unrelated']).toBe('keep-me');
        expect(state['setScope']).toBeUndefined();
      });

      it('does not touch filters when there is no set-scope state', async () => {
        history.replaceState({}, '', '/');
        const before = mockStore.filters();

        await component.ngOnInit();

        expect(mockStore.filters()).toBe(before);
      });
    });
  });

  describe('clearSetScope()', () => {
    afterEach(() => {
      localStorage.removeItem(DISPLAY_OPTIONS_KEY);
    });

    it('does nothing when no set scope is active', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS });

      component.clearSetScope();

      expect(mockStore.updateFilters).not.toHaveBeenCalled();
    });

    it('restores the user\'s stored hide_bursts preference instead of hardcoding true', () => {
      localStorage.setItem(DISPLAY_OPTIONS_KEY, JSON.stringify({ hide_bursts: false }));
      mockStore.filters.set({ ...DEFAULT_FILTERS, burst_group_id: '7', hide_bursts: false });

      component.clearSetScope();

      expect(mockStore.updateFilters).toHaveBeenCalledWith({
        sequence_group_id: '', sequence_kind: '', burst_group_id: '', duplicate_group_id: '',
        hide_bursts: false,
      });
    });

    it('falls back to the config default when nothing is stored in localStorage', () => {
      mockStore.config.set({ defaults: { hide_panoramas: false } });
      mockStore.filters.set({
        ...DEFAULT_FILTERS, sequence_kind: 'panorama', sequence_group_id: '3', hide_panoramas: false,
      });

      component.clearSetScope();

      expect(mockStore.updateFilters).toHaveBeenCalledWith({
        sequence_group_id: '', sequence_kind: '', burst_group_id: '', duplicate_group_id: '',
        hide_panoramas: false,
      });
    });

    it('falls back to true when neither storage nor config supplies a value', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, duplicate_group_id: '9', hide_duplicates: false });

      component.clearSetScope();

      expect(mockStore.updateFilters).toHaveBeenCalledWith({
        sequence_group_id: '', sequence_kind: '', burst_group_id: '', duplicate_group_id: '',
        hide_duplicates: true,
      });
    });
  });

  describe('hidden-photos banner toggle', () => {
    // showAllHidden()/restoreHidden() now live on GalleryStore (see
    // gallery.store.spec.ts) — the component only derives canRestoreHidden
    // from the store's hiddenFiltersStash + filters signals.
    it('offers the restore once a stash exists and every toggle is off', () => {
      mockStore.hiddenFiltersStash.set({
        hide_blinks: true, hide_bursts: false, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_blinks: false, hide_bursts: false, hide_duplicates: false, hide_brackets: false, hide_panoramas: false });
      expect(component.canRestoreHidden()).toBe(true);
    });

    it('offers no restore before Show all has been used', () => {
      expect(component.canRestoreHidden()).toBe(false);
    });

    it('withdraws the restore once a hide filter is switched back on by hand', () => {
      mockStore.hiddenFiltersStash.set({
        hide_blinks: true, hide_bursts: true, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_blinks: true, hide_bursts: false, hide_duplicates: false, hide_brackets: false, hide_panoramas: false });
      expect(component.canRestoreHidden()).toBe(false);
    });
  });

  describe('assistant-pinned list', () => {
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
    });

    it('keeps the pin when the gallery is restored from a /photo round trip', async () => {
      mockStore.pinnedPaths.set(['/a.jpg']);
      mockStore.photos.set([{ path: '/a.jpg' }]);
      mockStore.viewSnapshot.set({ scrollTop: 0, albumId: null, filterKey: mockStore.filterKey() });

      await component.ngOnInit();

      expect(mockStore.loadConfig).not.toHaveBeenCalled();
      expect(mockStore.loadPhotos).not.toHaveBeenCalled();
      expect(mockStore.pinnedPaths()).toEqual(['/a.jpg']);
    });

    it('reloads through loadConfig and loadPhotos (which drop the pin) when it cannot restore', async () => {
      mockStore.pinnedPaths.set(['/a.jpg']);

      await component.ngOnInit();

      expect(mockStore.loadConfig).toHaveBeenCalled();
      expect(mockStore.loadPhotos).toHaveBeenCalled();
    });

    it('renders the chip with the count and its button clears the pin', () => {
      mockStore.pinnedPaths.set(['/a.jpg', '/b.jpg']);
      mockStore.total.set(2);
      mockAuth['hasFeature'] = vi.fn(() => false);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const html = fixture.nativeElement as HTMLElement;
      expect(html.textContent).toContain(I18N.gallery.pinned.chip_plural);
      expect(html.querySelector('[role="status"]')).toBeTruthy();
      const clear = Array.from(html.querySelectorAll('button')).find(b => b.textContent?.includes(I18N.gallery.pinned.clear));
      expect(clear).toBeTruthy();
      clear?.click();
      expect(mockStore.clearPinned).toHaveBeenCalled();
    });

    function toolbarView(): HTMLElement {
      const tpl = (fixture!.componentInstance as unknown as { galleryToolbar(): TemplateRef<unknown> }).galleryToolbar();
      const view = tpl.createEmbeddedView({});
      view.detectChanges();
      const host = document.createElement('div');
      view.rootNodes.forEach((n: Node) => host.appendChild(n));
      return host;
    }
    const hasTypeAndSearch = (host: HTMLElement) =>
      host.textContent?.includes(I18N.ui.filters.type) === true
      && !!host.querySelector(`input[placeholder="${I18N.gallery.search_placeholder}"]`);

    it('offers no filter links while pinned (tag chips, person avatars, Find similar) and restores them after', () => {
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockStore.photos.set([{ path: '/a.jpg', filename: 'a.jpg', image_width: 4000, image_height: 3000 }]);
      mockStore.pinnedPaths.set(['/a.jpg']);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const cards = () => fixture!.debugElement.queryAll(By.directive(PhotoCardComponent));
      const menu = () => fixture!.debugElement.query(By.directive(GalleryPhotoMenuComponent)).componentInstance as GalleryPhotoMenuComponent;
      const tooltips = () => fixture!.debugElement.queryAll(By.directive(PhotoTooltipComponent));
      expect(cards().length).toBeGreaterThan(0);
      expect(cards().every(c => (c.componentInstance as PhotoCardComponent).filterLinks() === false)).toBe(true);
      expect(menu().findSimilar()).toBe(false);
      expect(tooltips().every(t => (t.componentInstance as PhotoTooltipComponent).personLinks() === false)).toBe(true);
      mockStore.pinnedPaths.set(null);
      fixture.detectChanges();
      expect(cards().every(c => (c.componentInstance as PhotoCardComponent).filterLinks() === true)).toBe(true);
      expect(menu().findSimilar()).toBe(true);
      expect(tooltips().every(t => (t.componentInstance as PhotoTooltipComponent).personLinks() === true)).toBe(true);
    });

    it('hides the header Type select and search field while pinned and restores them after', () => {
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockStore.pinnedPaths.set(['/a.jpg']);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      expect(hasTypeAndSearch(toolbarView())).toBe(false);
      mockStore.pinnedPaths.set(null);
      fixture.detectChanges();
      expect(hasTypeAndSearch(toolbarView())).toBe(true);
    });

    it('keeps the filter drawer shut while pinned without touching the persisted flag, and reopens it after', () => {
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockStore.filterDrawerOpen.set(true);
      mockStore.pinnedPaths.set(['/a.jpg']);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const drawer = fixture.debugElement.query(By.directive(MatSidenav)).componentInstance as MatSidenav;
      expect(drawer.opened).toBe(false);
      expect(mockStore.setFilterDrawerOpen).not.toHaveBeenCalled();
      expect(mockStore.filterDrawerOpen()).toBe(true);
      mockStore.pinnedPaths.set(null);
      fixture.detectChanges();
      expect(drawer.opened).toBe(true);
      mockStore.filterDrawerOpen.set(false);
    });

    it('the load-error Retry button reloads without dropping the pin', () => {
      mockStore.pinnedPaths.set(['/a.jpg']);
      mockStore.loadError.set(true);
      mockAuth['hasFeature'] = vi.fn(() => false);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const retry = Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('button'))
        .find(b => b.textContent?.includes(I18N.gallery.load_error.retry));
      expect(retry).toBeTruthy();
      retry?.click();
      expect(mockStore.reloadPhotos).toHaveBeenCalled();
      mockStore.loadError.set(false);
    });

    it('hides the Keep top N% button while a pinned list is shown', () => {
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockStore.total.set(2);
      mockStore.canScopeSelectionToView.set(false);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      expect((fixture.nativeElement as HTMLElement).querySelector(`[aria-label="${I18N.gallery.keep_top.label}"]`)).toBeNull();
      mockStore.canScopeSelectionToView.set(true);
    });

    it('renders the review legend in the chip only when the pin has marks', () => {
      mockStore.pinnedPaths.set(['/a.jpg', '/b.jpg']);
      mockStore.total.set(2);
      mockAuth['hasFeature'] = vi.fn(() => false);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const html = fixture.nativeElement as HTMLElement;
      expect(html.querySelector('[data-testid="pinned-review-legend"]')).toBeNull();
      mockStore.hasReview.set(true);
      mockStore.reviewLegend.set({ groups: 2, keep: 3, remove: 4 });
      fixture.detectChanges();
      const legend = html.querySelector('[data-testid="pinned-review-legend"]');
      expect(legend).toBeTruthy();
      expect(html.querySelector('[role="status"]')?.contains(legend)).toBe(true);
    });

    it('uses the singular chip text for one photo', () => {
      mockStore.pinnedPaths.set(['/a.jpg']);
      mockStore.total.set(1);
      mockAuth['hasFeature'] = vi.fn(() => false);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      const text = (fixture.nativeElement as HTMLElement).textContent ?? '';
      expect(text).toContain(I18N.gallery.pinned.chip);
      expect(text).not.toContain(I18N.gallery.pinned.chip_plural);
    });

    it('renders no chip without a pin', () => {
      mockAuth['hasFeature'] = vi.fn(() => false);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      expect((fixture.nativeElement as HTMLElement).textContent).not.toContain(I18N.gallery.pinned.chip);
    });
  });

  describe('collapsedSetKinds', () => {
    it('lists nothing when every hide toggle is off', () => {
      mockStore.filters.set({
        ...DEFAULT_FILTERS, hide_bursts: false, hide_duplicates: false, hide_brackets: false, hide_panoramas: false,
      });
      expect(component.collapsedSetKinds()).toEqual([]);
    });

    it('lists a kind per toggle that is on', () => {
      mockStore.filters.set({
        ...DEFAULT_FILTERS, hide_bursts: true, hide_duplicates: true, hide_brackets: true, hide_panoramas: true,
      });
      expect(component.collapsedSetKinds()).toEqual(['burst', 'duplicate', 'bracket', 'panorama', 'hdr_panorama']);
    });
  });

  describe('thumbnail-migration banner', () => {
    const RENDER_MIGRATION_KEY = 'facet_render_migration_dismissed';

    function rebuild(): GalleryComponent {
      return TestBed.runInInjectionContext(() => new GalleryComponent());
    }

    beforeEach(() => {
      localStorage.removeItem(RENDER_MIGRATION_KEY);
      component = rebuild();
    });

    afterEach(() => localStorage.removeItem(RENDER_MIGRATION_KEY));

    it('stays hidden until the server reports rows awaiting regeneration', () => {
      mockStore.config.set({ render_migration: { pending: 0 } });
      expect(component.showRenderMigrationBanner()).toBe(false);
    });

    it('stays hidden on a build whose config carries no migration block', () => {
      mockStore.config.set({ features: {} });
      expect(component.renderMigrationPending()).toBe(0);
      expect(component.showRenderMigrationBanner()).toBe(false);
    });

    it('shows the pending count once the server reports one', () => {
      mockStore.config.set({ render_migration: { pending: 1234 } });
      expect(component.renderMigrationPending()).toBe(1234);
      expect(component.showRenderMigrationBanner()).toBe(true);
    });

    it('hides on dismiss and stays hidden for the next visit', () => {
      mockStore.config.set({ render_migration: { pending: 12 } });
      component.dismissRenderMigration();

      expect(component.showRenderMigrationBanner()).toBe(false);
      expect(localStorage.getItem(RENDER_MIGRATION_KEY)).toBe('true');

      // A migration takes hours, so a reload must not raise the notice again.
      const reloaded = rebuild();
      expect(reloaded.showRenderMigrationBanner()).toBe(false);
    });
  });

  describe('docked details panel (tooltip_mode = panel)', () => {
    const hoverEvent = { currentTarget: null } as unknown as MouseEvent;

    /** Force the rail's width gate on, the way a >=1280px viewport would. */
    function widenForRail() {
      vi.stubGlobal('matchMedia', (media: string) => ({
        matches: true, media, addEventListener() {}, removeEventListener() {},
      }));
      (component as unknown as { railWide: { setup(): void } }).railWide.setup();
    }

    beforeEach(() => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'panel' });
    });

    afterEach(() => vi.unstubAllGlobals());

    it('needs a wide viewport as well as the setting, not the setting alone', () => {
      expect(component['tooltipMode']()).toBe('panel');
      expect(component.panelMode()).toBe(false);
    });

    describe('with a viewport wide enough for the rail', () => {
      beforeEach(() => widenForRail());

      it('is active', () => {
        expect(component.panelMode()).toBe(true);
      });

      it('hovering a photo feeds the rail without any placement maths', () => {
        const photo = { path: '/a.jpg' } as never;
        component.showTooltip(hoverEvent, photo);
        expect(component['tooltipPhoto']()).toBe(photo);
        expect(component['tooltipX']()).toBe(0);
        expect(component['tooltipY']()).toBe(0);
      });

      it('keeps the last photo when the cursor leaves the grid', () => {
        const photo = { path: '/a.jpg' } as never;
        component.showTooltip(hoverEvent, photo);
        component.hideTooltip();
        expect(component['tooltipPhoto']()).toBe(photo);
      });

      describe('while a photo is current', () => {
        const a = { path: '/a.jpg' };
        const b = { path: '/b.jpg' };
        const panelPhoto = () => (component as unknown as { panelPhoto(): unknown }).panelPhoto();
        const release = () => (component as unknown as { releasePanel(): void }).releasePanel();

        beforeEach(() => {
          mockStore.photos.set([a, b]);
          click(a, 0);
          component.showTooltip(hoverEvent, a as never);
        });

        it('hovering another photo does not retarget the rail', () => {
          component.showTooltip(hoverEvent, b as never);
          expect(panelPhoto()).toBe(a);
        });

        it('Deselect drops the cursor and the selection, keeps the photo until the next hover', () => {
          mockStore.selectedPaths.set(new Set([a.path]));
          component.showTooltip(hoverEvent, b as never);
          release();
          expect(hasActivePhoto()).toBe(false);
          expect(mockStore.toggleSelection).toHaveBeenLastCalledWith(a);
          expect(panelPhoto()).toBe(a);
          component.showTooltip(hoverEvent, b as never);
          expect(panelPhoto()).toBe(b);
        });

        it('a new pin empties the rail and drops the cursor, so nothing of the previous view carries over', () => {
          TestBed.tick();
          component.showTooltip(hoverEvent, a as never);
          expect(panelPhoto()).toBe(a);
          mockStore.pinnedPaths.set(['/a.jpg']);
          TestBed.tick();
          expect(panelPhoto()).toBeFalsy();
          expect(hasActivePhoto()).toBe(false);
          expect(component['tooltipPhoto']()).toBeNull();
        });

        it('a plain filter reload with no pin leaves the held photo alone', () => {
          TestBed.tick();
          component.showTooltip(hoverEvent, a as never);
          mockStore.pinnedPaths.set(null);
          TestBed.tick();
          expect(component['tooltipPhoto']()).toBe(a);
          expect(hasActivePhoto()).toBe(true);
        });

        it('Deselect leaves an already-unselected photo unselected', () => {
          mockStore.toggleSelection.mockClear();
          release();
          expect(mockStore.toggleSelection).not.toHaveBeenCalled();
        });

        it('Escape in the grid releases the photo like Deselect, then clears the rest of the selection', () => {
          mockStore.selectedPaths.set(new Set([a.path, b.path]));
          mockStore.selectionCount.set(2);
          component.showTooltip(hoverEvent, b as never);
          press('Escape');
          expect(hasActivePhoto()).toBe(false);
          expect(mockStore.toggleSelection).toHaveBeenLastCalledWith(a);
          expect(mockStore.clearSelection).toHaveBeenCalled();
          expect(panelPhoto()).toBe(a);
        });

        it('Escape in the grid releases a photo the cursor holds without any selection', () => {
          mockStore.toggleSelection.mockClear();
          press('Escape');
          expect(hasActivePhoto()).toBe(false);
          expect(mockStore.toggleSelection).not.toHaveBeenCalled();
          expect(mockStore.clearSelection).not.toHaveBeenCalled();
        });

        it('Escape with one photo in a view-scoped selection still clears the store selection', () => {
          mockStore.photos.set([a]);
          mockStore.viewScopeSelected.set(true);
          // The store's count is "loaded photos minus exclusions"; the release excludes the only one.
          mockStore.selectionCount.set(0);
          mockStore.clearSelection.mockClear();
          press('Escape');
          expect(mockStore.clearSelection).toHaveBeenCalled();
          mockStore.viewScopeSelected.set(false);
          mockStore.selectionCount.set(0);
        });

        it('focus moving into the rail keeps the cursor', () => {
          const rail = document.createElement('div');
          rail.setAttribute('data-details-rail', '');
          const button = document.createElement('button');
          rail.appendChild(button);
          document.body.appendChild(rail);
          (component as unknown as { onGridFocusOut(e: FocusEvent): void })
            .onGridFocusOut({ relatedTarget: button } as unknown as FocusEvent);
          expect(activeIndex()).toBe(0);
          rail.remove();
        });
      });

      describe('after Escape released a held card that still has focus', () => {
        const four = [{ path: '/a.jpg' }, { path: '/b.jpg' }, { path: '/c.jpg' }, { path: '/d.jpg' }];
        let card: HTMLElement;
        let inner: HTMLElement;
        const fire = (key: string, target: HTMLElement) => {
          const ev = new KeyboardEvent('keydown', { key, cancelable: true });
          Object.defineProperty(ev, 'target', { value: target, configurable: true });
          (component as unknown as { onGridKeydown(e: KeyboardEvent): void }).onGridKeydown(ev);
        };

        beforeEach(() => {
          mockStore.photos.set(four);
          mockStore.config.set({ features: { show_rating_controls: true } });
          (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
          card = document.createElement('div');
          card.setAttribute('data-pidx', '2');
          inner = document.createElement('span');
          card.appendChild(inner);
          click(four[2], 2);
          fire('Escape', inner);
          expect(activeIndex()).toBe(-1);
        });

        it('a rating key rates the card that has focus, not photo 0', () => {
          fire('5', inner);
          expect(mockStore.setRating).toHaveBeenCalledWith('/c.jpg', 5);
          expect(mockStore.setRating).not.toHaveBeenCalledWith('/a.jpg', 5);
        });

        it('ArrowRight moves on from the card that has focus', () => {
          fire('ArrowRight', inner);
          expect(activeIndex()).toBe(3);
        });
      });

      it('Escape in Hover mode never touches the panel hold: it only clears the selection', () => {
        mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
        mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }]);
        click({ path: '/b.jpg' }, 1);
        mockStore.selectionCount.set(1);
        mockStore.toggleSelection.mockClear();
        mockStore.clearSelection.mockClear();
        press('Escape');
        expect(mockStore.clearSelection).toHaveBeenCalled();
        expect(mockStore.toggleSelection).not.toHaveBeenCalled();
        expect(activeIndex()).toBe(1);
        mockStore.selectionCount.set(0);
      });

      it('disableClose follows the rail: false while the filters occupy the drawer', () => {
        const fixture = TestBed.createComponent(GalleryComponent);
        (fixture.componentInstance as unknown as { railWide: { setup(): void } }).railWide.setup();
        fixture.detectChanges();
        const drawer = fixture.debugElement.query(By.directive(MatSidenav)).componentInstance as MatSidenav;
        expect(fixture.componentInstance.detailsRailVisible()).toBe(true);
        expect(drawer.disableClose).toBe(true);
        mockStore.filterDrawerOpen.set(true);
        fixture.detectChanges();
        expect(fixture.componentInstance.detailsRailVisible()).toBe(false);
        expect(drawer.disableClose).toBe(false);
        fixture.destroy();
      });

      describe('rail rendered with a held photo', () => {
        interface RailInstance {
          railWide: { setup(): void };
          hasActivePhoto(): boolean;
          setCursor(index: number): void;
        }
        let fixture: ComponentFixture<GalleryComponent>;
        let instance: RailInstance;
        let rail: HTMLElement;

        beforeEach(() => {
          const a = {
            path: '/a.jpg', filename: 'a.jpg', image_width: 4000, image_height: 3000, tags_list: [], persons: [],
          };
          mockStore.photos.set([a]);
          // The docked tooltip fetches its own extras (histogram, captions) once it renders.
          Object.assign(mockApi, { get: vi.fn(() => of({})) });
          fixture = TestBed.createComponent(GalleryComponent);
          instance = fixture.componentInstance as unknown as RailInstance;
          instance.railWide.setup();
          fixture.detectChanges();
          instance.setCursor(0);
          fixture.detectChanges();
          expect(instance.hasActivePhoto()).toBe(true);
          rail = fixture.nativeElement.querySelector('[data-details-rail]') as HTMLElement;
        });

        afterEach(() => fixture.destroy());

        const escape = (target: HTMLElement) => target.dispatchEvent(new KeyboardEvent('keydown', {
          key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true, cancelable: true,
        }));

        it('Escape releases the photo and the drawer is not closed (rendered)', () => {
          // MatDrawer closes itself on an Escape from inside it unless disableClose is set;
          // the open/close effect would then reopen it, so the rail would flicker.
          const drawer = fixture.debugElement.query(By.directive(MatSidenav)).componentInstance as MatSidenav;
          const close = vi.spyOn(drawer, 'close');
          escape(rail);
          fixture.detectChanges();
          expect(instance.hasActivePhoto()).toBe(false);
          expect(close).not.toHaveBeenCalled();
        });

        it('focus leaving the rail for the outside releases the hold', () => {
          const outside = document.createElement('button');
          document.body.appendChild(outside);
          rail.dispatchEvent(new FocusEvent('focusout', { relatedTarget: outside, bubbles: true }));
          expect(instance.hasActivePhoto()).toBe(false);
          outside.remove();
        });

        it('focus moving within the rail keeps the hold', () => {
          const inside = rail.querySelector('button') as HTMLElement;
          rail.dispatchEvent(new FocusEvent('focusout', { relatedTarget: inside, bubbles: true }));
          expect(instance.hasActivePhoto()).toBe(true);
        });

        it('Escape on the focused Deselect button leaves focus on the rail', () => {
          document.body.appendChild(fixture.nativeElement);
          const button = rail.querySelector('button') as HTMLElement;
          button.focus();
          escape(button);
          fixture.detectChanges();
          expect(document.activeElement).toBe(rail);
        });
      });

      it('yields the shared drawer to the filters while they are open', () => {
        mockStore.filterDrawerOpen.set(true);
        expect(component.detailsRailVisible()).toBe(false);
      });
    });

    it('still clears on mouse-out in hover mode', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      component.hideTooltip();
      expect(component['tooltipPhoto']()).toBeNull();
    });

    it('falls back to a positioned floating tooltip when the rail cannot be shown', () => {
      // Selecting the mode on a viewport too narrow for the rail used to skip
      // the placement maths and leave the floating box at a stale coordinate.
      const card = document.createElement('div');
      card.className = 'relative rounded-lg';
      document.body.appendChild(card);
      const photo = { path: '/a.jpg', image_width: 4000, image_height: 3000 } as never;
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);
      expect(component['tooltipPhoto']()).toBe(photo);
      card.remove();
    });

    it('clears on mouse-out while the rail is unavailable, like hover does', () => {
      const photo = { path: '/a.jpg' } as never;
      component['tooltipPhoto'].set(photo);
      component.hideTooltip();
      expect(component['tooltipPhoto']()).toBeNull();
    });
  });

  describe('tooltip mode switch clears a stale tooltipPhoto', () => {
    function makeCard(): HTMLElement {
      const card = document.createElement('div');
      card.className = 'relative rounded-lg';
      document.body.appendChild(card);
      return card;
    }
    const photo = { path: '/a.jpg', image_width: 4000, image_height: 3000 } as never;

    it('a hover-shown tooltip does not survive a switch to click mode', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      TestBed.flushEffects();
      const card = makeCard();
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);
      expect(component['tooltipPhoto']()).toBe(photo);

      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'click' });
      TestBed.flushEffects();

      expect(component['tooltipPhoto']()).toBeNull();
      card.remove();
    });

    it('the first click in the new mode shows the tooltip rather than hiding it', () => {
      // A test asserting only "clicking twice toggles" would pass even if a
      // stale hover-set tooltipPhoto made this very first click hide instead
      // of show -- assert the show explicitly.
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      TestBed.flushEffects();
      const card = makeCard();
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);

      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'click' });
      TestBed.flushEffects();
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);

      expect(component['tooltipPhoto']()).toBe(photo);
      card.remove();
    });

    it('a click-pinned tooltip does not survive a switch to hover mode', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'click' });
      TestBed.flushEffects();
      const card = makeCard();
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);
      expect(component['tooltipPhoto']()).toBe(photo);

      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      TestBed.flushEffects();

      expect(component['tooltipPhoto']()).toBeNull();
      card.remove();
    });

    it('a tooltip does not survive a switch to off mode', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      TestBed.flushEffects();
      const card = makeCard();
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);

      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'off' });
      TestBed.flushEffects();

      expect(component['tooltipPhoto']()).toBeNull();
      card.remove();
    });

    it('switching into panel mode does not carry over a stale hover tooltip', () => {
      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'hover' });
      TestBed.flushEffects();
      const card = makeCard();
      component.showTooltip({ currentTarget: card } as unknown as MouseEvent, photo);

      mockStore.filters.set({ ...DEFAULT_FILTERS, tooltip_mode: 'panel' });
      TestBed.flushEffects();

      expect(component['tooltipPhoto']()).toBeNull();
      card.remove();
    });
  });

  describe('compare selection', () => {
    const photo = (path: string) => ({ path, filename: path.slice(1) });

    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    // The dialog itself is covered by its own spec; this is the wiring — which
    // photos it is handed, in which order, and when the action is offered.
    it('is offered from two photos up to the pane limit', () => {
      const c = component as unknown as { canCompareSelection: () => boolean };
      for (const n of [0, 1]) {
        select(Array.from({ length: n }, (_, i) => `/p${i}.jpg`));
        expect(c.canCompareSelection()).toBe(false);
      }
      for (let n = 2; n <= MAX_COMPARE_PANES; n++) {
        select(Array.from({ length: n }, (_, i) => `/p${i}.jpg`));
        expect(c.canCompareSelection()).toBe(true);
      }
      select(Array.from({ length: MAX_COMPARE_PANES + 1 }, (_, i) => `/p${i}.jpg`));
      expect(c.canCompareSelection()).toBe(false);
    });

    it('hands over the grid order, not the order they were picked in', async () => {
      mockStore.photos.set(['/a.jpg', '/b.jpg', '/c.jpg'].map(photo));
      select(['/c.jpg', '/a.jpg']);
      const dialog = TestBed.inject(MatDialog);

      await (component as unknown as { compareSelection: () => Promise<void> }).compareSelection();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.photos.map((p: { path: string }) => p.path)).toEqual(['/a.jpg', '/c.jpg']);
    });

    it('caps the panes even if more photos are somehow selected', async () => {
      const paths = Array.from({ length: MAX_COMPARE_PANES + 2 }, (_, i) => `/p${i}.jpg`);
      mockStore.photos.set(paths.map(photo));
      select(paths);
      const dialog = TestBed.inject(MatDialog);

      await (component as unknown as { compareSelection: () => Promise<void> }).compareSelection();

      expect((dialog.open as Mock).mock.calls[0][1].data.photos.length).toBe(MAX_COMPARE_PANES);
    });

    it('does nothing when fewer than two selected photos are loaded', async () => {
      mockStore.photos.set([photo('/a.jpg')]);
      select(['/a.jpg', '/gone.jpg']);
      const dialog = TestBed.inject(MatDialog);

      await (component as unknown as { compareSelection: () => Promise<void> }).compareSelection();

      expect(dialog.open).not.toHaveBeenCalled();
    });
  });

  describe('openCullDialog', () => {
    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    // The dialog itself is covered by its own spec; this is the wiring — which
    // capability flags reach it, and that both read fail-closed off the config.
    it('passes trashAvailable and allowTrash through when both are enabled', async () => {
      mockStore.config.set({ cull: { allow_trash: true, trash_available: true } });
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.openCullDialog();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.trashAvailable).toBe(true);
      expect(data.allowTrash).toBe(true);
    });

    it('passes allowTrash true but trashAvailable false when the package is missing', async () => {
      mockStore.config.set({ cull: { allow_trash: true, trash_available: false } });
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.openCullDialog();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.trashAvailable).toBe(false);
      expect(data.allowTrash).toBe(true);
    });

    it('fails closed to both false when the config has no cull key at all', async () => {
      mockStore.config.set({});
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.openCullDialog();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.trashAvailable).toBe(false);
      expect(data.allowTrash).toBe(false);
    });

    it('reloads the list before clearing the selection', async () => {
      // Clearing hands focus back to the marked card, and until the reload
      // returns the rows the cull has just moved away are still in the list --
      // so the focus would be aimed at a photo that no longer exists.
      mockStore.config.set({});
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });
      const order: string[] = [];
      mockStore.reloadPhotos.mockImplementation(() => {
        order.push('load');
        return Promise.resolve();
      });
      mockStore.clearSelection.mockImplementation(() => order.push('clear'));

      await component.openCullDialog();

      expect(order).toEqual(['load', 'clear']);
    });

    // The guard reads `if (!viewScoped && !paths.length) return;` -- widened
    // specifically so a whole-view cull (selectedPaths empty by design) is not
    // silently dropped the way `if (!paths.length) return;` would drop it.
    it('still opens under view scope even though selectedPaths is empty', async () => {
      mockStore.config.set({ cull: { allow_trash: true, trash_available: true } });
      mockStore.selectionScope.set('view');
      mockStore.viewScopeSelected.set(true);
      mockStore.excludedPaths.set(new Set(['/skip.jpg']));
      mockStore.selectionCount.set(650);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.openCullDialog();

      expect(dialog.open).toHaveBeenCalled();
      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.filters).toEqual({ page: '1' });
      expect(data.exclude).toEqual(['/skip.jpg']);
      expect(data.count).toBe(650);
    });
  });

  describe('openManualTagsDialog', () => {
    const open = () => (component as unknown as { openManualTagsDialog(): Promise<void> }).openManualTagsDialog();
    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    // The dialog owns its request (its own spec); this is the wiring.
    it('opens the manual-tags dialog with the selected paths', async () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(undefined) });

      await open();

      expect(dialog.open).toHaveBeenCalledTimes(1);
      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.paths).toEqual(['/a.jpg', '/b.jpg']);
      expect(data.filters).toBeNull();
      expect(data.count).toBe(2);
    });

    it('sends the filter and exclusions under view scope', async () => {
      mockStore.viewScopeSelected.set(true);
      mockStore.excludedPaths.set(new Set(['/skip.jpg']));
      mockStore.selectionCount.set(650);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(undefined) });

      await open();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.filters).toEqual({ page: '1' });
      expect(data.exclude).toEqual(['/skip.jpg']);
      expect(data.count).toBe(650);
    });

    it('does nothing for an empty path selection', async () => {
      select([]);
      const dialog = TestBed.inject(MatDialog);

      await open();

      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('refetches the list after a write, so the detail view gets fresh manual tags', async () => {
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(1) });

      await open();

      expect(mockStore.reloadPhotos).toHaveBeenCalledTimes(1);
      expect(mockStore.restoreSelection).toHaveBeenCalledWith(['/a.jpg']);
    });

    it('leaves the list alone when the dialog is cancelled', async () => {
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(undefined) });

      await open();

      expect(mockStore.loadPhotos).not.toHaveBeenCalled();
    });
  });

  describe('selection bar edit-tags button (rendered)', () => {
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
    });

    function render(edition: boolean): ComponentFixture<GalleryComponent> {
      mockAuth['isEdition'] = vi.fn(() => edition);
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockAuth['isMultiUser'] = vi.fn(() => false);
      mockAuth['isSuperadmin'] = vi.fn(() => false);
      mockAuth['downloadProfiles'] = vi.fn(() => []);
      mockStore.config.set({});
      mockStore.selectionCount.set(2);
      mockStore.viewScopeSelected.set(false);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      return fixture;
    }

    function tagsButton(f: ComponentFixture<GalleryComponent>): HTMLButtonElement | null {
      return (Array.from(f.nativeElement.querySelectorAll('button')) as HTMLButtonElement[])
        .find(b => b.textContent?.includes(I18N.gallery.selection.edit_tags)) ?? null;
    }

    it('is a desktop-only button for an edition user', () => {
      const button = tagsButton(render(true));

      expect(button).not.toBeNull();
      expect(button!.className).toContain('!hidden');
      expect(button!.className).toContain('lg:!inline-flex');
    });

    it('is absent without edition', () => {
      expect(tagsButton(render(false))).toBeNull();
    });

    it('opens the dialog when clicked', () => {
      const f = render(true);
      const open = vi.spyOn(f.componentInstance as unknown as { openManualTagsDialog(): Promise<void> }, 'openManualTagsDialog')
        .mockResolvedValue(undefined);

      tagsButton(f)!.click();

      expect(open).toHaveBeenCalledTimes(1);
    });
  });

  describe('deleteSelected', () => {
    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    function deleteResponse(overrides: Partial<{
      deleted: string[]; refused_bracket_lead: string[]; not_found: string[];
      not_visible: string[]; sequence_siblings: string[]; skipped: string[];
      errors: Record<string, string>; trashed: number;
    }> = {}) {
      return of({
        dry_run: false,
        deleted: [],
        not_found: [],
        not_visible: [],
        refused_bracket_lead: [],
        sequence_siblings: [],
        skipped: [],
        trashed: 0,
        errors: {},
        ...overrides,
      });
    }

    // decision 8 / B5: `paths` cannot express a view-scoped selection, so the
    // toolbar button is disabled under it -- this is the belt-and-braces guard
    // behind that, proven directly rather than only via the disabled attribute.
    it('does nothing under view scope, even if somehow invoked', async () => {
      mockStore.viewScopeSelected.set(true);
      const dialog = TestBed.inject(MatDialog);

      await component.deleteSelected();

      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('does nothing with an empty selection', async () => {
      select([]);
      const dialog = TestBed.inject(MatDialog);

      await component.deleteSelected();

      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('opens the dialog with paths only (never filters/exclude) and hasCompanion always offered', async () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.deleteSelected();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data.surface).toBe('bulk');
      expect(data.paths).toEqual(['/a.jpg', '/b.jpg']);
      expect(data.filters).toBeUndefined();
      expect(data.exclude).toBeUndefined();
      expect(data.hasCompanion).toBe(true);
      expect(data.hasBracketLead).toBe(false);
    });

    it('passes hasSiblings true when a selected, loaded photo carries a sequence_kind', async () => {
      mockStore.photos.set([
        { path: '/a.jpg', sequence_kind: 'bracket' },
        { path: '/b.jpg', sequence_kind: null },
      ]);
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.deleteSelected();

      expect((dialog.open as Mock).mock.calls[0][1].data.hasSiblings).toBe(true);
    });

    it('passes hasSiblings false when no selected photo carries a bracket/panorama/hdr_panorama sequence_kind', async () => {
      mockStore.photos.set([{ path: '/a.jpg', sequence_kind: null }]);
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.deleteSelected();

      expect((dialog.open as Mock).mock.calls[0][1].data.hasSiblings).toBe(false);
    });

    it('cancelling the dialog makes no request', async () => {
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

      await component.deleteSelected();

      expect(mockApi.post).not.toHaveBeenCalledWith('/photo/delete', expect.anything());
      expect(mockStore.removePhotos).not.toHaveBeenCalled();
    });

    it('on confirm: posts dry_run=false, removes only the DELETED paths (not a refused one), clears the selection, and never refetches', async () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({
        afterClosed: () => of({ includeCompanions: false, includeSequenceSiblings: false }),
      });
      mockApi.post.mockReturnValueOnce(
        deleteResponse({ deleted: ['/a.jpg'], refused_bracket_lead: ['/b.jpg'], trashed: 1 }),
      );

      await component.deleteSelected();

      expect(mockApi.post).toHaveBeenCalledWith('/photo/delete', {
        paths: ['/a.jpg', '/b.jpg'],
        include_companions: false,
        include_sequence_siblings: false,
        dry_run: false,
      });
      // Restricted to what the response actually reports deleted -- a refused
      // bracket lead's row still exists server-side and must stay in the grid.
      expect(mockStore.removePhotos).toHaveBeenCalledWith(['/a.jpg']);
      expect(mockStore.clearSelection).toHaveBeenCalled();
      // Step 11 deliberately departs from cull's `loadPhotos()` reload pattern
      // for delete specifically -- guards against silently reverting to it.
      expect(mockStore.loadPhotos).not.toHaveBeenCalled();
    });

    it('reports a partial result snackbar with the deleted and failed counts', async () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({
        afterClosed: () => of({ includeCompanions: false, includeSequenceSiblings: false }),
      });
      mockApi.post.mockReturnValueOnce(
        deleteResponse({ deleted: ['/a.jpg'], refused_bracket_lead: ['/b.jpg'], trashed: 1 }),
      );
      const snackBar = TestBed.inject(MatSnackBar);

      await component.deleteSelected();

      expect(snackBar.open).toHaveBeenCalledWith(
        mockI18n.t(I18N.cull.delete_partial_result, { deleted: 1, failed: 1 }),
        '', { duration: 4000 },
      );
    });

    // Finding 5: a bulk delete where every send2trash failed must not render
    // as a neutral "0 deleted, 0 refused" result -- `errors` (an unwritable
    // trash dir), `not_found`, `not_visible` and `skipped` all count as
    // failures even though none of them is `refused_bracket_lead`, the only
    // bucket the toast used to read.
    it('reports the dedicated delete_failed snackbar when every path lands in errors and none is deleted', async () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({
        afterClosed: () => of({ includeCompanions: false, includeSequenceSiblings: false }),
      });
      mockApi.post.mockReturnValueOnce(
        deleteResponse({ errors: { '/a.jpg': 'Permission denied', '/b.jpg': 'Permission denied' } }),
      );
      const snackBar = TestBed.inject(MatSnackBar);

      await component.deleteSelected();

      expect(snackBar.open).toHaveBeenCalledWith(
        mockI18n.t(I18N.cull.delete_failed), '', { duration: 4000 },
      );
    });

    it('folds not_found, not_visible and skipped into the partial-result failed count, not just refused_bracket_lead', async () => {
      select(['/a.jpg', '/b.jpg', '/c.jpg', '/d.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({
        afterClosed: () => of({ includeCompanions: false, includeSequenceSiblings: false }),
      });
      mockApi.post.mockReturnValueOnce(
        deleteResponse({
          deleted: ['/a.jpg'], not_found: ['/b.jpg'], not_visible: ['/c.jpg'], skipped: ['/d.jpg'], trashed: 1,
        }),
      );
      await component.deleteSelected();

      // Asserted on the i18n mock's own call args, not on the snackbar's
      // resolved text: `mockI18n.t` ignores its `vars` argument and echoes
      // the key back, so `snackBar.open`'s first argument is identical
      // ("cull.delete_partial_result") whether `failed` is computed from all
      // four buckets or from `refused_bracket_lead` alone -- asserting on
      // that resolved string would pass under either implementation.
      expect(mockI18n.t).toHaveBeenCalledWith(I18N.cull.delete_partial_result, { deleted: 1, failed: 3 });
    });

    it('a failed request does not touch the store', async () => {
      select(['/a.jpg']);
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({
        afterClosed: () => of({ includeCompanions: false, includeSequenceSiblings: false }),
      });
      mockApi.post.mockReturnValueOnce(throwError(() => new Error('boom')));

      await component.deleteSelected();

      expect(mockStore.removePhotos).not.toHaveBeenCalled();
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
    });
  });

  // The desktop toolbar button and its gating -- the two properties the
  // adversarial review singled out (G13, B5): gated on `trash_available`
  // (never the raw `allow_trash`), and disabled (not hidden) under a
  // view-scoped selection because `paths` cannot express one.
  describe('bulk delete toolbar button (rendered)', () => {
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
    });

    function render(trashAvailable: boolean, viewScoped: boolean, allowTrash: boolean = trashAvailable): ComponentFixture<GalleryComponent> {
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockAuth['isMultiUser'] = vi.fn(() => false);
      mockAuth['isSuperadmin'] = vi.fn(() => false);
      mockAuth['downloadProfiles'] = vi.fn(() => []);
      mockStore.config.set({ cull: { allow_trash: allowTrash, trash_available: trashAvailable } });
      mockStore.selectionCount.set(2);
      mockStore.viewScopeSelected.set(viewScoped);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      return fixture;
    }

    function deleteButton(f: ComponentFixture<GalleryComponent>): HTMLButtonElement | null {
      return (Array.from(f.nativeElement.querySelectorAll('button')) as HTMLButtonElement[])
        .find(b => b.textContent?.includes('cull.delete_action')) ?? null;
    }

    it('is absent when trash_available is false, even with allow_trash true', () => {
      const f = render(false, false, true);
      expect(deleteButton(f)).toBeNull();
    });

    it('is present and enabled when trash_available is true and the selection is an explicit path list', () => {
      const f = render(true, false);
      const button = deleteButton(f);
      expect(button).not.toBeNull();
      expect(button!.disabled).toBe(false);
    });

    it('is disabled under a view-scoped ("select all in view") selection, with a tooltip explaining why', () => {
      const f = render(true, true);
      const button = deleteButton(f);
      expect(button).not.toBeNull();
      expect(button!.disabled).toBe(true);
      const tooltipDebug = f.debugElement.queryAll(By.directive(MatTooltip))
        .find(de => de.nativeElement === button);
      expect(tooltipDebug?.injector.get(MatTooltip).message).toBe(I18N.cull.delete_disabled_view_scope_tooltip);
    });
  });

  describe('openActionsSheet -> delete dispatch (mobile)', () => {
    beforeEach(() => {
      mockAuth['downloadProfiles'] = vi.fn(() => []);
    });

    it('passes trashAvailable through to the sheet data', async () => {
      mockStore.config.set({ cull: { allow_trash: true, trash_available: true } });
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      const bottomSheet = TestBed.inject(MatBottomSheet);
      (bottomSheet.open as Mock).mockReturnValue({ afterDismissed: () => of(null) });

      await (component as unknown as { openActionsSheet(): Promise<void> }).openActionsSheet();

      const data = (bottomSheet.open as Mock).mock.calls[0][1].data;
      expect(data.trashAvailable).toBe(true);
    });

    it('dispatches to deleteSelected() when the sheet resolves { kind: "delete" }', async () => {
      mockStore.config.set({ cull: { allow_trash: true, trash_available: true } });
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      const bottomSheet = TestBed.inject(MatBottomSheet);
      (bottomSheet.open as Mock).mockReturnValue({ afterDismissed: () => of({ kind: 'delete' }) });
      const spy = vi.spyOn(component, 'deleteSelected').mockResolvedValue();

      await (component as unknown as { openActionsSheet(): Promise<void> }).openActionsSheet();

      expect(spy).toHaveBeenCalled();
    });
  });

  describe('openExportDialog', () => {
    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    it('opens the album-scoped dialog when the route carries an albumId, ignoring selection scope', () => {
      routeMock.snapshot.paramMap.get = vi.fn(() => '42');
      const dialog = TestBed.inject(MatDialog);

      component.openExportDialog();

      expect((dialog.open as Mock).mock.calls[0][1].data).toEqual({ albumId: 42 });
    });

    it('sends the filter payload, exclude list and count under view scope, with no paths key', () => {
      mockStore.selectionScope.set('view');
      mockStore.viewScopeSelected.set(true);
      mockStore.excludedPaths.set(new Set(['/skip.jpg']));
      mockStore.selectionCount.set(650);
      const dialog = TestBed.inject(MatDialog);

      component.openExportDialog();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data).toEqual({ filters: { page: '1' }, exclude: ['/skip.jpg'], count: 650 });
      expect(data.paths).toBeUndefined();
    });

    it('sends the selected paths under path scope, with no filters key', () => {
      select(['/a.jpg', '/b.jpg']);
      const dialog = TestBed.inject(MatDialog);

      component.openExportDialog();

      const data = (dialog.open as Mock).mock.calls[0][1].data;
      expect(data).toEqual({ paths: ['/a.jpg', '/b.jpg'] });
      expect(data.filters).toBeUndefined();
    });
  });

  describe('whole-view selection', () => {
    const photo = (path: string) => ({ path, filename: path.slice(1) });

    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    const offered = () => (component as unknown as { offerWholeView: () => boolean }).offerWholeView();

    describe('the banner offering to widen the selection', () => {
      beforeEach(() => {
        mockStore.photos.set(['/a.jpg', '/b.jpg'].map(photo));
        mockStore.total.set(650);
        select(['/a.jpg', '/b.jpg']);
      });

      it('shows when every loaded photo is selected and the view holds more', () => {
        expect(offered()).toBe(true);
      });

      it('stays hidden while only part of the loaded page is selected', () => {
        select(['/a.jpg']);
        expect(offered()).toBe(false);
      });

      it('stays hidden when the loaded page IS the whole view — nothing to widen to', () => {
        mockStore.total.set(2);
        expect(offered()).toBe(false);
      });

      it('stays hidden once the selection is already the whole view', () => {
        mockStore.viewScopeSelected.set(true);
        expect(offered()).toBe(false);
      });

      it('stays hidden under a view with no filter form to widen into', () => {
        mockStore.canScopeSelectionToView.set(false);
        expect(offered()).toBe(false);
      });
    });

    // Both "select all in view" and its sibling "select all" render inside an
    // @if keyed on the very selection state their own click flips, so Angular
    // removes the still-focused button on the same tick that the click
    // handler runs. Without focus restoration the browser drops focus to
    // document.body and announces nothing.
    describe('focus and announcement when a toggle button removes itself', () => {
      let liveAnnouncer: { announce: Mock };
      let statusEl: HTMLElement;
      let vanishingButton: HTMLElement;

      beforeEach(() => {
        liveAnnouncer = TestBed.inject(LiveAnnouncer) as unknown as { announce: Mock };
        // Stand-ins for the real template markup: the always-rendered status
        // span the fix anchors focus to, and the button the click originated
        // from -- which the real @if would remove right after.
        statusEl = document.createElement('span');
        statusEl.setAttribute('data-selection-status', '');
        statusEl.tabIndex = -1;
        document.body.appendChild(statusEl);
        vanishingButton = document.createElement('button');
        document.body.appendChild(vanishingButton);
        vanishingButton.focus();
      });

      afterEach(() => {
        statusEl.remove();
        vanishingButton.remove();
      });

      it('moves focus off the "select all in view" button onto the status text', () => {
        mockStore.viewScopeSelected.set(true);
        mockStore.selectionCount.set(650);
        expect(document.activeElement).toBe(vanishingButton);

        (component as unknown as { selectWholeView: () => void }).selectWholeView();

        expect(document.activeElement).toBe(statusEl);
        expect(document.activeElement).not.toBe(document.body);
      });

      it('announces the new whole-view selection state', () => {
        mockStore.viewScopeSelected.set(true);
        mockStore.selectionCount.set(650);

        (component as unknown as { selectWholeView: () => void }).selectWholeView();

        expect(liveAnnouncer.announce).toHaveBeenCalledWith('gallery.selection.view_scope_active');
      });

      it('moves focus off the sibling "select all" button onto the status text', () => {
        mockStore.selectionCount.set(2);
        expect(document.activeElement).toBe(vanishingButton);

        (component as unknown as { selectAll: () => void }).selectAll();

        expect(document.activeElement).toBe(statusEl);
        expect(document.activeElement).not.toBe(document.body);
      });

      it('announces the new selection count from the sibling "select all" button', () => {
        mockStore.selectionCount.set(2);

        (component as unknown as { selectAll: () => void }).selectAll();

        expect(liveAnnouncer.announce).toHaveBeenCalledWith('gallery.selection.count');
      });

      it('announces the new count when the selection is inverted', () => {
        mockStore.selectionCount.set(7);

        (component as unknown as { invertSelection: () => void }).invertSelection();

        expect(liveAnnouncer.announce).toHaveBeenCalledWith('gallery.selection.count');
      });

      it('leaves focus on the invert button, which survives its own click', () => {
        mockStore.selectionCount.set(7);
        expect(document.activeElement).toBe(vanishingButton);

        (component as unknown as { invertSelection: () => void }).invertSelection();

        expect(document.activeElement).toBe(vanishingButton);
        expect(document.activeElement).not.toBe(statusEl);
      });
    });

    describe('confirming a mutation that runs over the whole view', () => {
      let dialog: MatDialog;
      let snackOpen: Mock;

      beforeEach(() => {
        mockStore.photos.set(['/a.jpg', '/b.jpg'].map(photo));
        mockStore.total.set(650);
        mockStore.viewScopeSelected.set(true);
        mockStore.selectionScope.set('view');
        mockStore.selectionCount.set(650);
        dialog = TestBed.inject(MatDialog);
        snackOpen = TestBed.inject(MatSnackBar).open as Mock;
      });

      const favorite = () =>
        (component as unknown as { batchFavorite: () => Promise<void> }).batchFavorite();

      it('counts the view from the server, then asks, before writing anything', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });

        await favorite();

        expect(mockStore.countInView).toHaveBeenCalled();
        expect(dialog.open).toHaveBeenCalled();
        expect((dialog.open as Mock).mock.calls[0][1].data.message)
          .toBe('gallery.selection.view_scope_confirm_message');
        expect(mockStore.batchFavorite).toHaveBeenCalled();
      });

      it('writes nothing when the confirmation is declined', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(false) });

        await favorite();

        expect(mockStore.batchFavorite).not.toHaveBeenCalled();
      });

      it('writes nothing when the count cannot be fetched', async () => {
        mockStore.countInView.mockResolvedValue(null);

        await favorite();

        expect(dialog.open).not.toHaveBeenCalled();
        expect(mockStore.batchFavorite).not.toHaveBeenCalled();
      });

      // The server total minus what the user unticked can land on zero — the
      // whole view was already excluded down to nothing. That must short-
      // circuit before the confirm dialog, not open it to confirm acting on 0.
      it('tells the user there is nothing to act on when exclusions cover the whole view', async () => {
        mockStore.excludedPaths.set(new Set(['/a.jpg', '/b.jpg']));
        mockStore.countInView.mockResolvedValue(2);

        await favorite();

        expect(dialog.open).not.toHaveBeenCalled();
        expect(mockStore.batchFavorite).not.toHaveBeenCalled();
        expect(snackOpen.mock.calls.some(c => c[0] === 'gallery.selection.view_scope_empty')).toBe(true);
      });

      // The user approved a number; if the view moved under the write, say so
      // rather than quietly reporting whatever happened.
      it('reports a server count that disagrees with the number confirmed', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });
        mockStore.countInView.mockResolvedValue(650);
        mockStore.batchFavorite.mockResolvedValue({ snapshot: new Map(), targeted: 650, count: 640 });

        await favorite();

        expect(snackOpen.mock.calls.some(c => c[0] === 'gallery.selection.view_scope_mismatch')).toBe(true);
      });

      it('says nothing when the server changed exactly what was confirmed', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });
        mockStore.countInView.mockResolvedValue(650);
        mockStore.batchFavorite.mockResolvedValue({ snapshot: new Map(), targeted: 650, count: 650 });

        await favorite();

        expect(snackOpen.mock.calls.some(c => c[0] === 'gallery.selection.view_scope_mismatch')).toBe(false);
      });
    });

    it('refuses to declare a whole view one panorama', async () => {
      mockStore.viewScopeSelected.set(true);
      mockStore.selectionCount.set(650);

      await (component as unknown as { markAsPanorama: (k: string) => Promise<void> })
        .markAsPanorama('panorama');

      expect(mockApi.post).not.toHaveBeenCalled();
    });
  });

  describe('undo is only offered when it would restore everything', () => {
    const snap = { is_favorite: false, is_rejected: false, star_rating: null };
    let undoRegister: Mock;
    let snackOpen: Mock;

    beforeEach(() => {
      undoRegister = vi.fn();
      vi.spyOn(TestBed.inject(UndoService), 'register').mockImplementation(undoRegister);
      snackOpen = TestBed.inject(MatSnackBar).open as Mock;
    });

    const reject = () => (component as unknown as { batchReject: () => Promise<void> }).batchReject();

    it('offers undo when the snapshot covers every photo the action touched', async () => {
      mockStore.selectedPaths.set(new Set(['/a.jpg', '/b.jpg']));
      mockStore.selectionCount.set(2);
      mockStore.batchReject.mockResolvedValue({
        snapshot: new Map([['/a.jpg', snap], ['/b.jpg', snap]]), targeted: 2, count: 2,
      });

      await reject();

      expect(undoRegister).toHaveBeenCalled();
    });

    // The snapshot is built from the LOADED photos, so a 5,000-path selection
    // (from "Keep top N%") yields a ~64-entry one: small enough to pass the
    // UNDO_MAX_PHOTOS gate, and an "undo" that would restore 64 of 5,000.
    it('withholds undo when the snapshot covers only the loaded page of a much larger action', async () => {
      const paths = Array.from({ length: 5000 }, (_, i) => `/p${i}.jpg`);
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
      mockStore.batchReject.mockResolvedValue({
        snapshot: new Map(paths.slice(0, 64).map(path => [path, snap])),
        targeted: 5000,
        count: 5000,
      });

      await reject();

      expect(undoRegister).not.toHaveBeenCalled();
      expect(snackOpen.mock.calls.some(c => c[0] === 'gallery.selection.batch_rejected')).toBe(true);
    });

    it('withholds undo for a whole-view action, whose snapshot can never cover it', async () => {
      mockStore.viewScopeSelected.set(true);
      mockStore.selectionScope.set('view');
      mockStore.selectionCount.set(650);
      (TestBed.inject(MatDialog).open as Mock).mockReturnValue({ afterClosed: () => of(true) });
      mockStore.batchReject.mockResolvedValue({
        snapshot: new Map([['/a.jpg', snap]]), targeted: 650, count: 650,
      });

      await reject();

      expect(undoRegister).not.toHaveBeenCalled();
    });
  });

  describe('marking a selection as one panorama', () => {
    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    const mark = (kind: SequenceKind = 'panorama') =>
      (component as unknown as { markAsPanorama: (k: SequenceKind) => Promise<void> }).markAsPanorama(kind);

    // The gallery is the only surface that can correct a MISS: an undetected
    // sweep is in no culling group, so it can only be named where its frames
    // are visible as ordinary photos.
    it('sends every selected path with the chosen kind', async () => {
      select(['/a.jpg', '/b.jpg', '/c.jpg']);

      await mark('hdr_panorama');

      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/override_sequence', {
        paths: ['/a.jpg', '/b.jpg', '/c.jpg'],
        kind: 'hdr_panorama',
      });
    });

    it('marks the photos pending and clears the selection', async () => {
      select(['/a.jpg', '/b.jpg']);

      await mark();

      expect(mockStore.patchSequenceOverride).toHaveBeenCalledWith(['/a.jpg', '/b.jpg'], 'panorama');
      expect(mockStore.clearSelection).toHaveBeenCalled();
    });

    it('refuses a single photo — one frame is not a set', async () => {
      select(['/a.jpg']);

      await mark();

      expect(mockApi.post).not.toHaveBeenCalled();
    });

    // The server caps a sequence correction at MARK_SEQUENCE_MAX_PHOTOS (500)
    // frames; a set is a handful of frames one camera shot together, never
    // hundreds, so this refusal is client-side, before any request is sent.
    it('refuses more paths than the server-side correction cap', async () => {
      const paths = Array.from({ length: 501 }, (_, i) => `/p${i}.jpg`);
      select(paths);
      const snackOpen = TestBed.inject(MatSnackBar).open as Mock;

      await mark();

      expect(mockApi.post).not.toHaveBeenCalled();
      expect(mockStore.patchSequenceOverride).not.toHaveBeenCalled();
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
      expect(snackOpen.mock.calls.some(c => c[0] === 'gallery.selection.mark_too_many')).toBe(true);
    });

    it('marks nothing when the server refuses', async () => {
      select(['/a.jpg', '/b.jpg']);
      mockApi.post.mockReturnValueOnce(throwError(() => new Error('nope')));

      await mark();

      expect(mockStore.patchSequenceOverride).not.toHaveBeenCalled();
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
    });

    it('sends kind: bracket and uses the bracket-worded undo label', async () => {
      const undoRegister = vi.fn();
      vi.spyOn(TestBed.inject(UndoService), 'register').mockImplementation(undoRegister);
      select(['/a.jpg', '/b.jpg']);

      await mark('bracket');

      expect(mockApi.post).toHaveBeenCalledWith('/culling-groups/override_sequence', {
        paths: ['/a.jpg', '/b.jpg'],
        kind: 'bracket',
      });
      expect(undoRegister).toHaveBeenCalledWith(
        expect.objectContaining({ labelKey: 'gallery.selection.marked_bracket' }));
    });

    it('shows the ladder-specific message when a bracket mark 400s', async () => {
      select(['/a.jpg', '/b.jpg']);
      mockApi.post.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 400 })));
      const snackOpen = TestBed.inject(MatSnackBar).open as Mock;

      await mark('bracket');

      expect(snackOpen.mock.calls.some(c => c[0] === 'culling.bracket.not_a_ladder')).toBe(true);
    });

    it('keeps the generic error for a non-bracket 400', async () => {
      select(['/a.jpg', '/b.jpg']);
      mockApi.post.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 400 })));
      const snackOpen = TestBed.inject(MatSnackBar).open as Mock;

      await mark('panorama');

      expect(snackOpen.mock.calls.some(c => c[0] === 'errors.action_failed')).toBe(true);
      expect(snackOpen.mock.calls.some(c => c[0] === 'culling.bracket.not_a_ladder')).toBe(false);
    });
  });

  describe('downloadSelected', () => {
    function select(paths: string[]) {
      mockStore.selectedPaths.set(new Set(paths));
      mockStore.selectionCount.set(paths.length);
    }

    const download = () =>
      (component as unknown as { downloadSelected: () => Promise<void> }).downloadSelected();

    // Past DOWNLOAD_CONFIRM_PHOTOS (50), a download is one blob fetch plus one
    // synthetic anchor click PER PHOTO, serially -- confirm before starting
    // something that size by accident.
    it('asks for confirmation before downloading more than DOWNLOAD_CONFIRM_PHOTOS photos', async () => {
      select(Array.from({ length: 51 }, (_, i) => `/p${i}.jpg`));
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(false) });

      await download();

      expect(dialog.open).toHaveBeenCalled();
      expect((dialog.open as Mock).mock.calls[0][1].data.message)
        .toBe('gallery.selection.download_confirm_message');
      expect(mockApi.getRaw).not.toHaveBeenCalled();
    });

    it('downloads once an oversized selection is confirmed', async () => {
      select(Array.from({ length: 51 }, (_, i) => `/p${i}.jpg`));
      const dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });

      await download();

      expect(mockApi.getRaw).toHaveBeenCalled();
    });

    it('downloads without confirming at or under the limit', async () => {
      select(Array.from({ length: 50 }, (_, i) => `/p${i}.jpg`));
      const dialog = TestBed.inject(MatDialog);

      await download();

      expect(dialog.open).not.toHaveBeenCalled();
      expect(mockApi.getRaw).toHaveBeenCalled();
    });
  });

  // Under a whole-view selection these three actions read no local selection at
  // all: they ask the server for the paths, which can resolve to null — a
  // refusal past the endpoint's cap, a failed request, or a declined
  // confirmation. A swapped condition or a dropped null check would turn all
  // three into silent no-ops with the rest of the suite still green.
  describe('actions that resolve a whole-view selection to paths', () => {
    let dialog: MatDialog;
    let addPhotos: Mock;
    let writeText: Mock;
    let clipboardDescriptor: PropertyDescriptor | undefined;

    beforeEach(() => {
      mockStore.viewScopeSelected.set(true);
      mockStore.selectionScope.set('view');
      mockStore.selectionCount.set(650);
      mockStore.total.set(650);
      mockStore.pathsInView.mockResolvedValue(['/x.jpg', '/y.jpg']);
      dialog = TestBed.inject(MatDialog);
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });
      addPhotos = TestBed.inject(AlbumService).addPhotos as unknown as Mock;
      writeText = vi.fn(() => Promise.resolve());
      clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
      Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
    });

    // The stub is a global: left in place it outlives this describe and hands a
    // fake clipboard to every test appended after it.
    afterEach(() => {
      if (clipboardDescriptor) Object.defineProperty(navigator, 'clipboard', clipboardDescriptor);
      else delete (navigator as unknown as { clipboard?: unknown }).clipboard;
    });

    const copy = () => (component as unknown as { copyPaths: () => Promise<void> }).copyPaths();
    const download = () =>
      (component as unknown as { downloadSelected: () => Promise<void> }).downloadSelected();
    const addToAlbum = () => component.addToAlbum(3);

    describe('copy filenames', () => {
      it('copies the paths the server resolved, not the empty local selection', async () => {
        await copy();

        expect(mockStore.pathsInView).toHaveBeenCalled();
        expect(writeText).toHaveBeenCalledWith('x.jpg\ny.jpg');
      });

      it('copies nothing when the view cannot be resolved to paths', async () => {
        mockStore.pathsInView.mockResolvedValue(null);

        await copy();

        expect(writeText).not.toHaveBeenCalled();
      });

      // Copying changes nothing, so it must not borrow the wording that tells
      // the user their photos are about to be modified.
      it('confirms against the server count, in words that match a copy', async () => {
        await copy();

        expect(mockStore.countInView).toHaveBeenCalled();
        expect((dialog.open as Mock).mock.calls[0][1].data.message)
          .toBe('gallery.selection.view_scope_copy_message');
      });

      it('does not even fetch the paths when the confirmation is declined', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(false) });

        await copy();

        expect(mockStore.pathsInView).not.toHaveBeenCalled();
        expect(writeText).not.toHaveBeenCalled();
      });
    });

    describe('download', () => {
      const fiftyOne = Array.from({ length: 51 }, (_, i) => `/p${i}.jpg`);

      it('downloads the paths the server resolved', async () => {
        await download();

        expect(mockStore.pathsInView).toHaveBeenCalled();
        expect(mockApi.getRaw).toHaveBeenCalled();
      });

      it('downloads nothing when the view cannot be resolved to paths', async () => {
        mockStore.pathsInView.mockResolvedValue(null);

        await download();

        expect(mockApi.getRaw).not.toHaveBeenCalled();
      });

      // The download already confirms in its own words, against the count it
      // actually resolved: two dialogs for one click would be worse than one.
      it('confirms exactly once, with the download wording', async () => {
        mockStore.pathsInView.mockResolvedValue(fiftyOne);

        await download();

        expect((dialog.open as Mock).mock.calls.length).toBe(1);
        expect((dialog.open as Mock).mock.calls[0][1].data.message)
          .toBe('gallery.selection.download_confirm_message');
      });

      it('downloads nothing when that confirmation is declined', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(false) });
        mockStore.pathsInView.mockResolvedValue(fiftyOne);

        await download();

        expect(mockApi.getRaw).not.toHaveBeenCalled();
      });
    });

    describe('add to album', () => {
      it('adds the paths the server resolved', async () => {
        await addToAlbum();

        expect(addPhotos).toHaveBeenCalledWith(3, ['/x.jpg', '/y.jpg']);
        expect(mockStore.clearSelection).toHaveBeenCalled();
      });

      it('adds nothing when the view cannot be resolved to paths', async () => {
        mockStore.pathsInView.mockResolvedValue(null);

        await addToAlbum();

        expect(addPhotos).not.toHaveBeenCalled();
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
      });

      // Filing photos into an album writes album_photos rows and modifies no
      // photo, so it must not borrow the mutation's wording either.
      it('confirms in the words of filing, not of changing the photos', async () => {
        await addToAlbum();

        expect((dialog.open as Mock).mock.calls[0][1].data.message)
          .toBe('gallery.selection.view_scope_album_message');
      });

      // One album_photos row per photo in the view, with no undo: the least it
      // can do is ask.
      it('adds nothing when the confirmation is declined', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(false) });

        await addToAlbum();

        expect(mockStore.pathsInView).not.toHaveBeenCalled();
        expect(addPhotos).not.toHaveBeenCalled();
      });
    });
  });

  // The scan entry lives in the shell header (app.html, covered by app.spec.ts); the
  // gallery keeps only the empty-state call to action.
  describe('scan entry (gallery page)', () => {
    const photos = Array.from({ length: 3 }, (_, n) => ({
      path: `/p${n}.jpg`, filename: `p${n}.jpg`, image_width: 4000, image_height: 3000,
      is_favorite: false, is_rejected: false, unassigned_faces: 0,
    }));
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
    });

    function render(canLaunch: boolean, library: typeof photos, launched = true) {
      mockAuth['downloadProfiles'] = vi.fn(() => []);
      mockStore.photos.set(library);
      mockStore.total.set(library.length);
      const scan = TestBed.inject(ScanService) as unknown as { canLaunch: WritableSignal<boolean>; openLauncher: Mock };
      scan.canLaunch.set(canLaunch);
      scan.openLauncher.mockResolvedValue(launched);
      fixture = TestBed.createComponent(GalleryComponent);
      fixture.detectChanges();
      return { f: fixture, scan };
    }

    function allButtons(f: ComponentFixture<GalleryComponent>): HTMLButtonElement[] {
      return Array.from(f.nativeElement.querySelectorAll('button')) as HTMLButtonElement[];
    }

    function getStarted(f: ComponentFixture<GalleryComponent>): HTMLButtonElement[] {
      return allButtons(f).filter(b => b.textContent?.includes(I18N.scan.get_started));
    }

    it('renders no scan button above a populated grid', () => {
      // A locked single-user install with an unlocked edition session, which used to earn the button.
      mockAuth['hasFeature'] = vi.fn(() => true);
      mockAuth['isMultiUser'] = vi.fn(() => false);
      mockAuth['editionPasswordRequired'] = vi.fn(() => true);
      mockAuth['isEdition'] = vi.fn(() => true);
      const { f } = render(true, photos);
      expect(allButtons(f).filter(b => b.getAttribute('aria-label') === I18N.gallery.scan_action)).toHaveLength(0);
      expect(getStarted(f)).toHaveLength(0);
    });

    it('offers the get-started button on an empty, unfiltered library when scanning is allowed', () => {
      expect(getStarted(render(true, []).f)).toHaveLength(1);
    });

    it('withholds the get-started button when scanning is not allowed', () => {
      expect(getStarted(render(false, []).f)).toHaveLength(0);
    });

    it('reloads the counts and the photos when the launcher reports a completed scan', async () => {
      const { f, scan } = render(true, []);
      getStarted(f)[0].click();
      await vi.waitFor(() => expect(mockStore.reloadPhotos).toHaveBeenCalledTimes(1));
      expect(scan.openLauncher).toHaveBeenCalledTimes(1);
      expect(mockStore.loadTypeCounts).toHaveBeenCalled();
    });

    it('reloads nothing when the launcher is dismissed', async () => {
      const { f, scan } = render(true, [], false);
      await f.whenStable();
      mockStore.loadTypeCounts.mockClear();
      mockStore.reloadPhotos.mockClear();
      getStarted(f)[0].click();
      await vi.waitFor(() => expect(scan.openLauncher).toHaveBeenCalledTimes(1));
      await f.whenStable();
      expect(mockStore.loadTypeCounts).not.toHaveBeenCalled();
      expect(mockStore.reloadPhotos).not.toHaveBeenCalled();
    });
  });

  // The gallery's right-click menu acts on explicit paths: the menu's single-photo
  // actions must reach these methods without resolving, confirming over or
  // clearing the selection the user has built (and, under view scope, without
  // asking the server for the whole view).
  describe('explicit paths override (context menu)', () => {
    let dialog: MatDialog;
    let addPhotos: Mock;
    let writeText: Mock;
    let clipboardDescriptor: PropertyDescriptor | undefined;
    const photo = (path: string, extra: Record<string, unknown> = {}) => ({ path, filename: path.slice(1), ...extra });

    function selectThree(): void {
      mockStore.photos.set([photo('/a.jpg'), photo('/b.jpg'), photo('/c.jpg'), photo('/x.jpg')]);
      mockStore.selectedPaths.set(new Set(['/a.jpg', '/b.jpg', '/c.jpg']));
      mockStore.selectionCount.set(3);
    }

    function selectView(): void {
      mockStore.viewScopeSelected.set(true);
      mockStore.selectionScope.set('view');
      mockStore.selectionCount.set(650);
      mockStore.total.set(650);
    }

    beforeEach(() => {
      dialog = TestBed.inject(MatDialog);
      addPhotos = TestBed.inject(AlbumService).addPhotos as unknown as Mock;
      writeText = vi.fn(() => Promise.resolve());
      clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
      Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
      selectThree();
    });

    afterEach(() => {
      if (clipboardDescriptor) Object.defineProperty(navigator, 'clipboard', clipboardDescriptor);
      else delete (navigator as unknown as { clipboard?: unknown }).clipboard;
    });

    const copy = (paths?: string[]) =>
      (component as unknown as { copyPaths: (p?: string[]) => Promise<void> }).copyPaths(paths);
    const download = (paths?: string[]) =>
      (component as unknown as { downloadSelected: (t?: string, pr?: string, p?: string[]) => Promise<void> })
        .downloadSelected('original', undefined, paths);

    it('addToAlbum adds exactly the given paths and leaves the selection alone', async () => {
      await component.addToAlbum(3, ['/x.jpg']);

      expect(addPhotos).toHaveBeenCalledWith(3, ['/x.jpg']);
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
      expect(mockStore.pathsInView).not.toHaveBeenCalled();
      expect(dialog.open).not.toHaveBeenCalled();
    });

    it('an empty paths list is a no-op, never a fall-back to the selection', async () => {
      await component.addToAlbum(3, []);
      await copy([]);

      expect(addPhotos).not.toHaveBeenCalled();
      expect(writeText).not.toHaveBeenCalled();
    });

    it('addToAlbum without paths still adds the selection and clears it', async () => {
      await component.addToAlbum(3);

      expect(addPhotos).toHaveBeenCalledWith(3, ['/a.jpg', '/b.jpg', '/c.jpg']);
      expect(mockStore.clearSelection).toHaveBeenCalled();
    });

    it('createAlbumAndAdd forwards the paths to addToAlbum', async () => {
      (dialog.open as Mock).mockReturnValue({ afterClosed: () => of({ id: 9, name: 'N' }) });

      await component.createAlbumAndAdd(['/x.jpg']);

      expect(addPhotos).toHaveBeenCalledWith(9, ['/x.jpg']);
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
    });

    describe('under a whole-view selection', () => {
      beforeEach(() => {
        selectView();
        mockStore.pathsInView.mockResolvedValue(['/q.jpg']);
      });

      it('addToAlbum, copyPaths and downloadSelected use the given paths without asking the server', async () => {
        await component.addToAlbum(3, ['/x.jpg']);
        await copy(['/x.jpg']);
        await download(['/x.jpg']);

        expect(addPhotos).toHaveBeenCalledWith(3, ['/x.jpg']);
        expect(writeText).toHaveBeenCalledWith('x.jpg');
        expect(mockApi.downloadUrl).toHaveBeenCalledWith('/x.jpg', 'original', undefined);
        expect(mockStore.countInView).not.toHaveBeenCalled();
        expect(mockStore.pathsInView).not.toHaveBeenCalled();
        expect(dialog.open).not.toHaveBeenCalled();
      });
    });

    it('copyPaths writes the basenames of the given paths', async () => {
      await copy(['/d/one.jpg']);

      expect(writeText).toHaveBeenCalledWith('one.jpg');
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
    });

    it('downloadSelected downloads only the given paths', async () => {
      await download(['/x.jpg']);

      expect(mockApi.downloadUrl).toHaveBeenCalledTimes(1);
      expect(mockApi.downloadUrl).toHaveBeenCalledWith('/x.jpg', 'original', undefined);
    });

    describe('openExportDialog', () => {
      it('opens the dialog for the given paths even on an album route', () => {
        routeMock.snapshot.paramMap.get = vi.fn(() => '42');

        component.openExportDialog(['/x.jpg']);

        expect((dialog.open as Mock).mock.calls[0][1].data).toEqual({ paths: ['/x.jpg'] });
      });

      it('still exports the whole album on an album route when no paths are given', () => {
        routeMock.snapshot.paramMap.get = vi.fn(() => '42');

        component.openExportDialog();

        expect((dialog.open as Mock).mock.calls[0][1].data).toEqual({ albumId: 42 });
      });

      it('ignores view scope when paths are given', () => {
        selectView();

        component.openExportDialog(['/x.jpg']);

        expect((dialog.open as Mock).mock.calls[0][1].data).toEqual({ paths: ['/x.jpg'] });
      });
    });

    describe('openCullDialog', () => {
      // The real store's loadPhotos() ends a whole-view selection, and its
      // selection methods move the signals. An inert mock hides both.
      beforeEach(() => {
        const setScope = (view: boolean, selected: Iterable<string>, excluded: Iterable<string>) => {
          mockStore.viewScopeSelected.set(view);
          mockStore.selectionScope.set(view ? 'view' : 'paths');
          mockStore.selectedPaths.set(new Set(selected));
          mockStore.excludedPaths.set(new Set(excluded));
        };
        mockStore.loadPhotos.mockImplementation(() => {
          if (mockStore.viewScopeSelected()) setScope(false, [], []);
          return Promise.resolve();
        });
        mockStore.selectWholeView.mockImplementation(() => setScope(true, [], []));
        mockStore.restoreSelection.mockImplementation((paths: Iterable<string>) => setScope(false, paths, []));
        mockStore.toggleSelection.mockImplementation((p: { path: string }) => {
          const target = mockStore.viewScopeSelected() ? mockStore.excludedPaths : mockStore.selectedPaths;
          const next = new Set(target());
          if (!next.delete(p.path)) next.add(p.path);
          target.set(next);
        });
      });

      it('sends the given paths with no filter even under view scope', async () => {
        selectView();
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });

        await component.openCullDialog(['/x.jpg']);

        const data = (dialog.open as Mock).mock.calls[0][1].data;
        expect(data.paths).toEqual(['/x.jpg']);
        expect(data.filters).toBeNull();
        expect(data.exclude).toEqual([]);
        expect(data.count).toBe(1);
        expect(mockStore.reloadPhotos).toHaveBeenCalled();
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
      });

      it('keeps the whole-view selection across the reload, with the culled photo now excluded', async () => {
        selectView();
        mockStore.excludedPaths.set(new Set(['/e.jpg']));
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });

        await component.openCullDialog(['/x.jpg']);

        expect(mockStore.viewScopeSelected()).toBe(true);
        expect(mockStore.selectionScope()).toBe('view');
        expect([...mockStore.excludedPaths()].sort()).toEqual(['/e.jpg', '/x.jpg']);
      });

      it('drops the target from a path selection, and only it', async () => {
        mockStore.selectedPaths.set(new Set(['/a.jpg', '/x.jpg']));
        mockStore.selectionCount.set(2);
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });

        await component.openCullDialog(['/x.jpg']);

        expect([...mockStore.selectedPaths()]).toEqual(['/a.jpg']);
        expect(mockStore.selectionScope()).toBe('paths');
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
      });

      it('leaves a path selection alone when the target was not selected', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(true) });

        await component.openCullDialog(['/x.jpg']);

        expect([...mockStore.selectedPaths()].sort()).toEqual(['/a.jpg', '/b.jpg', '/c.jpg']);
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
      });

      it('touches nothing when the dialog is dismissed', async () => {
        mockStore.selectedPaths.set(new Set(['/x.jpg']));
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

        await component.openCullDialog(['/x.jpg']);

        expect(mockStore.loadPhotos).not.toHaveBeenCalled();
        expect(mockStore.toggleSelection).not.toHaveBeenCalled();
      });
    });

    describe('deleteSelected', () => {
      const confirmed = { includeCompanions: false, includeSequenceSiblings: false };
      const deleted = (paths: string[]) => of({
        dry_run: false, deleted: paths, not_found: [], not_visible: [], refused_bracket_lead: [],
        sequence_siblings: [], skipped: [], trashed: paths.length, errors: {},
      });

      it('opens the single-photo dialog under view scope, where the no-arg form refuses', async () => {
        selectView();
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });

        await component.deleteSelected(['/x.jpg']);

        const data = (dialog.open as Mock).mock.calls[0][1].data;
        expect(data.surface).toBe('photo_detail');
        expect(data.paths).toEqual(['/x.jpg']);
        expect(data.count).toBe(1);
      });

      it('removes only the deleted path and does not clear the selection', async () => {
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(confirmed) });
        mockApi.post.mockReturnValueOnce(deleted(['/x.jpg']));

        await component.deleteSelected(['/x.jpg']);

        expect(mockApi.post).toHaveBeenCalledWith('/photo/delete', expect.objectContaining({ paths: ['/x.jpg'] }));
        expect(mockStore.removePhotos).toHaveBeenCalledWith(['/x.jpg']);
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
      });

      it('returns without a dialog when the photo is no longer loaded', async () => {
        await component.deleteSelected(['/gone.jpg']);

        expect(dialog.open).not.toHaveBeenCalled();
      });

      it('flags a bracket base exposure as a lead, and nothing else', async () => {
        mockStore.photos.set([
          photo('/lead.jpg', { sequence_kind: 'bracket', sequence_ev_offset: 0 }),
          photo('/dark.jpg', { sequence_kind: 'bracket', sequence_ev_offset: -2 }),
          photo('/pano.jpg', { sequence_kind: 'panorama', sequence_ev_offset: 0 }),
        ]);
        (dialog.open as Mock).mockReturnValue({ afterClosed: () => of(null) });
        const leadOf = async (path: string) => {
          (dialog.open as Mock).mockClear();
          await component.deleteSelected([path]);
          return (dialog.open as Mock).mock.calls[0][1].data;
        };

        expect((await leadOf('/lead.jpg')).hasBracketLead).toBe(true);
        expect((await leadOf('/lead.jpg')).hasSiblings).toBe(true);
        expect((await leadOf('/dark.jpg')).hasBracketLead).toBe(false);
        expect((await leadOf('/pano.jpg')).hasBracketLead).toBe(false);
        expect((await leadOf('/pano.jpg')).hasSiblings).toBe(true);
      });

      it('without paths still refuses under view scope', async () => {
        selectView();

        await component.deleteSelected();

        expect(dialog.open).not.toHaveBeenCalled();
      });
    });
  });

  describe('onPhotoMenuAction', () => {
    interface Menu {
      onPhotoMenuAction(e: { action: unknown; photo: unknown; bulk: boolean }): Promise<void>;
      runSelectionAction(a: unknown): Promise<void>;
    }
    const menu = () => component as unknown as Menu;
    const target = { path: '/x.jpg', filename: 'x.jpg' };
    const spy = (name: string) =>
      vi.spyOn(component as unknown as Record<string, (...a: unknown[]) => unknown>, name)
        .mockResolvedValue(undefined);

    beforeEach(() => {
      mockStore.photos.set([target]);
      mockStore.selectedPaths.set(new Set(['/a.jpg', '/b.jpg', '/c.jpg']));
      mockStore.selectionCount.set(3);
    });

    it('routes a bulk action through runSelectionAction, never the per-photo store calls', async () => {
      const run = vi.spyOn(menu() as unknown as { runSelectionAction(a: unknown): Promise<void> }, 'runSelectionAction')
        .mockResolvedValue();

      await menu().onPhotoMenuAction({ action: { kind: 'favorite' }, photo: target, bulk: true });

      expect(run).toHaveBeenCalledTimes(1);
      expect(run).toHaveBeenCalledWith({ kind: 'favorite' });
      expect(mockStore.toggleFavorite).not.toHaveBeenCalled();
    });

    describe('runSelectionAction covers every sheet kind', () => {
      const cases: [string, unknown, string, unknown[]][] = [
        ['favorite', { kind: 'favorite' }, 'batchFavorite', []],
        ['reject', { kind: 'reject' }, 'batchReject', []],
        ['rate', { kind: 'rate', rating: 4 }, 'batchRate', [4]],
        ['album', { kind: 'album', albumId: 5 }, 'addToAlbum', [5]],
        ['create-album', { kind: 'create-album' }, 'createAlbumAndAdd', []],
        ['invert', { kind: 'invert' }, 'invertSelection', []],
        ['compare', { kind: 'compare' }, 'compareSelection', []],
        ['export', { kind: 'export' }, 'openExportDialog', []],
        ['cull', { kind: 'cull' }, 'openCullDialog', []],
        ['delete', { kind: 'delete' }, 'deleteSelected', []],
        ['copy', { kind: 'copy' }, 'copyPaths', []],
        ['mark-panorama', { kind: 'mark-panorama', sequenceKind: 'bracket' }, 'markAsPanorama', ['bracket']],
        ['download', { kind: 'download', type: 'darktable', profile: 'P' }, 'downloadSelected', ['darktable', 'P']],
        ['tags', { kind: 'tags' }, 'openManualTagsDialog', []],
      ];
      for (const [name, action, method, args] of cases) {
        it(`${name} -> ${method}`, async () => {
          const target = spy(method);

          await menu().runSelectionAction(action);

          expect(target).toHaveBeenCalledTimes(1);
          expect(target).toHaveBeenCalledWith(...args);
        });
      }
    });

    describe('single photo', () => {
      const single = (action: unknown) =>
        menu().onPhotoMenuAction({ action, photo: target, bulk: false });

      afterEach(() => {
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
        expect(mockStore.toggleSelection).not.toHaveBeenCalled();
        expect(mockStore.batchFavorite).not.toHaveBeenCalled();
        expect(mockStore.batchReject).not.toHaveBeenCalled();
        expect(mockStore.batchRating).not.toHaveBeenCalled();
      });

      it('toggle-favorite toggles that one photo', async () => {
        await single({ kind: 'toggle-favorite' });
        expect(mockStore.toggleFavorite).toHaveBeenCalledWith('/x.jpg');
      });

      it('toggle-reject toggles that one photo', async () => {
        await single({ kind: 'toggle-reject' });
        expect(mockStore.toggleRejected).toHaveBeenCalledWith('/x.jpg');
      });

      it('rate sets that one photo', async () => {
        await single({ kind: 'rate', rating: 3 });
        expect(mockStore.setRating).toHaveBeenCalledWith('/x.jpg', 3);
      });

      it('similar filters by that photo', async () => {
        await single({ kind: 'similar', mode: 'color' });
        expect(mockStore.updateFilters).toHaveBeenCalledWith(
          expect.objectContaining({ similar_to: '/x.jpg', similarity_mode: 'color' }));
      });

      const cases: [string, unknown, string, unknown[]][] = [
        ['open', { kind: 'open' }, 'downloadPhoto', [target]],
        ['critique', { kind: 'critique' }, 'openCritique', [target]],
        ['embed', { kind: 'embed' }, 'embedMetadata', [target]],
        ['assign-face', { kind: 'assign-face' }, 'openAddPerson', [target]],
        ['album', { kind: 'album', albumId: 5 }, 'addToAlbum', [5, ['/x.jpg']]],
        ['create-album', { kind: 'create-album' }, 'createAlbumAndAdd', [['/x.jpg']]],
        ['copy', { kind: 'copy' }, 'copyPaths', [['/x.jpg']]],
        ['export', { kind: 'export' }, 'openExportDialog', [['/x.jpg']]],
        ['cull', { kind: 'cull' }, 'openCullDialog', [['/x.jpg']]],
        ['delete', { kind: 'delete' }, 'deleteSelected', [['/x.jpg']]],
        ['download', { kind: 'download', type: 'raw' }, 'downloadSelected', ['raw', undefined, ['/x.jpg']]],
      ];
      for (const [name, action, method, args] of cases) {
        it(`${name} -> ${method} on that path only`, async () => {
          const called = spy(method);

          await single(action);

          expect(called).toHaveBeenCalledTimes(1);
          expect(called).toHaveBeenCalledWith(...args);
        });
      }

      it('the bulk-only kinds do nothing', async () => {
        const run = spy('runSelectionAction');
        for (const kind of ['invert', 'compare']) await single({ kind });
        await single({ kind: 'mark-panorama', sequenceKind: 'panorama' });
        await single({ kind: 'tags' });
        expect(run).not.toHaveBeenCalled();
        expect(mockStore.updateFilters).not.toHaveBeenCalled();
        expect(mockStore.toggleFavorite).not.toHaveBeenCalled();
      });

      it('leaves the multi-photo selection untouched', async () => {
        spy('copyPaths');
        await single({ kind: 'copy' });
        expect(mockStore.clearSelection).not.toHaveBeenCalled();
        expect(mockStore.toggleSelection).not.toHaveBeenCalled();
        expect(mockStore.restoreSelection).not.toHaveBeenCalled();
      });
    });
  });

  describe('onGridFocusOut and the photo menu overlay', () => {
    const focusOut = (next: HTMLElement | null) =>
      (component as unknown as { onGridFocusOut(e: FocusEvent): void })
        .onGridFocusOut({ relatedTarget: next } as unknown as FocusEvent);

    it('keeps the cursor when focus moves into the cdk overlay container', () => {
      mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }]);
      (component as unknown as { activeIndex: { set(v: number): void } }).activeIndex.set(1);
      const container = document.createElement('div');
      container.className = 'cdk-overlay-container';
      const item = document.createElement('button');
      container.appendChild(item);
      document.body.appendChild(container);

      focusOut(item);
      container.remove();

      expect(activeIndex()).toBe(1);
    });

    it('still drops the cursor when focus goes somewhere unrelated', () => {
      mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }]);
      (component as unknown as { activeIndex: { set(v: number): void } }).activeIndex.set(1);
      const other = document.createElement('button');
      document.body.appendChild(other);

      focusOut(other);
      other.remove();

      expect(activeIndex()).toBe(-1);
    });
  });

  describe('photo context menu (rendered)', () => {
    const TOUCH = '(hover: none) and (pointer: coarse)';
    const photos = Array.from({ length: 12 }, (_, n) => ({
      path: `/p${n}.jpg`, filename: `p${n}.jpg`, image_width: 4000, image_height: 3000,
      is_favorite: false, is_rejected: false, unassigned_faces: 0,
    }));
    let fixture: ComponentFixture<GalleryComponent> | null = null;

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
      vi.unstubAllGlobals();
    });

    function render(mode: 'grid' | 'mosaic', virtual: boolean, touch = false): HTMLElement[] {
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      mockAuth['hasFeature'] = vi.fn(() => false);
      mockAuth['isMultiUser'] = vi.fn(() => false);
      mockAuth['isSuperadmin'] = vi.fn(() => false);
      mockStore.photos.set(photos);
      mockStore.config.set({ features: { show_rating_controls: true, show_similar_button: true } });
      mockStore.galleryMode.set(mode);
      mockStore.virtualScroll.set(virtual);
      const wide = mode === 'mosaic' || virtual;
      vi.stubGlobal('matchMedia', (media: string) => ({
        matches: media === TOUCH ? touch : wide,
        media, addEventListener() {}, removeEventListener() {},
      }));
      fixture = TestBed.createComponent(GalleryComponent);
      const instance = fixture.componentInstance as unknown as {
        desktop: { setup(): void };
        containerWidth: { set(v: number): void };
      };
      if (wide) {
        instance.desktop.setup();
        instance.containerWidth.set(1200);
      }
      fixture.detectChanges();
      // The touch reading lands in afterNextRender, after the first pass.
      TestBed.tick();
      fixture.detectChanges();
      expect(fixture.componentInstance.effectiveGalleryMode()).toBe(mode);
      expect(fixture.componentInstance.virtualOn()).toBe(virtual);
      return [...fixture.nativeElement.querySelectorAll('app-photo-card')] as HTMLElement[];
    }

    function rightClick(card: HTMLElement): MouseEvent {
      const ev = new MouseEvent('contextmenu', {
        button: 2, clientX: 20, clientY: 20, bubbles: true, cancelable: true,
      });
      card.dispatchEvent(ev);
      fixture!.detectChanges();
      return ev;
    }

    const panel = () => document.querySelector('.mat-mdc-menu-panel') as HTMLElement | null;
    const panelCount = () => document.querySelectorAll('.mat-mdc-menu-panel').length;

    for (const [name, mode, virtual] of [
      ['plain grid', 'grid', false],
      ['mosaic', 'mosaic', false],
      ['windowed rows', 'mosaic', true],
    ] as const) {
      describe(name, () => {
        it('opens the menu and suppresses the native one', () => {
          const cards = render(mode, virtual);

          const ev = rightClick(cards[cards.length - 2]);

          expect(ev.defaultPrevented).toBe(true);
          expect(panel()).not.toBeNull();
        });

        it('leaves the native menu on a touch-first device', () => {
          const cards = render(mode, virtual, true);

          const ev = rightClick(cards[cards.length - 2]);

          expect(ev.defaultPrevented).toBe(false);
          expect(panel()).toBeNull();
        });
      });
    }

    it('hides the floating tooltip when the menu opens', () => {
      const cards = render('grid', false);
      (fixture!.componentInstance as unknown as { tooltipPhoto: { set(v: unknown): void; (): unknown } })
        .tooltipPhoto.set(photos[0]);

      rightClick(cards[1]);

      expect((fixture!.componentInstance as unknown as { tooltipPhoto(): unknown }).tooltipPhoto()).toBeNull();
    });

    it('opens the single-photo menu on an unselected photo, leaving the selection alone', () => {
      const cards = render('grid', false);
      mockStore.selectedPaths.set(new Set(['/p0.jpg', '/p1.jpg', '/p2.jpg']));
      mockStore.selectionCount.set(3);
      fixture!.detectChanges();

      rightClick(cards[5]);

      expect(panel()!.textContent).toContain(I18N.shortcuts.open_detail);
      expect(panel()!.textContent).not.toContain(I18N.gallery.selection.mark_sequence);
      expect(mockStore.toggleSelection).not.toHaveBeenCalled();
      expect(mockStore.clearSelection).not.toHaveBeenCalled();
    });

    it('opens the bulk menu on a photo inside a multi-photo selection', () => {
      const cards = render('grid', false);
      mockStore.selectedPaths.set(new Set(['/p0.jpg', '/p1.jpg', '/p2.jpg']));
      mockStore.selectionCount.set(3);
      fixture!.detectChanges();

      rightClick(cards[1]);

      expect(panel()!.textContent).toContain(I18N.gallery.selection.mark_sequence);
      expect(panel()!.textContent).not.toContain(I18N.shortcuts.open_detail);
      expect(mockStore.toggleSelection).not.toHaveBeenCalled();
    });

    it('treats the sole selected photo as a single-photo menu', () => {
      const cards = render('grid', false);
      mockStore.selectedPaths.set(new Set(['/p1.jpg']));
      mockStore.selectionCount.set(1);
      fixture!.detectChanges();

      rightClick(cards[1]);

      expect(panel()!.textContent).toContain(I18N.shortcuts.open_detail);
    });

    it('treats an excluded photo under view scope as a single-photo menu', () => {
      const cards = render('grid', false);
      mockStore.viewScopeSelected.set(true);
      mockStore.excludedPaths.set(new Set(['/p3.jpg']));
      mockStore.selectionCount.set(11);
      fixture!.detectChanges();

      rightClick(cards[3]);

      expect(panel()!.textContent).toContain(I18N.shortcuts.open_detail);
    });

    it('opens from a nested control inside the card too', () => {
      const cards = render('grid', false);

      const ev = new MouseEvent('contextmenu', { button: 2, bubbles: true, cancelable: true });
      (cards[2].querySelector('button') ?? cards[2]).dispatchEvent(ev);
      fixture!.detectChanges();

      expect(ev.defaultPrevented).toBe(true);
      expect(panel()).not.toBeNull();
    });

    it('does not change the selection on a right mouse-down', () => {
      const cards = render('grid', false);

      cards[2].dispatchEvent(new MouseEvent('mousedown', { button: 2, bubbles: true }));
      cards[2].dispatchEvent(new MouseEvent('pointerdown', { button: 2, bubbles: true }));

      expect(mockStore.toggleSelection).not.toHaveBeenCalled();
    });

    it('keeps exactly one panel when a second right-click lands while it is open', () => {
      const cards = render('grid', false);
      rightClick(cards[1]);

      rightClick(cards[1]);

      expect(panelCount()).toBe(1);
    });

    it('runs a picked single action against that photo', () => {
      const cards = render('grid', false);
      rightClick(cards[4]);

      const item = [...document.querySelectorAll('.mat-mdc-menu-item')]
        .find(e => e.textContent?.includes(I18N.rating.add_favorite)) as HTMLElement;
      item.click();
      fixture!.detectChanges();

      expect(mockStore.toggleFavorite).toHaveBeenCalledWith('/p4.jpg');
    });

    it('returns focus to the card when the menu is closed with Escape', () => {
      const cards = render('grid', false);
      rightClick(cards[4]);

      panel()!.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', code: 'Escape', keyCode: 27, bubbles: true }));
      fixture!.detectChanges();

      expect(cards[4].contains(document.activeElement)).toBe(true);
    });

    it('returns focus to the card after an item is picked', () => {
      const cards = render('grid', false);
      rightClick(cards[4]);

      (document.querySelector('.mat-mdc-menu-item') as HTMLElement).click();
      fixture!.detectChanges();

      expect(cards[4].contains(document.activeElement)).toBe(true);
    });

    it('has the card focused at the moment a picked action opens its dialog', () => {
      const cards = render('grid', false);
      let focusedCard = false;
      vi.spyOn(fixture!.componentInstance as unknown as Record<string, (...a: unknown[]) => unknown>, 'openExportDialog')
        .mockImplementation(() => { focusedCard = cards[4].contains(document.activeElement); });
      rightClick(cards[4]);

      const item = [...document.querySelectorAll('.mat-mdc-menu-item')]
        .find(e => e.textContent?.includes(I18N.export.action)) as HTMLElement;
      item.click();
      fixture!.detectChanges();

      expect(focusedCard).toBe(true);
    });

    it('does not steal focus when the menu is dismissed from its backdrop', () => {
      const cards = render('grid', false);
      rightClick(cards[4]);

      (document.querySelector('.cdk-overlay-backdrop') as HTMLElement).click();
      fixture!.detectChanges();

      expect(cards[4].contains(document.activeElement)).toBe(false);
    });
  });

  describe('grouped review layout', () => {
    let fixture: ComponentFixture<GalleryComponent> | null = null;
    const paths = ['/g0.jpg', '/g1.jpg', '/g2.jpg', '/g3.jpg', '/g4.jpg', '/g5.jpg', '/g6.jpg'];
    const groupOf = [1, 1, 1, 1, 2, 2, 2];
    const photos = paths.map(path => ({ path, filename: path, image_width: 4000, image_height: 3000, tags_list: [], persons: [] }));

    afterEach(() => {
      fixture?.destroy();
      fixture = null;
      vi.unstubAllGlobals();
    });

    function pin(opts: { groups?: boolean; marks?: boolean }): void {
      mockStore.photos.set(photos);
      mockStore.pinnedPaths.set(paths);
      mockStore.pinnedGroups.set(new Map(opts.groups === false ? [] : paths.map((p, i) => [p, groupOf[i]] as [string, number])));
      mockStore.pinnedMarks.set(new Map(opts.marks === false ? [] : paths.map((p, i) => [p, i % 2 ? 'remove' : 'keep'] as [string, 'keep' | 'remove'])));
      mockStore.hasReview.set(true);
      mockStore.reviewGroupCounts.set(opts.marks === false
        ? new Map()
        : new Map([[1, { count: 4, keep: 2, remove: 2 }], [2, { count: 3, keep: 2, remove: 1 }]]));
    }

    function render(mode: 'grid' | 'mosaic', virtual: boolean): HTMLElement {
      mockStore.config.set({ features: { show_rating_controls: true } });
      mockStore.galleryMode.set(mode);
      mockStore.virtualScroll.set(virtual);
      vi.stubGlobal('matchMedia', (media: string) => ({
        matches: true, media, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
      }));
      fixture = TestBed.createComponent(GalleryComponent);
      const instance = fixture.componentInstance as unknown as {
        desktop: { setup(): void };
        containerWidth: { set(v: number): void };
      };
      instance.desktop.setup();
      instance.containerWidth.set(1200);
      fixture.detectChanges();
      return fixture.nativeElement as HTMLElement;
    }

    const headers = (html: HTMLElement) => [...html.querySelectorAll('[role="heading"]')] as HTMLElement[];

    for (const [name, mode, virtual] of [
      ['virtual scroll off', 'grid', false],
      ['virtual scroll on', 'grid', true],
      ['mosaic', 'mosaic', false],
    ] as const) {
      it(`renders one header per group, every row and every card (${name})`, () => {
        pin({});
        const html = render(mode, virtual);
        expect(headers(html)).toHaveLength(2);
        expect(html.querySelectorAll('[role="heading"][aria-level]')).toHaveLength(2);
        expect(html.querySelector('[role="row"], [role="rowheader"]')).toBeNull();
        expect(html.querySelectorAll('app-photo-card')).toHaveLength(7);
        expect(headers(html)[0].textContent).toContain('gallery.pinned.review.group_header_plural');
      });
    }

    it('offers no filter links on any rendered card, tooltip or menu in a pinned grouped review, and restores them after the pin ends', () => {
      pin({});
      render('grid', false);
      const f = fixture!;
      const cards = () => f.debugElement.queryAll(By.directive(PhotoCardComponent)).map(c => c.componentInstance as PhotoCardComponent);
      const tips = () => f.debugElement.queryAll(By.directive(PhotoTooltipComponent)).map(t => t.componentInstance as PhotoTooltipComponent);
      const menu = () => f.debugElement.query(By.directive(GalleryPhotoMenuComponent)).componentInstance as GalleryPhotoMenuComponent;
      expect(cards()).toHaveLength(7);
      expect(cards().map(c => c.filterLinks())).toEqual(Array(7).fill(false));
      expect(tips().map(t => t.personLinks()).every(v => v === false)).toBe(true);
      expect(menu().findSimilar()).toBe(false);
      mockStore.pinnedPaths.set(null);
      mockStore.pinnedGroups.set(new Map());
      f.detectChanges();
      expect(cards().length).toBeGreaterThan(0);
      expect(cards().map(c => c.filterLinks()).every(v => v === true)).toBe(true);
      expect(tips().map(t => t.personLinks()).every(v => v === true)).toBe(true);
      expect(menu().findSimilar()).toBe(true);
    });

    it('feeds the header text from the effective counts', () => {
      pin({});
      mockI18n.t.mockImplementation((key: string, vars?: Record<string, unknown>) =>
        vars ? `${key} ${JSON.stringify(vars)}` : key);
      const html = render('grid', false);
      expect(headers(html)[1].textContent)
        .toContain('{"group":2,"count":3,"keep":2,"remove":1}');
    });

    it('updates the counts on a mark flip without rebuilding the rows', () => {
      pin({});
      const html = render('grid', false);
      const before = fixture!.componentInstance.rowsModel();
      mockStore.reviewGroupCounts.set(new Map([[1, { count: 4, keep: 1, remove: 3 }], [2, { count: 3, keep: 2, remove: 1 }]]));
      mockStore.userMarks.set(new Map([['/g0.jpg', 'remove']]));
      fixture!.detectChanges();
      expect(fixture!.componentInstance.rowsModel()).toBe(before);
      expect(headers(html)).toHaveLength(2);
    });

    it('counts photo rows only in aria-rowcount, not the group headings', () => {
      pin({});
      const html = render('grid', false);
      const rows = fixture!.componentInstance.rowsModel();
      expect(rows.length).toBe(5);
      expect(rows.filter(r => r.kind !== 'header').length).toBe(3);
      expect(html.querySelector('#gallery-rows-host')?.getAttribute('aria-rowcount')).toBe('3');
    });

    it('renders every card of a review taller than the window when virtual scroll is off (C30)', () => {
      const many = Array.from({ length: 60 }, (_, n) => `/m${n}.jpg`);
      mockStore.photos.set(many.map(path => ({ path, filename: path, image_width: 4000, image_height: 3000, tags_list: [], persons: [] })));
      mockStore.pinnedPaths.set(many);
      mockStore.pinnedGroups.set(new Map(many.map((p, i) => [p, i + 1] as [string, number])));
      mockStore.pinnedMarks.set(new Map());
      mockStore.hasReview.set(true);
      mockStore.reviewGroupCounts.set(new Map());
      const html = render('grid', false);
      const model = fixture!.componentInstance.rowsModel();
      expect(model[model.length - 1].offset).toBeGreaterThan(20000);
      expect(html.querySelectorAll('app-photo-card')).toHaveLength(60);
      expect(headers(html)).toHaveLength(60);
    });

    it('shows card details in the row branch when hide_details is off (C32)', () => {
      pin({});
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_details: false });
      const html = render('grid', false);
      const cards = [...html.querySelectorAll('app-photo-card')] as HTMLElement[];
      expect(cards).toHaveLength(7);
      expect(cards.every((card, i) => card.textContent?.includes(paths[i]))).toBe(true);
      mockStore.filters.set({ ...DEFAULT_FILTERS });
    });

    describe('first frame width', () => {
      function renderMeasured(width: number): ComponentFixture<GalleryComponent> {
        const host = document.createElement('mat-sidenav-content');
        // The box the ResizeObserver reports: the client width (no scrollbar) less the horizontal padding.
        Object.defineProperty(host, 'clientWidth', { value: width + 32 });
        host.style.paddingLeft = '16px';
        host.style.paddingRight = '16px';
        host.getBoundingClientRect = () => ({ width: width + 17, height: 600, top: 0, left: 0, right: width, bottom: 600, x: 0, y: 0, toJSON() { return {}; } });
        document.body.appendChild(host);
        vi.stubGlobal('ResizeObserver', class { observe() {} unobserve() {} disconnect() {} });
        vi.stubGlobal('matchMedia', (media: string) => ({
          matches: true, media, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {},
        }));
        mockStore.config.set({ features: { show_rating_controls: true } });
        mockStore.galleryMode.set('grid');
        mockStore.virtualScroll.set(false);
        fixture = TestBed.createComponent(GalleryComponent);
        fixture.detectChanges();
        TestBed.tick();
        return fixture;
      }

      afterEach(() => document.querySelectorAll('mat-sidenav-content').forEach(el => el.remove()));

      it('lays the first rowsModel out for the measured width, with no ResizeObserver tick', () => {
        pin({});
        const f = renderMeasured(800);
        const rows = f.componentInstance.rowsModel();
        expect(rows.length).toBeGreaterThan(0);
        const photoRows = rows.filter(r => r.kind !== 'header');
        expect(photoRows.length).toBeGreaterThan(0);
        for (const row of photoRows) {
          expect(row.widths.reduce((x, y) => x + y, 0)).toBeLessThanOrEqual(768);
        }
        expect((f.componentInstance as unknown as { containerWidth: () => number }).containerWidth()).toBe(800);
      });

      it('marks no group visited while the width is still 0', () => {
        pin({});
        mockStore.markGroupsVisited.mockClear();
        renderMeasured(0);
        expect(f_width()).toBe(0);
        expect(mockStore.markGroupsVisited).not.toHaveBeenCalled();
      });

      const f_width = () => (fixture!.componentInstance as unknown as { containerWidth: () => number }).containerWidth();
    });

    it('shows only the title when the pin has groups but no marks', () => {
      pin({ marks: false });
      mockStore.pinnedMarks.set(new Map());
      const html = render('grid', false);
      expect(headers(html)).toHaveLength(2);
      expect(headers(html)[0].textContent).toContain('gallery.pinned.review.group_title');
      expect(headers(html)[0].textContent).not.toContain('group_header');
    });

    it('renders no header for marks without groups and keeps the existing branch', () => {
      pin({ groups: false });
      const html = render('grid', false);
      expect(headers(html)).toHaveLength(0);
      expect(html.querySelector('#gallery-rows-host')).toBeNull();
      expect(html.querySelectorAll('app-photo-card')).toHaveLength(7);
    });

    it('renders a pin with no review at all as before', () => {
      mockStore.photos.set(photos);
      mockStore.hasReview.set(false);
      const html = render('grid', false);
      expect(headers(html)).toHaveLength(0);
    });

    it('builds rows with the real hide_details setting', () => {
      pin({});
      mockStore.filters.set({ ...DEFAULT_FILTERS, hide_details: false });
      render('grid', false);
      const photoRow = fixture!.componentInstance.rowsModel().find(r => r.kind !== 'header')!;
      const cellW = photoRow.widths[0];
      expect(photoRow.height).toBeGreaterThan(Math.round(cellW * 3 / 4));
      mockStore.filters.set({ ...DEFAULT_FILTERS });
    });

    describe('assistant context: labels, reasons, progress, group actions, copy', () => {
      interface Inst {
        viewportH: { set(v: number): void };
        relScrollTop: { set(v: number): void };
        rowsHostGap: { set(v: number): void };
        activeIndex: { (): number; set(v: number): void };
        onGridKeydown(e: KeyboardEvent): void;
      }
      const inst = () => fixture!.componentInstance as unknown as Inst;
      const actions = (html: HTMLElement) => [...html.querySelectorAll('[data-review-group-actions] button')] as HTMLButtonElement[];
      const echo = () => mockI18n.t.mockImplementation((key: string, vars?: Record<string, unknown>) =>
        vars ? `${key} ${JSON.stringify(vars)}` : key);

      beforeEach(() => {
        Element.prototype.scrollIntoView = vi.fn();
      });

      describe('group label', () => {
        it('appends the translated label after the counts, only on the group that has one', () => {
          pin({});
          echo();
          mockStore.pinnedLabels.set(new Map([[1, { key: 'bracket_span', params: { frames: 4, ev_span: 1.3 } }]]));
          const html = render('grid', false);
          expect(headers(html)[0].textContent).toContain('"remove":2}');
          expect(headers(html)[0].textContent).toContain(' · culling.group_reason.bracket_span {"frames":4,"ev_span":1.3}');
          expect(headers(html)[1].textContent).not.toContain('group_reason');
        });

        it('renders a header without any label exactly as before', () => {
          pin({});
          const html = render('grid', false);
          expect(headers(html)[0].textContent).not.toContain('· culling');
          expect(html.querySelector('[data-testid="review-group-label"]')).toBeNull();
        });

        it('shows a server-supplied moment as text, never as markup', () => {
          pin({});
          mockI18n.t.mockImplementation((key: string, vars?: Record<string, unknown>) =>
            key === 'culling.group_reason.moment' ? String(vars?.['moment']) : key);
          mockStore.pinnedLabels.set(new Map([[1, { key: 'moment', params: { moment: '<img src=x onerror=alert(1)>' } }]]));
          const html = render('grid', false);
          expect(html.querySelector('img[onerror]')).toBeNull();
          expect(html.querySelector('[data-testid="review-group-label"]')?.textContent).toContain('<img src=x onerror=alert(1)>');
        });
      });

      describe('reason on the strip', () => {
        it('feeds the card the reason of its own path', () => {
          pin({});
          mockI18n.t.mockImplementation((key: string, vars?: Record<string, unknown>) =>
            key.startsWith('culling.reason.') ? key : (vars ? `${key} ${JSON.stringify(vars)}` : key));
          mockStore.pinnedReasons.set(new Map([['/g1.jpg', { key: 'eyes_closed' }]]));
          const html = render('grid', false);
          const labels = [...html.querySelectorAll('app-photo-card button[aria-label]')].map(b => b.getAttribute('aria-label') ?? '');
          expect(labels.filter(l => l.includes('culling.reason.eyes_closed'))).toHaveLength(1);
        });
      });

      describe('visited groups', () => {
        it('marks only the groups whose header is inside the visible viewport, with no overscan', () => {
          pin({});
          const html = render('grid', false);
          void html;
          mockStore.markGroupsVisited.mockClear();
          inst().viewportH.set(50);
          fixture!.detectChanges();
          expect(mockStore.markGroupsVisited).toHaveBeenLastCalledWith([1]);
          const model = fixture!.componentInstance.rowsModel();
          const second = model.find(r => r.kind === 'header' && r.group === 2)!;
          mockStore.markGroupsVisited.mockClear();
          inst().relScrollTop.set(second.offset);
          fixture!.detectChanges();
          expect(mockStore.markGroupsVisited).toHaveBeenLastCalledWith([2]);
        });

        it('does not mark a group whose header lies under the strip above the rows host', () => {
          pin({});
          render('grid', false);
          const second = fixture!.componentInstance.rowsModel().find(r => r.kind === 'header' && r.group === 2)!;
          inst().relScrollTop.set(0);
          inst().rowsHostGap.set(0);
          inst().viewportH.set(second.offset + 10);
          fixture!.detectChanges();
          expect(mockStore.markGroupsVisited).toHaveBeenLastCalledWith([1, 2]);
          mockStore.markGroupsVisited.mockClear();
          inst().rowsHostGap.set(70);
          fixture!.detectChanges();
          expect(mockStore.markGroupsVisited).toHaveBeenLastCalledWith([1]);
        });

        it('marks the group of the photo the keyboard cursor lands on', () => {
          pin({});
          render('grid', false);
          mockStore.markGroupsVisited.mockClear();
          inst().activeIndex.set(3);
          const ev = new KeyboardEvent('keydown', { key: 'ArrowDown' });
          Object.defineProperty(ev, 'target', { value: null, configurable: true });
          inst().onGridKeydown(ev);
          expect(inst().activeIndex()).toBe(4);
          expect(mockStore.markGroupsVisited).toHaveBeenCalledWith([2]);
        });
      });

      describe('apply my marks', () => {
        const unit = (group: number, keep: string[], reject: string[], kind = 'burst') =>
          ({ group, kind, ungrouped: false, keep, reject, unreject: [] as string[] });
        const u1 = unit(1, ['/g0.jpg', '/g2.jpg'], ['/g1.jpg', '/g3.jpg']);
        const u2 = unit(2, ['/g4.jpg', '/g6.jpg'], ['/g5.jpg']);
        const byTest = (html: ParentNode, id: string) => [...html.querySelectorAll(`[data-testid="${id}"]`)] as HTMLButtonElement[];
        const strips = (html: HTMLElement) => [...html.querySelectorAll('app-photo-card button[class*="z-30"][class*="h-7"]')] as HTMLButtonElement[];
        const edition = (on = true) => { (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => on); };
        const planOf = (...units: (typeof u1)[]) => mockStore.applyPlan.set({
          units, byGroup: new Map(units.map(u => [u.group, u])),
          counts: { groups: units.length, reject: units.reduce((n, u) => n + u.reject.length, 0), unreject: 0 },
        });
        const fakeApply = () => mockStore.applyGroups.mockImplementation(async (units: (typeof u1)[]) => {
          for (const u of units) {
            const id = `r${u.group}`;
            const paths = [...u.keep, ...u.reject];
            mockStore.appliedGroups.update((m: Map<number, unknown>) => new Map(m).set(u.group, { receiptId: id, keptWhole: 0, unavailable: false }));
            mockStore.appliedReceiptList.update((l: unknown[]) => [...l, {
              receiptId: id, paths, group: u.group, kind: u.kind, label: null, firstFilename: `first-${u.group}.jpg`, skippedKeepWhole: [],
            }]);
            mockStore.appliedMarks.update((m: Map<string, unknown>) => new Map([...m, ...paths.map(p => [p, { mark: 'keep' as const, receiptId: id }] as const)]));
          }
          return true;
        });
        const dialogOpen = (confirmed: boolean) => {
          const dialog = (fixture!.componentInstance as unknown as { dialog: { open(...a: unknown[]): unknown } }).dialog;
          return vi.spyOn(dialog, 'open').mockReturnValue({ afterClosed: () => of(confirmed) } as never);
        };

        afterEach(() => {
          edition(false);
          mockStore.appliedMarks.set(new Map());
          mockStore.appliedGroups.set(new Map());
          mockStore.appliedReceiptList.set([]);
          mockStore.applying.set(false);
          planOf();
          mockStore.applyGroups.mockReset();
          mockStore.applyGroups.mockResolvedValue(true);
          mockStore.undoApplied.mockClear();
        });

        it('shows Apply per group and Apply my marks for edition users on a pin with marks, and nothing otherwise', () => {
          pin({});
          planOf(u1, u2);
          let html = render('grid', false);
          expect(byTest(html, 'review-apply-group')).toHaveLength(0);
          expect(byTest(html, 'apply-my-marks')).toHaveLength(0);
          fixture!.destroy();
          edition();
          html = render('grid', false);
          expect(byTest(html, 'review-apply-group')).toHaveLength(2);
          expect(byTest(html, 'apply-my-marks')).toHaveLength(1);
          fixture!.destroy();
          pin({ marks: false });
          planOf();
          html = render('grid', false);
          expect(byTest(html, 'review-apply-group')).toHaveLength(0);
          expect(byTest(html, 'apply-my-marks')).toHaveLength(0);
        });

        it('Apply on a group sends exactly that group\'s unit', () => {
          pin({});
          edition();
          planOf(u1, u2);
          const html = render('grid', false);
          byTest(html, 'review-apply-group')[1].click();
          expect(mockStore.applyGroups.mock.calls).toEqual([[[u2]]]);
        });

        it('disables Apply while a request is in flight', () => {
          pin({});
          edition();
          planOf(u1, u2);
          mockStore.applying.set(true);
          const html = render('grid', false);
          expect(byTest(html, 'review-apply-group').every(b => b.disabled)).toBe(true);
          expect(byTest(html, 'apply-my-marks')[0].disabled).toBe(true);
        });

        it('after Apply the row stays: Applied chip, a persistent Undo, locked mark buttons, and the kept-whole note', () => {
          pin({});
          echo();
          edition();
          planOf(u1, u2);
          const html = render('grid', false);
          fakeApply();
          mockStore.appliedGroups.set(new Map());
          byTest(html, 'review-apply-group')[0].click();
          mockStore.appliedGroups.update((m: Map<number, unknown>) => new Map(m).set(1, { receiptId: 'r1', keptWhole: 2, unavailable: false }));
          planOf(u2);
          fixture!.detectChanges();
          expect(headers(html)).toHaveLength(2);
          expect(byTest(html, 'review-applied-chip')).toHaveLength(1);
          expect(byTest(html, 'review-undo-group')).toHaveLength(1);
          expect(byTest(html, 'review-apply-group')).toHaveLength(1);
          expect(byTest(html, 'review-undo-group')[0].getAttribute('aria-label')).toBe('gallery.pinned.review.undo_apply_aria {"group":1}');
          expect(byTest(html, 'review-kept-whole-note')[0].textContent).toContain('gallery.pinned.review.kept_whole_note');
          const first = [...html.querySelectorAll('[data-review-group-actions]')][0];
          for (const mode of ['keep_all', 'keep_best', 'remove_all']) {
            expect(first.querySelector(`[data-mode="${mode}"]`)!.getAttribute('aria-disabled')).toBe('true');
          }
          byTest(html, 'review-undo-group')[0].click();
          expect(mockStore.undoApplied).toHaveBeenCalledWith('r1');
        });

        it('moves the focus from a group Apply to its Undo, and from the Undo back to the Apply', async () => {
          pin({});
          echo();
          edition();
          planOf(u1, u2);
          const html = render('grid', false);
          document.body.appendChild(html);
          try {
            fakeApply();
            const apply = byTest(html, 'review-apply-group')[0];
            apply.focus();
            expect(document.activeElement).toBe(apply);
            apply.click();
            await fixture!.whenStable();
            planOf(u2);
            fixture!.detectChanges();
            await fixture!.whenStable();
            const undo = byTest(html, 'review-undo-group')[0];
            expect(document.activeElement).toBe(undo);
            mockStore.undoApplied.mockImplementation(async () => {
              mockStore.appliedGroups.set(new Map());
              planOf(u1, u2);
            });
            undo.click();
            await fixture!.whenStable();
            fixture!.detectChanges();
            await fixture!.whenStable();
            expect(document.activeElement).toBe(byTest(html, 'review-apply-group')[0]);
            expect(byTest(html, 'review-apply-group')[0].closest('[data-review-group-actions]')!.getAttribute('data-group')).toBe('1');
          } finally {
            html.remove();
          }
        });

        it('moves the focus from Apply my marks to the Applied menu trigger', async () => {
          pin({});
          echo();
          edition();
          planOf(u1, u2);
          const html = render('grid', false);
          document.body.appendChild(html);
          try {
            dialogOpen(true);
            fakeApply();
            byTest(html, 'apply-my-marks')[0].focus();
            byTest(html, 'apply-my-marks')[0].click();
            for (let i = 0; i < 4; i += 1) {
              await fixture!.whenStable();
              fixture!.detectChanges();
            }
            expect(document.activeElement).toBe(byTest(html, 'applied-menu')[0]);
          } finally {
            html.remove();
          }
        });

        it('names an Applied menu entry by its group number, heading and first filename', () => {
          pin({});
          echo();
          edition();
          planOf(u1);
          const html = render('grid', false);
          mockStore.appliedReceiptList.set([{
            receiptId: 'r1', paths: ['/g0.jpg'], group: 1, kind: 'burst', label: { key: 'burst', params: { n: 2 } },
            firstFilename: 'IMG_0012.jpg', skippedKeepWhole: [],
          }]);
          fixture!.detectChanges();
          byTest(html, 'applied-menu')[0].click();
          fixture!.detectChanges();
          const item = document.body.querySelector('[data-testid="applied-menu-undo"]')!;
          expect(item.textContent).toContain('gallery.pinned.review.applied_menu_entry_titled');
          expect(item.textContent).toContain('"title":"gallery.pinned.review.group_title {\\"group\\":1}"');
        });

        it('keeps both Undo buttons when group 1 is applied and then group 2 (B3)', () => {
          pin({});
          edition();
          planOf(u1, u2);
          const html = render('grid', false);
          fakeApply();
          byTest(html, 'review-apply-group')[0].click();
          fixture!.detectChanges();
          byTest(html, 'review-apply-group')[0].click();
          fixture!.detectChanges();
          const undos = byTest(html, 'review-undo-group');
          expect(undos).toHaveLength(2);
          undos[0].click();
          undos[1].click();
          expect(mockStore.undoApplied.mock.calls).toEqual([['r1'], ['r2']]);
        });

        it('disables the Undo of a receipt the server no longer holds', () => {
          pin({});
          edition();
          mockStore.appliedGroups.set(new Map([[1, { receiptId: 'r1', keptWhole: 0, unavailable: true }]]));
          const html = render('grid', false);
          expect(byTest(html, 'review-undo-group')[0].getAttribute('aria-disabled')).toBe('true');
          byTest(html, 'review-undo-group')[0].click();
          expect(mockStore.undoApplied).not.toHaveBeenCalled();
        });

        for (const [name, mode, grouped] of [
          ['row instance (grouped review)', 'grid', true],
          ['grid instance', 'grid', false],
          ['mosaic instance', 'mosaic', false],
        ] as const) {
          it(`locks the Keep / Remove strip of applied photos on the ${name}, and only those`, () => {
            pin({ groups: grouped });
            edition();
            mockStore.appliedMarks.set(new Map([
              ['/g0.jpg', { mark: 'keep' as const, receiptId: 'r1' }],
              ['/g1.jpg', { mark: 'remove' as const, receiptId: 'r1' }],
            ]));
            const html = render(mode, false);
            const all = strips(html);
            expect(all).toHaveLength(7);
            const locked = all.filter(b => b.getAttribute('aria-disabled') === 'true');
            expect(locked).toHaveLength(2);
            const cards = [...html.querySelectorAll('app-photo-card')];
            expect(locked.map(b => cards.find(c => c.contains(b))!.getAttribute('data-pidx'))).toEqual(['0', '1']);
            locked[0].click();
            fixture!.detectChanges();
            expect(mockStore.setReviewMark).not.toHaveBeenCalled();
            expect(mockStore.userMarks().size).toBe(0);
          });
        }

        it('K and R fall through on an applied photo', () => {
          pin({});
          edition();
          mockStore.appliedMarks.set(new Map([['/g0.jpg', { mark: 'keep' as const, receiptId: 'r1' }]]));
          render('grid', false);
          mockStore.setReviewMark.mockClear();
          inst().activeIndex.set(0);
          const ev = new KeyboardEvent('keydown', { key: 'k', cancelable: true });
          Object.defineProperty(ev, 'target', { value: null, configurable: true });
          inst().onGridKeydown(ev);
          expect(mockStore.setReviewMark).not.toHaveBeenCalled();
          expect(ev.defaultPrevented).toBe(false);
          inst().activeIndex.set(1);
          const ev2 = new KeyboardEvent('keydown', { key: 'r', cancelable: true });
          Object.defineProperty(ev2, 'target', { value: null, configurable: true });
          inst().onGridKeydown(ev2);
          expect(mockStore.setReviewMark).toHaveBeenCalledWith('/g1.jpg', 'remove');
        });

        describe('Apply my marks', () => {
          it('names the three counts in a confirm dialog, and Cancel posts nothing', () => {
            pin({});
            echo();
            edition();
            planOf(u1, u2);
            mockStore.applyPlan.update((plan: Record<string, unknown>) => ({ ...plan, counts: { groups: 2, reject: 3, unreject: 1 } }));
            const html = render('grid', false);
            const open = dialogOpen(false);
            byTest(html, 'apply-my-marks')[0].click();
            expect(open).toHaveBeenCalledTimes(1);
            const data = (open.mock.calls[0][1] as { data: { title: string; message: string } }).data;
            expect(data.title).toBe('gallery.pinned.review.apply_all_title');
            expect(data.message).toBe('gallery.pinned.review.apply_all_confirm_plural {"reject":3,"unreject":1,"groups":2}');
            expect(mockStore.applyGroups).not.toHaveBeenCalled();
          });

          it('Confirm posts every appliable group once', async () => {
            pin({});
            edition();
            planOf(u1, u2);
            const html = render('grid', false);
            dialogOpen(true);
            byTest(html, 'apply-my-marks')[0].click();
            await vi.waitFor(() => expect(mockStore.applyGroups).toHaveBeenCalledTimes(1));
            expect(mockStore.applyGroups).toHaveBeenCalledWith([u1, u2]);
          });

          it('uses the singular wording for one group', () => {
            pin({});
            echo();
            edition();
            planOf(u1);
            const html = render('grid', false);
            const open = dialogOpen(false);
            byTest(html, 'apply-my-marks')[0].click();
            expect((open.mock.calls[0][1] as { data: { message: string } }).data.message)
              .toMatch(/^gallery\.pinned\.review\.apply_all_confirm \{/);
          });

          it('is disabled when nothing is left to apply', () => {
            pin({});
            edition();
            planOf();
            const html = render('grid', false);
            expect(byTest(html, 'apply-my-marks')[0].disabled).toBe(true);
          });

          it('is the only control of a marks-only pin: no group headers, no per-group Apply', () => {
            pin({ groups: false });
            edition();
            const only = { group: null, kind: null, ungrouped: true, keep: ['/g0.jpg'], reject: ['/g1.jpg'], unreject: [] as string[] };
            mockStore.applyPlan.set({ units: [only], byGroup: new Map(), counts: { groups: 1, reject: 1, unreject: 0 } });
            const html = render('grid', false);
            expect(headers(html)).toHaveLength(0);
            expect(byTest(html, 'review-apply-group')).toHaveLength(0);
            expect(byTest(html, 'apply-my-marks')).toHaveLength(1);
          });
        });

        describe('Applied menu', () => {
          const receipts = [
            { receiptId: 'r3', paths: ['/x.jpg'], group: 3, kind: 'burst', label: { key: 'burst', params: { n: 2 } }, firstFilename: 'IMG_0003.jpg', skippedKeepWhole: [] },
            { receiptId: 'r4', paths: ['/y.jpg'], group: 4, kind: 'similar', label: null, firstFilename: 'IMG_0004.jpg', skippedKeepWhole: [] },
          ];
          const open = (html: HTMLElement) => {
            byTest(html, 'applied-menu')[0].click();
            fixture!.detectChanges();
            return [...document.body.querySelectorAll('[data-testid="applied-menu-undo"]')] as HTMLButtonElement[];
          };

          it('still lists a group after a different pin replaced the list, labelled, and Undo from it calls the route (NEW-B1)', async () => {
            pin({});
            edition();
            echo();
            mockStore.appliedReceiptList.set(receipts);
            const html = render('grid', false);
            const items = open(html);
            await fixture!.whenStable();
            expect(byTest(html, 'applied-menu')[0].textContent).toContain('gallery.pinned.review.applied_menu_plural {"count":2}');
            expect(items).toHaveLength(2);
            expect(items[0].textContent).toContain('gallery.pinned.review.applied_menu_entry');
            expect(items[0].textContent).toContain('IMG_0003.jpg');
            expect(items[0].textContent).toContain('culling.group_reason.burst');
            expect(items[1].textContent).toContain('gallery.pinned.review.group_title');
            items[0].click();
            expect(mockStore.undoApplied).toHaveBeenCalledWith('r3');
          });

          it('is absent for a non-edition user and when there is no receipt', () => {
            pin({});
            mockStore.appliedReceiptList.set(receipts);
            let html = render('grid', false);
            expect(byTest(html, 'applied-menu')).toHaveLength(0);
            fixture!.destroy();
            edition();
            mockStore.appliedReceiptList.set([]);
            html = render('grid', false);
            expect(byTest(html, 'applied-menu')).toHaveLength(0);
          });
        });
      });

      describe('group actions', () => {
        it('renders three real buttons per header, each naming its group, that call setGroupMarks', () => {
          pin({});
          echo();
          const html = render('grid', false);
          const all = actions(html);
          expect(all).toHaveLength(6);
          expect(all.every(b => b.tagName === 'BUTTON' && b.getAttribute('type') === 'button')).toBe(true);
          expect(all[0].getAttribute('aria-label')).toBe('gallery.pinned.review.keep_all_aria {"group":1}');
          expect(all[1].getAttribute('aria-label')).toBe('gallery.pinned.review.keep_best_aria {"group":1}');
          expect(all[2].getAttribute('aria-label')).toBe('gallery.pinned.review.remove_all_aria {"group":1}');
          expect(all[3].getAttribute('aria-label')).toContain('"group":2');
          all[0].click();
          all[1].click();
          all[5].click();
          expect(mockStore.setGroupMarks.mock.calls).toEqual([[1, 'keep_all'], [1, 'keep_best'], [2, 'remove_all']]);
        });

        it('disables Keep best only and Remove all, and says why, for a keep-whole group', () => {
          pin({});
          echo();
          mockStore.pinnedKinds.set(new Map([[1, 'bracket'], [2, 'burst']]));
          const all = actions(render('grid', false));
          expect(all[0].disabled).toBe(false);
          expect(all[1].getAttribute('aria-disabled')).toBe('true');
          expect(all[2].getAttribute('aria-disabled')).toBe('true');
          expect(all[1].getAttribute('aria-description')).toBe('gallery.pinned.review.group_kept_whole');
          expect(all[2].getAttribute('aria-description')).toBe('gallery.pinned.review.group_kept_whole');
          expect(all[0].getAttribute('aria-description')).toBeNull();
          expect(all[3].disabled || all[4].disabled || all[5].disabled).toBe(false);
        });

        it('keeps the disabled keep-whole buttons focusable, carries the reason as tooltip and ignores clicks', () => {
          pin({});
          echo();
          mockStore.pinnedKinds.set(new Map([[1, 'bracket'], [2, 'burst']]));
          const html = render('grid', false);
          const all = actions(html);
          mockStore.setGroupMarks.mockClear();
          all[1].focus();
          expect(document.activeElement).toBe(all[1]);
          expect(all[1].disabled).toBe(false);
          expect(all[1].tabIndex).toBe(0);
          expect(all[1].getAttribute('aria-disabled')).toBe('true');
          all[1].click();
          all[2].click();
          expect(mockStore.setGroupMarks).not.toHaveBeenCalled();
          const tips = fixture!.debugElement.queryAll(By.directive(MatTooltip))
            .filter(d => d.nativeElement.closest('[data-review-group-actions]'))
            .map(d => ({ el: d.nativeElement as HTMLElement, message: d.injector.get(MatTooltip).message }));
          expect(tips.filter(t => t.message === 'gallery.pinned.review.group_kept_whole').map(t => t.el))
            .toEqual([all[1], all[2]]);
        });

        it('has no tooltip and no aria-disabled on the enabled buttons', () => {
          pin({});
          echo();
          mockStore.pinnedKinds.set(new Map([[1, 'burst'], [2, 'burst']]));
          const html = render('grid', false);
          const all = actions(html);
          expect(all.every(b => b.getAttribute('aria-disabled') === null)).toBe(true);
          const tips = fixture!.debugElement.queryAll(By.directive(MatTooltip))
            .filter(d => d.nativeElement.closest('[data-review-group-actions]'))
            .filter(d => d.injector.get(MatTooltip).message);
          expect(tips).toHaveLength(0);
        });

        it('offers no actions when the pin carries no marks', () => {
          pin({ marks: false });
          mockStore.pinnedMarks.set(new Map());
          const html = render('grid', false);
          expect(headers(html)).toHaveLength(2);
          expect(actions(html)).toHaveLength(0);
        });

        it('keeps the buttons in DOM order between the heading and the group cards', () => {
          pin({});
          const html = render('grid', false);
          const order = [...html.querySelectorAll('[role="heading"], [data-review-group-actions] button, app-photo-card')];
          const first = order.findIndex(el => el.tagName === 'BUTTON');
          expect(order[first - 1].getAttribute('role')).toBe('heading');
          expect(order.slice(first, first + 3).every(el => el.tagName === 'BUTTON')).toBe(true);
          expect(order[first + 3].tagName).toBe('APP-PHOTO-CARD');
          expect(html.querySelectorAll('[data-review-group-actions] button[tabindex="-1"]')).toHaveLength(0);
        });

        const fireOnButton = (button: HTMLElement, key: string): KeyboardEvent => {
          const ev = new KeyboardEvent('keydown', { key, bubbles: true, cancelable: true });
          button.dispatchEvent(ev);
          return ev;
        };

        it('lets K, R and the arrows pass while a header button has focus', () => {
          pin({});
          mockStore.photos.set(photos);
          mockStore.setReviewMark.mockClear();
          const html = render('grid', false);
          (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
          inst().activeIndex.set(1);
          const button = actions(html)[0];
          for (const key of ['k', 'r', 'K', 'ArrowDown', 'ArrowRight', 'Home', 'End']) {
            const ev = fireOnButton(button, key);
            expect(ev.defaultPrevented).toBe(false);
          }
          expect(mockStore.setReviewMark).not.toHaveBeenCalled();
          expect(inst().activeIndex()).toBe(1);
        });

        it('lets Space and Enter through to the native button', () => {
          pin({});
          const button = actions(render('grid', false))[2];
          expect(fireOnButton(button, ' ').defaultPrevented).toBe(false);
          expect(fireOnButton(button, 'Enter').defaultPrevented).toBe(false);
        });

        it('still handles K on a card of the same grid', () => {
          pin({});
          const html = render('grid', false);
          mockStore.pinnedMarks.set(new Map(paths.map((p, i) => [p, i % 2 ? 'remove' : 'keep'] as [string, 'keep' | 'remove'])));
          inst().activeIndex.set(1);
          const card = html.querySelector('app-photo-card') as HTMLElement;
          const ev = new KeyboardEvent('keydown', { key: 'k', bubbles: true, cancelable: true });
          card.dispatchEvent(ev);
          expect(mockStore.setReviewMark).toHaveBeenCalledWith('/g1.jpg', 'keep');
        });
      });

      describe('Copy for assistant', () => {
        const en = async (): Promise<(key: string, vars?: Record<string, unknown>) => string> => {
          const bundle = (await import('../../../../../i18n/translations/en.json')).default as Record<string, unknown>;
          return (key, vars = {}) => {
            const text = key.split('.').reduce<unknown>((node, part) => (node as Record<string, unknown>)?.[part], bundle) as string;
            return text.replace(/\{(\w+)\}/g, (_, name) => String(vars[name]));
          };
        };
        const copyButton = (html: HTMLElement) => html.querySelector('[data-testid="copy-for-assistant"]') as HTMLButtonElement | null;
        let writeText: Mock;
        let snackOpen: { mock: { calls: unknown[][] } };
        const setup = async (kinds: boolean) => {
          pin({});
          mockI18n.t.mockImplementation(await en());
          mockStore.reviewChanges.set({ changed: 3, keep: 2, remove: 1 });
          mockStore.review.set({ keep: [], remove: [], groups_total: 5, groups_visited: 4, groups_changed: 2 });
          mockStore.pinnedKinds.set(kinds ? new Map([[1, 'burst']]) : new Map());
          writeText = vi.fn(() => Promise.resolve());
          Object.defineProperty(navigator, 'clipboard', { value: { writeText }, configurable: true });
          const html = render('grid', false);
          // The component's own MatSnackBar (MatSnackBarModule re-provides it) would open a real bar here.
          snackOpen = vi.spyOn((fixture!.componentInstance as unknown as { snackBar: MatSnackBar }).snackBar, 'open')
            .mockReturnValue(undefined as never);
          return html;
        };
        let clipboardDescriptor: PropertyDescriptor | undefined;
        beforeEach(() => {
          clipboardDescriptor = Object.getOwnPropertyDescriptor(navigator, 'clipboard');
        });
        // Restore the original property: a leftover read-only `clipboard` breaks every later spec that assigns it.
        afterEach(() => {
          if (clipboardDescriptor) Object.defineProperty(navigator, 'clipboard', clipboardDescriptor);
          else delete (navigator as unknown as { clipboard?: unknown }).clipboard;
          delete (document as unknown as Record<string, unknown>)['execCommand'];
        });

        it('is offered with the review and not without one', () => {
          pin({});
          expect(copyButton(render('grid', false))).not.toBeNull();
          fixture!.destroy();
          mockStore.hasReview.set(false);
          mockStore.pinnedGroups.set(new Map());
          mockStore.pinnedMarks.set(new Map());
          mockStore.pinnedPaths.set(null);
          expect(copyButton(render('grid', false))).toBeNull();
        });

        it('copies the exact text of an auto_cull pin (it carries kinds)', async () => {
          const html = await setup(true);
          copyButton(html)!.click();
          await vi.waitFor(() => expect(writeText).toHaveBeenCalled());
          expect(writeText).toHaveBeenCalledWith(
            'I reviewed the photos in Facet: I changed 3 (2 keep, 1 remove), visited 4 of 5 groups. Apply auto_cull using my marks.');
          await vi.waitFor(() => expect(snackOpen.mock.calls).toEqual([['Copied', '', { duration: 2000 }]]));
        });

        it('copies the exact text of a plain pin, naming no tool', async () => {
          const html = await setup(false);
          copyButton(html)!.click();
          await vi.waitFor(() => expect(writeText).toHaveBeenCalled());
          expect(writeText).toHaveBeenCalledWith(
            'I reviewed the photos in Facet: I changed 3 (2 keep, 1 remove), visited 4 of 5 groups. Use my marks.');
        });

        it('labels applied groups and keeps the tail only while marks remain pending', async () => {
          const html = await setup(true);
          mockStore.review.set({ keep: [], remove: [], groups_total: 5, groups_visited: 4, groups_changed: 2, groups_applied: 2 } as never);
          mockStore.applyPlan.set({ units: [{ group: 3 }], byGroup: new Map(), counts: { groups: 1, reject: 0, unreject: 0 } });
          copyButton(html)!.click();
          await vi.waitFor(() => expect(writeText).toHaveBeenCalled());
          expect(writeText).toHaveBeenCalledWith(
            'I reviewed the photos in Facet: I changed 3 (2 keep, 1 remove), visited 4 of 5 groups and already applied 2 of them myself; leave those alone. Apply auto_cull using my marks.');
        });

        it('drops the tail when everything is applied', async () => {
          const html = await setup(true);
          mockStore.review.set({ keep: [], remove: [], groups_total: 5, groups_visited: 4, groups_changed: 2, groups_applied: 5 } as never);
          mockStore.applyPlan.set({ units: [], byGroup: new Map(), counts: { groups: 0, reject: 0, unreject: 0 } });
          copyButton(html)!.click();
          await vi.waitFor(() => expect(writeText).toHaveBeenCalled());
          expect(writeText).toHaveBeenCalledWith(
            'I reviewed the photos in Facet: I changed 3 (2 keep, 1 remove), visited 4 of 5 groups and already applied 5 of them myself; leave those alone.');
        });

        it('falls back to a hidden textarea and execCommand when navigator.clipboard is undefined', async () => {
          const html = await setup(false);
          Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
          let copied = '';
          const execCommand = vi.fn(() => {
            copied = (document.querySelector('textarea') as HTMLTextAreaElement).value;
            return true;
          });
          (document as unknown as Record<string, unknown>)['execCommand'] = execCommand;
          copyButton(html)!.click();
          await vi.waitFor(() => expect(execCommand).toHaveBeenCalledWith('copy'));
          expect(copied).toContain('Use my marks.');
          expect(document.querySelector('textarea')).toBeNull();
          await vi.waitFor(() => expect(snackOpen.mock.calls).toEqual([['Copied', '', { duration: 2000 }]]));
        });
      });
    });

    describe('keyboard', () => {
      const inst = () => fixture!.componentInstance as unknown as {
        activeIndex: { (): number; set(v: number): void };
        onGridKeydown(e: KeyboardEvent): void;
      };
      const pressOn = (key: string) => {
        const ev = new KeyboardEvent('keydown', { key });
        Object.defineProperty(ev, 'target', { value: null, configurable: true });
        inst().onGridKeydown(ev);
      };
      beforeEach(() => {
        pin({});
        render('grid', false);
        Element.prototype.scrollIntoView = vi.fn();
      });

      it('ArrowDown from the last photo of group 1 lands on the first row of group 2', () => {
        inst().activeIndex.set(3);
        pressOn('ArrowDown');
        expect(inst().activeIndex()).toBe(4);
      });

      it('ArrowUp from group 2 first row lands in group 1', () => {
        inst().activeIndex.set(4);
        pressOn('ArrowUp');
        expect(inst().activeIndex()).toBe(3);
      });

      it('ArrowDown within a group still steps one row', () => {
        inst().activeIndex.set(1);
        pressOn('ArrowDown');
        expect(inst().activeIndex()).toBe(3);
      });

      it('ArrowDown on the last row stays put', () => {
        inst().activeIndex.set(5);
        pressOn('ArrowDown');
        expect(inst().activeIndex()).toBe(5);
      });
    });
  });

  describe('review keys (K / R)', () => {
    function keyEvent(key: string, init: KeyboardEventInit = {}): KeyboardEvent {
      const ev = new KeyboardEvent('keydown', { key, cancelable: true, ...init });
      Object.defineProperty(ev, 'target', { value: null, configurable: true });
      return ev;
    }
    function fire(ev: KeyboardEvent): void {
      (component as unknown as { onGridKeydown(e: KeyboardEvent): void }).onGridKeydown(ev);
    }

    beforeEach(() => {
      mockStore.photos.set([{ path: '/a.jpg' }, { path: '/b.jpg' }, { path: '/c.jpg' }]);
      mockStore.config.set({ features: { show_rating_controls: true } });
      (mockAuth as { isEdition: unknown }).isEdition = vi.fn(() => true);
      mockStore.hasReview.set(true);
      mockStore.pinnedMarks.set(new Map([['/a.jpg', 'remove'], ['/b.jpg', 'keep']]));
      mockStore.userMarks.set(new Map());
      mockStore.setReviewMark.mockClear();
      mockStore.toggleRejected.mockClear();
      (component as unknown as { activeIndex: { set(v: number): void } }).activeIndex.set(0);
    });

    afterEach(() => {
      mockStore.hasReview.set(false);
      mockStore.pinnedMarks.set(new Map());
    });

    it('K sets keep on the marked cursor photo and advances', () => {
      const ev = keyEvent('k');
      fire(ev);
      expect(mockStore.setReviewMark).toHaveBeenCalledWith('/a.jpg', 'keep');
      expect(activeIndex()).toBe(1);
      expect(ev.defaultPrevented).toBe(true);
    });

    it('R sets remove and advances', () => {
      fire(keyEvent('R'));
      expect(mockStore.setReviewMark).toHaveBeenCalledWith('/a.jpg', 'remove');
      expect(activeIndex()).toBe(1);
    });

    it('does nothing on an unmarked photo and does not preventDefault', () => {
      (component as unknown as { activeIndex: { set(v: number): void } }).activeIndex.set(2);
      const ev = keyEvent('k');
      fire(ev);
      expect(mockStore.setReviewMark).not.toHaveBeenCalled();
      expect(ev.defaultPrevented).toBe(false);
      expect(activeIndex()).toBe(2);
    });

    it('does nothing without a review pin', () => {
      mockStore.hasReview.set(false);
      const ev = keyEvent('r');
      fire(ev);
      expect(mockStore.setReviewMark).not.toHaveBeenCalled();
      expect(ev.defaultPrevented).toBe(false);
    });

    it('uses the user mark over the assistant mark to decide the cursor photo is marked', () => {
      mockStore.pinnedMarks.set(new Map());
      mockStore.userMarks.set(new Map([['/a.jpg', 'keep']]));
      fire(keyEvent('r'));
      expect(mockStore.setReviewMark).toHaveBeenCalledWith('/a.jpg', 'remove');
    });

    it('X still rejects for real and never sets a review mark', () => {
      fire(keyEvent('x'));
      expect(mockStore.toggleRejected).toHaveBeenCalledWith('/a.jpg');
      expect(mockStore.setReviewMark).not.toHaveBeenCalled();
    });

    it('ignores Ctrl+K', () => {
      const ev = keyEvent('k', { ctrlKey: true });
      fire(ev);
      expect(mockStore.setReviewMark).not.toHaveBeenCalled();
      expect(ev.defaultPrevented).toBe(false);
    });

    it('does not advance past the last photo', () => {
      mockStore.pinnedMarks.set(new Map([['/c.jpg', 'keep']]));
      (component as unknown as { activeIndex: { set(v: number): void } }).activeIndex.set(2);
      fire(keyEvent('r'));
      expect(mockStore.setReviewMark).toHaveBeenCalledWith('/c.jpg', 'remove');
      expect(activeIndex()).toBe(2);
    });
  });
});
