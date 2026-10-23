import { Component } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatBottomSheet } from '@angular/material/bottom-sheet';
import { MatDialog } from '@angular/material/dialog';
import { ConnectAssistantDialogComponent } from '../../features/agent/connect-assistant-dialog.component';
import { PageContextService, registerOverlayForLifetime, registerPageContext } from './page-context.service';

@Component({ selector: 'app-probe', template: '' })
class ProbeComponent {
  constructor() {
    registerPageContext('probe', () => ({ search: 'x'.repeat(500), pair_a: 'p'.repeat(4096), list: [1], nested: { a: 1 }, n: 3, b: true, nothing: null }));
    registerOverlayForLifetime('slideshow');
  }
}

describe('PageContextService', () => {
  let openDialogs: { componentInstance: unknown }[];
  let sheet: { _openedBottomSheetRef: unknown };
  let service: PageContextService;

  beforeEach(() => {
    openDialogs = [];
    sheet = { _openedBottomSheetRef: null };
    TestBed.configureTestingModule({
      providers: [
        { provide: MatDialog, useValue: { get openDialogs() { return openDialogs; } } },
        { provide: MatBottomSheet, useValue: sheet },
      ],
    });
    service = TestBed.inject(PageContextService);
  });

  it('reports nothing when no page is registered', () => {
    expect(service.snapshot()).toBeNull();
    expect(service.overlays()).toEqual([]);
  });

  it('returns the id plus scalar state only, cutting free text but never a path', () => {
    service.register('probe', () => ({ search: 'x'.repeat(500), pair_a: 'p'.repeat(4096), list: [1], nested: { a: 1 }, n: 3, b: true, nothing: null }));
    const snapshot = service.snapshot();
    expect(Object.keys(snapshot ?? {}).sort()).toEqual(['b', 'id', 'n', 'nothing', 'pair_a', 'search']);
    expect(snapshot?.['search']).toBe('x'.repeat(200));
    expect(snapshot?.['pair_a']).toBe('p'.repeat(4096));
  });

  it('reads live on every snapshot', () => {
    let search = 'a';
    service.register('persons', () => ({ search }));
    expect(service.snapshot()?.['search']).toBe('a');
    search = 'b';
    expect(service.snapshot()?.['search']).toBe('b');
  });

  it('removes only the current registration', () => {
    const first = service.register('a', () => ({}));
    service.register('b', () => ({}));
    first();
    expect(service.snapshot()?.['id']).toBe('b');
  });

  it('degrades a throwing reader to the id', () => {
    service.register('compare', () => {
      throw new Error('not mounted');
    });
    expect(service.snapshot()).toEqual({ id: 'compare' });
  });

  it('reports a dialog of any type but the connect-assistant one', () => {
    openDialogs.push({ componentInstance: Object.create(ConnectAssistantDialogComponent.prototype) });
    expect(service.overlays()).toEqual([]);
    openDialogs.push({ componentInstance: {} });
    expect(service.overlays()).toEqual(['dialog']);
  });

  it('reports an open bottom sheet', () => {
    sheet._openedBottomSheetRef = {};
    expect(service.overlays()).toEqual(['bottom_sheet']);
  });

  it('reports a registered overlay until it is removed', () => {
    const remove = service.registerOverlay('slideshow');
    expect(service.overlays()).toEqual(['slideshow']);
    remove();
    expect(service.overlays()).toEqual([]);
  });

  it('registerPageContext and registerOverlayForLifetime clean up with the component', () => {
    const fixture = TestBed.createComponent(ProbeComponent);
    expect(service.snapshot()?.['id']).toBe('probe');
    expect(service.overlays()).toEqual(['slideshow']);
    fixture.destroy();
    expect(service.snapshot()).toBeNull();
    expect(service.overlays()).toEqual([]);
  });
});
