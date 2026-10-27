import { signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { I18nService } from '../../../core/services/i18n.service';
import { DEFAULT_KEYMAP } from '../../../core/services/keyboard-mapping.service';
import { ShortcutsDialogComponent } from './shortcuts-dialog.component';

describe('ShortcutsDialogComponent', () => {
  /** Each row as "label=keys", the label being the raw i18n key (the stub
   *  translates a key to itself), grouped by the section heading. */
  function rowsBySection(): Record<string, string[]> {
    // Some tests render the dialog twice in one test; reset keeps re-configure legal.
    TestBed.resetTestingModule();
    TestBed.configureTestingModule({
      imports: [ShortcutsDialogComponent],
      providers: [{ provide: I18nService, useValue: { translations: signal({}), t: (key: string) => key } }],
    });
    const fixture = TestBed.createComponent(ShortcutsDialogComponent);
    fixture.detectChanges();
    const result: Record<string, string[]> = {};
    for (const heading of Array.from((fixture.nativeElement as HTMLElement).querySelectorAll('h3'))) {
      const rows = Array.from(heading.nextElementSibling?.children ?? []);
      result[heading.textContent!.trim()] = rows.map(row => {
        const label = row.querySelector('span')!.textContent!.trim();
        const keys = Array.from(row.querySelectorAll('kbd')).map(k => k.textContent!.trim()).join(' ');
        return `${label}=${keys}`;
      });
    }
    return result;
  }

  it('lists the gallery view keys /, B and V', () => {
    expect(rowsBySection()['shortcuts.section_gallery']).toEqual(expect.arrayContaining([
      'shortcuts.focus_search=/',
      'shortcuts.toggle_filters=B',
      'shortcuts.toggle_layout=V',
    ]));
  });

  it('lists the photo page rating keys 1-5, 0/X and F', () => {
    expect(rowsBySection()['shortcuts.section_detail']).toEqual(expect.arrayContaining([
      'shortcuts.rate=1 – 5',
      'shortcuts.reject=0 X',
      'shortcuts.favorite=F',
    ]));
  });

  it('lists the keys in effect, not the defaults, once the user remapped one', () => {
    localStorage.setItem('facet_keymap', JSON.stringify({ ...DEFAULT_KEYMAP, reject: 'r' }));
    try {
      for (const section of ['shortcuts.section_gallery', 'shortcuts.section_detail']) {
        expect(rowsBySection()[section]).toEqual(expect.arrayContaining([
          'shortcuts.reject=0 R',
        ]));
      }
    } finally {
      localStorage.removeItem('facet_keymap');
    }
  });
});
