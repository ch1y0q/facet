import { TestBed, ComponentFixture } from '@angular/core/testing';
import { signal } from '@angular/core';
import { I18nService } from '../../../core/services/i18n.service';
import { I18N } from '../../../core/i18n/keys';
import { DEFAULT_KEYMAP, KeyboardMappingService } from '../../../core/services/keyboard-mapping.service';
import { KeyboardMappingDialogComponent } from './keyboard-mapping-dialog.component';

describe('KeyboardMappingDialogComponent', () => {
  let fixture: ComponentFixture<KeyboardMappingDialogComponent>;

  /** The stub translates a key to itself, so assertions use the I18N constants. */
  function render(): HTMLElement {
    // The builder shares one jsdom window across spec files: never inherit a
    // mapping a previous file left behind.
    localStorage.removeItem('facet_keymap');
    TestBed.configureTestingModule({
      imports: [KeyboardMappingDialogComponent],
      providers: [
        { provide: I18nService, useValue: {
          translations: signal({}),
          t: (key: string) => key,
        } },
      ],
    });
    fixture = TestBed.createComponent(KeyboardMappingDialogComponent);
    fixture.detectChanges();
    return fixture.nativeElement as HTMLElement;
  }

  /** The remappable actions are the only stroked buttons; OK is flat, Reset raised. */
  const actionButtons = (root: HTMLElement): HTMLButtonElement[] =>
    Array.from(root.querySelectorAll<HTMLButtonElement>('button[mat-stroked-button]'));

  const press = (key: string, init: KeyboardEventInit = {}): void => {
    document.dispatchEvent(new KeyboardEvent('keydown', { key, ...init }));
    fixture.detectChanges();
  };

  afterEach(() => localStorage.removeItem('facet_keymap'));

  it('lists every remappable action with its current key', () => {
    const root = render();
    const buttons = actionButtons(root);
    expect(buttons.length).toBe(6);
    expect(buttons[0].textContent!.trim()).toBe(DEFAULT_KEYMAP.favourite.toUpperCase());
    expect(buttons[2].textContent!.trim()).toBe(DEFAULT_KEYMAP.keep.toUpperCase());
    expect(buttons.map(b => b.textContent!.trim())).toContain('/');
  });

  it('captures a pressed key into the clicked action and persists it', () => {
    const root = render();
    const service = TestBed.inject(KeyboardMappingService);
    actionButtons(root)[0].click();
    fixture.detectChanges();
    expect(actionButtons(root)[0].textContent).toContain(I18N.shortcuts.press_key);
    press('z');
    expect(actionButtons(root)[0].textContent!.trim()).toBe('Z');
    expect(service.key('favourite')).toBe('z');
    expect(JSON.parse(localStorage.getItem('facet_keymap')!).favourite).toBe('z');
  });

  it('stores an uppercase keystroke lowercased', () => {
    const root = render();
    const service = TestBed.inject(KeyboardMappingService);
    actionButtons(root)[1].click();
    press('R');
    expect(service.key('reject')).toBe('r');
  });

  it('backs out of capture on Escape and keeps the old binding', () => {
    const root = render();
    const service = TestBed.inject(KeyboardMappingService);
    actionButtons(root)[0].click();
    press('Escape');
    expect(actionButtons(root)[0].textContent!.trim()).toBe(DEFAULT_KEYMAP.favourite.toUpperCase());
    expect(service.key('favourite')).toBe(DEFAULT_KEYMAP.favourite);
  });

  it('stays armed through keys it cannot use, such as arrows and modifiers', () => {
    const root = render();
    actionButtons(root)[0].click();
    press('ArrowLeft');
    press('c', { ctrlKey: true });
    expect(actionButtons(root)[0].textContent).toContain(I18N.shortcuts.press_key);
    press('g');
    expect(actionButtons(root)[0].textContent!.trim()).toBe('G');
  });

  it('refuses a reserved key with an inline message and keeps the old binding', () => {
    const root = render();
    const service = TestBed.inject(KeyboardMappingService);
    actionButtons(root)[0].click();
    press('3');
    expect(root.textContent).toContain(I18N.shortcuts.key_reserved);
    expect(service.key('favourite')).toBe(DEFAULT_KEYMAP.favourite);
  });

  it('refuses a key another action already holds and keeps the old binding', () => {
    const root = render();
    const service = TestBed.inject(KeyboardMappingService);
    actionButtons(root)[0].click();
    press('x');
    expect(root.textContent).toContain(I18N.shortcuts.key_in_use);
    expect(service.key('favourite')).toBe(DEFAULT_KEYMAP.favourite);
    expect(service.key('reject')).toBe(DEFAULT_KEYMAP.reject);
  });

  it('enforces clashes against the live map, and frees a key when its holder moves', () => {
    const root = render();
    const service = TestBed.inject(KeyboardMappingService);
    // favourite <- q: no default holds q, allowed.
    actionButtons(root)[0].click();
    press('q');
    expect(service.key('favourite')).toBe('q');
    // reject <- q: favourite now holds q, refused.
    actionButtons(root)[1].click();
    press('q');
    expect(root.textContent).toContain(I18N.shortcuts.key_in_use);
    expect(service.key('reject')).toBe(DEFAULT_KEYMAP.reject);
    // favourite <- w releases q; swap layout then takes q.
    actionButtons(root)[0].click();
    press('w');
    expect(service.key('favourite')).toBe('w');
    actionButtons(root)[5].click();
    press('q');
    expect(service.key('swapLayout')).toBe('q');
  });

  it('reset all restores every default', () => {
    const root = render();
    const service = TestBed.inject(KeyboardMappingService);
    actionButtons(root)[0].click();
    press('z');
    root.querySelector<HTMLButtonElement>('button[mat-button]')!.click();
    fixture.detectChanges();
    expect(service.keymap()).toEqual(DEFAULT_KEYMAP);
    expect(actionButtons(root)[0].textContent!.trim()).toBe(DEFAULT_KEYMAP.favourite.toUpperCase());
  });
});
