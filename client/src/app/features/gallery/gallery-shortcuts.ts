/** The gallery page's keyboard reference, shown in the help dialog. Mirrors
 *  the card hint chip and the grid/photo-page key handlers. */
export interface GalleryShortcutRow { keys: string[]; labelKey: string; }

export const GALLERY_HELP_SHORTCUT_SECTIONS: { titleKey: string; rows: GalleryShortcutRow[] }[] = [
  {
    titleKey: 'culling.shortcuts.page_title',
    rows: [
      { keys: ['1', '–', '5'], labelKey: 'gallery.shortcuts.rate' },
      { keys: ['F'], labelKey: 'gallery.shortcuts.favourite' },
      { keys: ['X'], labelKey: 'gallery.shortcuts.reject' },
      { keys: ['/'], labelKey: 'gallery.shortcuts.focus_search' },
      { keys: ['B'], labelKey: 'gallery.shortcuts.toggle_sidebar' },
      { keys: ['V'], labelKey: 'gallery.shortcuts.swap_layout' },
      { keys: ['Space'], labelKey: 'gallery.shortcuts.select' },
      { keys: ['Enter'], labelKey: 'culling.shortcuts.open' },
    ],
  },
];
