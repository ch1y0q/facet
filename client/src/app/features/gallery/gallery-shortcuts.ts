import { I18N } from '../../core/i18n/keys';

/** The gallery's keyboard reference. One table feeds both the `?` shortcuts
 *  dialog and the help dialog the user menu opens on the gallery routes, so
 *  the two can never list different keys. */
export interface GalleryShortcutRow { keys: string[]; labelKey: string; }

export const GALLERY_SHORTCUT_SECTION: { titleKey: string; rows: GalleryShortcutRow[] } = {
  titleKey: I18N.shortcuts.section_gallery,
  rows: [
    { keys: ['←', '→', '↑', '↓'], labelKey: I18N.shortcuts.navigate },
    { keys: ['Enter'], labelKey: I18N.shortcuts.open_detail },
    { keys: ['Space'], labelKey: I18N.shortcuts.toggle_select },
    { keys: ['Ctrl', 'A'], labelKey: I18N.shortcuts.select_all },
    { keys: ['1', '–', '5'], labelKey: I18N.shortcuts.rate },
    { keys: ['K'], labelKey: I18N.review.shortcut },
    { keys: ['0', 'X'], labelKey: I18N.shortcuts.reject },
    { keys: ['F'], labelKey: I18N.shortcuts.favorite },
    { keys: ['Esc'], labelKey: I18N.shortcuts.clear_selection },
    { keys: ['Shift', 'F10'], labelKey: I18N.shortcuts.context_menu },
    { keys: ['/'], labelKey: I18N.shortcuts.focus_search },
    { keys: ['B'], labelKey: I18N.shortcuts.toggle_filters },
    { keys: ['V'], labelKey: I18N.shortcuts.toggle_layout },
  ],
};
