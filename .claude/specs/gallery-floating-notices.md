# Gallery advisory notices → floating bottom-right notifications

> Changed at user request 2026-10-23: the notices now float bottom-right (originally bottom-left); the right offset is measured to clear an open end drawer and the content scrollbar.

## Goal (locked by the user, 2026-10-23)
The gallery's advisory notices currently render as in-flow banners at the top of
`mat-sidenav-content` (`client/src/app/features/gallery/gallery.component.ts` ~227-247 and ~278-293):
- hidden-photos banner (`showHiddenBanner()`: "N photos hidden by current filters" + Show all) and its
  twin (`canRestoreHidden()`: "showing all" + Restore);
- RAW thumbnail-migration notice (`showRenderMigrationBanner()`: "N RAW photos still show a thumbnail
  from the previous rendering… python facet.py --refresh-thumbnails" + Dismiss).

They must become floating notifications at the BOTTOM-RIGHT, out of the layout flow:
- confined to the gallery content area: never over the filter drawer / docked side panel / details rail /
  side thumbnails when those are shown;
- stacked ABOVE the selection action bar (`[data-selection-bar]`, `fixed bottom-0`, wraps so its height
  varies) whenever it is visible (`selectionCount()`), with a small gap;
- NOT moved: set-scope chip, assistant pinned-list chip, album actions (they stay in flow at the top).

## Steps
1. Establish the scroll container and side regions (read the template + run the app): is
   `mat-sidenav-content` the element that scrolls (see ~2173 `document.querySelector('mat-sidenav-content')`)?
   Where do the docked panel (`panelPhoto`), details rail (`data-details-rail`) and filmstrip/side thumbnails
   render relative to it? → verify: note the answer in your report with line refs.
2. Remove the two banner blocks from the top flow; render the same content (same i18n keys, icons,
   buttons, handlers, `role="status"`) inside a single notification stack anchored bottom-right of the
   gallery content area. Default approach: a zero-height `sticky bottom-0` anchor as the last child of the
   scrolling content area with an `absolute` bottom-right column inside it (`pointer-events-none` on the
   anchor, `pointer-events-auto` on cards) — adapt if step 1 shows a different container. Cards: surface
   container colour, border, rounded, shadow, `max-w` so they never span the full width, newest/most
   important order: hidden notice first, migration notice below it (or a consistent order — state it).
   Tailwind utilities only, no custom CSS classes; no template method calls (signals/pipes only).
   → verify: browser screenshot — cards bottom-right, grid scrolls under them, top of grid no longer pushed down.
3. Selection-bar offset: measure the bar's height (ResizeObserver on `[data-selection-bar]` while it exists,
   cleaned up on destroy / when it disappears) into a signal; bind the stack's bottom offset to
   `gap + height` (e.g. `[style.bottom.px]`). → verify: select photos → stack rises above the bar; resize to a
   narrow width so the bar wraps → still above; clear selection → back down.
4. Confinement: with the filter drawer open (desktop `side` mode), the docked tooltip panel, and the details
   rail visible, the stack stays inside the grid area. On mobile (`over` drawer) it stays above any
   bottom bar/safe-area. → verify: screenshots for each state.
5. Tests: update/add `gallery.component.spec.ts` cases that assert the notices render (and the twin / dismiss
   behaviour) at their new location; keep assertions on behaviour, not pixel positions.
6. Docs: grep `docs/` (all 7 languages: docs/VIEWER.md + docs/<lang>/VIEWER.md) for any description of these
   banners' position ("banner", "at the top") and update it in all languages in the same change.

## Not changed
Notice conditions, wording, i18n keys, dismissal persistence, store logic, the other three banners.
