# Spec: Gallery selection bar as a floating, icon-only card (bottom-left)

Symbols, not line numbers, are referenced: `gallery.component.ts` is concurrently edited by another builder (album feature).

## Objective + success criteria
- The selection bar is a floating card inside the gallery's `#noticeHost` (the `relative h-full` wrapper around `mat-sidenav-container`), anchored bottom-left with a 16px margin (8px below `md`), rounded, `shadow-lg`, `bg-[var(--mat-sys-surface-container)]`, full outline. It is `absolute`, not `fixed`, so it never leaves the gallery content box and never overlaps the right-hand end drawer / details rail.
- Its right edge is capped by the same measured inset the notices use (`noticeRightPx()` = drawer/scrollbar gap + margin), so with the drawer open (desktop `side` mode) it wraps instead of running under the drawer.
- Every action is a `mat-icon-button` with `[matTooltip]` and `[attr.aria-label]` driven by the SAME existing i18n keys. No new keys, except where an existing key cannot serve (none identified; see Open questions). The old `md:!hidden` / `!hidden md:!inline-flex` duplicate pairs collapse to one button each.
- The "N selected" text (`data-selection-status`) stays. Clear becomes an icon button.
- Mobile (`< md`, the `isDesktop()` breakpoint): same card, bottom margin 8px; actions collapse into the existing single "Actions" trigger (`openActionsSheet`) shown as an icon button (`more_horiz`) with tooltip/aria-label `gallery.selection.actions`.
- Advisory notices (bottom-right) lift above the bar ONLY when the two boxes overlap horizontally; otherwise both rest on the same bottom margin. The rule is a pure function, unit-tested.
- The grid's end spacer (`<div aria-hidden class="h-40">` under `@if (selectionCount())`) is sized from the measured card height + margin so the last row is never hidden.
- The card is gated `@if (selectionCount() && !overDrawerOpen())` like the notices (selection persists; the card hides while the mobile `over` drawer is open), because Material's `.mat-drawer-container` is `z-index:1; position:relative` and a `z-20` sibling would paint over that drawer.
- On mobile with a selection the card bottom equals viewport bottom minus 8px: `app.html`'s `<main [class.pb-14]=...>` no longer keeps 56px padding while the bottom nav is hidden by `mobileGalleryBarVisible`.
- Every icon button has `disabledInteractive` so tooltips show on disabled buttons (delete when view-scoped, download/actions while downloading).
- One breakpoint everywhere: `isDesktop()` (md, 768px) -> `md:` classes; margin = `isDesktop() ? 16 : 8` for the card AND the notices (shared baseline). Notices' base bottom therefore goes 8 -> 16 on desktop even without a selection: an intended change, tested.
- The UI is correct at every breakpoint actually in effect (inventory + matrix, steps 8-9); defects found are fixed in the same change.
- Docs updated (EN + 6 translations) where the bar's look or position is described.
- Gates: vitest, `tsc` x2, `ng lint` clean.

## Files to create / change
- `client/src/app/features/gallery/gallery.component.ts` — selection bar template (move inside `#noticeHost`, new classes, icon-only buttons), `trackSelectionBar` / `selectionBarOverlap` / `noticeBottomPx` rework, end spacer sizing.
- `client/src/app/features/gallery/selection-bar-layout.util.ts` (new, tiny) — pure `noticeLiftPx(...)` function (testable without a DOM).
- `client/src/app/features/gallery/selection-bar-layout.util.spec.ts` (new) — unit tests for the lift rule.
- `client/src/app/features/gallery/gallery.component.spec.ts` — new describe for the bar (aria-label/tooltip reachability, placement), keep existing `data-selection-bar` stand-in tests unchanged.
- `client/src/app/app.html` (+ `app.ts` only if a shared `mobileBottomNavVisible` computed is extracted) — `<main [class.pb-14]>` applies only while the mobile bottom nav is actually shown.
- `client/src/app/shared/components/photo-card/photo-card.component.ts` — `scroll-mb-28` assumed the old single-row bar; raise to cover a 3-row card (start at `scroll-mb-44`, confirm against the measured worst case) and rewrite its comment.
- `docs/VIEWER.md`, `docs/{fr,de,it,es,pt,zh}/VIEWER.md` — the "Show what's hidden" bullet ("above the selection bar when photos are selected") and the "## Mobile" paragraph; add a one-line description of the floating icon bar where the selection bar is first described.
- NOT changed: `i18n/translations/*.json` (no new keys), `gallery-actions-sheet.component.ts`.

## Other users of the markup (audited)
- `grep data-selection-bar` hits only `gallery.component.ts` (template + focus-out guard `onGridFocusOut`, which uses `closest('[data-selection-bar]')` — keep the attribute) and its spec.
- `shared-view.component.ts` has its own three `fixed bottom-0` bars (different markup, public share page); `manage-persons.component.ts` has its own selection UI; `app.html` has a separate mobile bottom bar. None share this markup. Decision: change the gallery only.

## Open questions / risks
- Icon-only controls need an existing label: favorite, reject, rate, copy_filenames, edit_tags, `export.action`, `cull.action`, `cull.delete_action`, `gallery.selection.download` / `photo_detail.downloading`, `albums.add_photos`, `gallery.selection.mark_sequence` all exist (they are the current text labels). The Rate menu's items are stars and reuse `gallery.selection.clear`; unchanged.
- Placement inside `#noticeHost`: the host is the `h-full` box that the router outlet gives the gallery. Verify in the browser that its bottom is the viewport bottom on desktop and that on mobile it is the viewport bottom too (bottom bar hidden during selection, per `mobileGalleryBarVisible`). If the host stops above something on mobile, the 8px margin still holds relative to the host; confirm there is no safe-area gap on iOS (`max-md:mb-[max(0.5rem,env(safe-area-inset-bottom))]` keeps the existing safe-area behaviour).
- `z-index`: the card was `z-50` fixed over everything; inside the host it must still sit above the sidenav content and below dialogs/overlays (`cdk-overlay-container` is higher). Use `z-20` (above notices `z-10`); verify the mobile `over` drawer (z-index in its own stacking context) still covers the card — acceptable and arguably desired, the notices already step aside there via `overDrawerOpen()`; the card does NOT hide.
- Menus (`mat-menu`) anchor to their trigger and open upward-flip automatically; confirm they are not clipped (overlay container is global, expected fine).
- Existing specs/tests (any in the repo) that locate bar buttons by visible text (`textContent.includes(label)`) will break once labels become aria-only. Builder must grep `gallery.component.spec.ts` and `ui-tool-handlers.spec.ts` for such lookups and switch them to `[aria-label]` queries.
- Another builder edits `gallery.component.ts` (album feature, possibly touching the album menu in this same bar via `albumOptions` / `createAlbumAndAdd`). Re-read the template block immediately before editing; do not revert their hunks; coordinate if the album trigger markup changed.

## Steps
1. Pure lift rule + its unit tests.
   - description: add `noticeLiftPx({ hostBottom, barLeft, barRight, barTop, noticeLeft, noticeRight })` returning the px the notices must rise. The notice box is the MEASURED `getBoundingClientRect()` of `[data-gallery-notices]` (no duplicated width formula; when the stack is absent the lift is 0). If the intervals (bar vs notice, bar measured relative to the host's left) do not intersect, return 0; else return `max(0, ceil(hostBottom - barTop))` (distance from the host bottom up to the card top, which already includes the card's own bottom margin).
   - key decision: horizontal-overlap gating vs always lifting. Gating keeps both on the bottom margin when the card is narrow (few actions) and the notice sits clear on the right.
   - default: gate on strict interval intersection with a 0px gutter (touching edges = no overlap); lift value includes nothing extra, the notices' own base gap (step 3) supplies the 8px breathing room.
   - verify: new spec cases — card at left, narrow (right=300) in a 1200 host, notice rect left=768,right=1184: returns 0; card spanning (right=1000): returns `hostBottom - barTop`; touching edges (barRight == noticeLeft): 0; mobile 400 host (notice rect 8..392, bar full width): lifts; barTop > hostBottom: 0.
   - affected files: `selection-bar-layout.util.ts`, `selection-bar-layout.util.spec.ts`.
2. Template: move the bar inside `#noticeHost`, restyle as a floating card.
   - description: relocate the `@if (selectionCount())` block from the component root into the `#noticeHost` div (after `</mat-sidenav-container>`, before/after the notices block). Replace the classes with: `absolute bottom-2 md:bottom-4 left-2 md:left-4 z-20 (inside `@if (selectionCount() && !overDrawerOpen())`) w-fit flex flex-wrap items-center gap-1 px-2 py-1 rounded-2xl bg-[var(--mat-sys-surface-container)] border border-[var(--mat-sys-outline-variant)] shadow-lg max-md:mb-[env(safe-area-inset-bottom)]` plus `[style.right.px]="noticeRightPx()"` so the available width ends at the content area's visible right edge minus margin (the shrink-to-fit width then wraps rather than overflows). Keep `#selectionBar` and `data-selection-bar`. Keep the `offerWholeView()` row as a `w-full` first row.
   - key decision: `absolute` in the host (follows the content box, avoids the drawer) vs `fixed` with computed offsets (needs resize tracking, can overlap the drawer on the right).
   - default: `absolute` in `#noticeHost`; reuses the already-measured `noticeRightPx` so no new measurement for the cap.
   - verify: browser — desktop, selection of 3 photos: card is bottom-left with 16px gap on left/bottom (get_css_styles / rect vs host), no full-width strip; open filter drawer (side mode): card right edge <= drawer left - 16, resize narrower to confirm it wraps instead of hiding under the drawer. Vitest — with `overDrawerOpen` true (mobile, drawer open) the card is absent while `selectionCount()` is unchanged, and returns when closed. Vitest — `html.querySelector('[data-selection-bar]')` is inside the `#noticeHost` wrapper, has `absolute` and `rounded-2xl` classes, and no `fixed` class.
   - affected files: `gallery.component.ts`.
3. Icon-only buttons with tooltip + aria-label.
   - description: for each existing action emit one `<button mat-icon-button [matTooltip]="KEY | translate" [attr.aria-label]="KEY | translate">` with the same icon as today: clear `close`, select all `select_all` (still `@if (!allLoadedSelected())`), invert `flip`, compare `compare` (`@if (canCompareSelection())`), favorite `favorite`, reject `thumb_down`, rate `star` (menu trigger `rateMenu`), add to album `photo_library` (`albumMenu`), mark sequence `panorama_photosphere` (`sequenceMenu`), copy `content_copy`, edit tags `sell`, export `drive_file_move`, cull `folder_move`, delete `delete` (tooltip keeps the existing view-scoped ternary: disabled -> `cull.delete_disabled_view_scope_tooltip`, else `cull.delete_action`; aria-label always `cull.delete_action`), download `download` (menu trigger `dlMenu` when profiles exist, else direct; tooltip/aria `downloading() ? photo_detail.downloading : gallery.selection.download`; spinner replaces the icon while downloading). Desktop-only group gets `max-md:hidden`; mobile shows clear, select all, invert, compare, then one Actions icon button (`more_horiz`, tooltip/aria `gallery.selection.actions`, `(click)="openActionsSheet()"`, `[disabled]="downloading()"`, spinner while downloading). Insert thin dividers between groups (`<span aria-hidden="true" class="w-px h-6 mx-1 bg-[var(--mat-sys-outline-variant)]"></span>`): selection tools | edit actions | file actions. Every button carries `disabledInteractive`. Preserve DOM order so keyboard tab order is unchanged; all `(click)` handlers, `@if` guards (`auth.isEdition()`, `show_albums`, `trash_available`, `downloadProfiles().length`) and menu templates unchanged.
   - key decision: how to keep the dense desktop set legible without text. Icons + tooltip + group dividers; do not add a "more" overflow on desktop (locked: every action stays one click).
   - default: no text anywhere except the count; delete icon tinted with `text-[var(--mat-sys-error)]`? NO — keep neutral to avoid a new styling decision; destructive confirmation already exists in `deleteSelected()`.
   - verify: vitest (assert `disabledInteractive` on delete and download; select 2 photos, `auth.isEdition` true, `downloadProfiles` empty, `trash_available` true): for each i18n key (selection.clear, select_all, invert, favorite, reject, rate, albums.add_photos, selection.mark_sequence, copy_filenames, edit_tags, export.action, cull.action, cull.delete_action, selection.download) `bar.querySelector('button[aria-label="<translated>"]')` exists, is a `mat-icon-button` (`mat-mdc-icon-button` class), and has `matTooltip` set (read `ng-reflect`-free: assert via `MatTooltip` directive `debugElement.injector.get(MatTooltip).message` equals the label). Clicking favorite/reject/copy calls the same component methods as before. A non-edition run omits the edit/file actions. No button in the bar has visible text content other than mat-icon glyphs (`textContent.trim()` of each button is a ligature name or empty). `viewScoped` true -> delete disabled and tooltip is the disabled text.
   - affected files: `gallery.component.ts`, `gallery.component.spec.ts`.
4. Notice lift rework and end-spacer sizing.
   - description: in `trackSelectionBar` the measure callback computes `selectionBarOverlap` via `noticeLiftPx` using `host.getBoundingClientRect()`, `bar.getBoundingClientRect()` (bar x-coordinates made relative to host.left), and the current `noticeRightPx()`; also set a new `selectionBarReservePx` signal = `ceil(host.bottom - bar.top)` (card height plus margin; used by the spacer). `noticeBottomPx` becomes `margin + overlap` where `margin = isDesktop() ? 16 : 8` (the same as the card's bottom margin so both rest on one baseline). The lift already reaches the card top, so `bottom = overlap + margin` leaves a `margin` gap above the card. This also moves the notices' resting bottom from 8 to 16 on desktop with no selection (intended; assert it). Observe `bar`, `host` and the content element (`scrollContent`) so a drawer opening (which changes `noticeRightPx` and the card's wrap) re-measures; also re-run when `noticeRightPx` changes (read it inside the effect). Replace the fixed `h-40` spacer by `[style.height.px]="selectionBarReservePx()"` with a floor (`Math.max(reserve, 112)` at write time, not in the template) and keep `aria-hidden`. Update the doc comments on `selectionBarOverlap` / `noticeBottomPx` ("fixed selection bar" wording is now false).
   - key decision: measure vs hard-code the spacer. Measured, because the card height varies 1-3 rows with the drawer state; a hard-coded value either wastes space or hides the last row.
   - default: spacer height = measured bar height + margin (floor 112px); notices margin follows the breakpoint.
   - verify: vitest — with ResizeObserver stubbed and `getBoundingClientRect` mocked on host/bar, assert `noticeBottomPx()` equals `16` when the card is narrow (no overlap) and `16 + (hostBottom - barTop)` when wide (desktop), and `8`-based on mobile; assert the spacer element's `style.height` equals the mocked reserve (>= 112), and that with no selection `noticeBottomPx()` is 16 on desktop / 8 on mobile. Browser — select the LAST row's photo with the keyboard: the focused card is fully visible above a 3-row card (scroll margin in photo-card). Browser — select photos, scroll to the end: the last grid row is fully above the card; with the hidden-photos notice visible and the card narrow (few actions as a non-edition user) both sit on the same bottom line; with the edition card wide enough to reach the notice, the notice sits above the card with an 8-16px gap and is not covered.
   - affected files: `gallery.component.ts`, `gallery.component.spec.ts`.
5. Docs, EN then six translations.
   - description: `docs/VIEWER.md` — "Show what's hidden" bullet: "above the selection bar when photos are selected" -> "(and above the floating selection card only when the two would overlap)"; "## Mobile": the bar is now a floating card (same on mobile) whose bulk operations collapse into one Actions icon button opening the bottom sheet; add one sentence where the selection bar is first described (grep "selection bar" at the Bulk editing bullet) stating it is a floating bottom-left card with icon-only buttons (hover for the label). Mirror the same edits in `docs/fr|de|it|es|pt|zh/VIEWER.md`, using `i18n/translations/<lang>.json` terms for the action names (glossary rule).
   - key decision: how much prose. Minimal: only sentences made false or newly needed.
   - default: three small edits per file.
   - verify: `scripts/docs_parity.py` / `docs_xlinks.py` do NOT exist; instead grep `docs/VIEWER.md` and the six translations: no remaining "above the selection bar" phrase (or its translation); the Multi-Select "Action bar appears..." line and the "## Mobile" single-Actions-button paragraph are each updated in all 7 languages.
   - affected files: `docs/VIEWER.md`, `docs/fr/VIEWER.md`, `docs/de/VIEWER.md`, `docs/it/VIEWER.md`, `docs/es/VIEWER.md`, `docs/pt/VIEWER.md`, `docs/zh/VIEWER.md`.
6. Mobile bottom padding in the app shell.
   - description: `app.html` `<main [class.pb-14]="isGalleryRoute() || ...">` keeps 56px padding for the bottom nav; during a selection `mobileGalleryBarVisible` hides the nav, so the card would float 64px up. Apply `pb-14` only while the nav is actually visible (reuse the nav's own show condition; extract a computed in `app.ts` if duplicated). Audit every route that triggers `pb-14` so they are unchanged when their nav shows.
   - key decision: change the shell padding vs offset the card by 56px. Shell padding, so the card's math stays margin-only.
   - default: padding conditional on nav visibility.
   - verify: browser at 400px with a selection: card bottom = viewport bottom - 8px; without a selection the nav and padding are as before on each pb-14 route.
   - affected files: `client/src/app/app.html`, `client/src/app/app.ts`.
7. Existing specs adapted.
   - description: adapt `gallery.component.spec.ts` helpers that find bar buttons by text (`deleteButton`, `tagsButton`) to `[aria-label]` lookups, and the `tagsButton` "is a desktop-only button" test (asserts `!hidden` / `lg:!inline-flex`) to the new visibility classes (`max-md:hidden`). The builder lists every touched test in its report as ADAPTED (same assertion, new locator) or ASSERTION-CHANGED (different claim, with reason).
   - key decision: none beyond disclosure.
   - default: grep `textContent.includes`, `lg:!`, `!hidden` in the gallery specs and `ui-tool-handlers.spec.ts` first.
   - verify: vitest green; the disclosure list is present.
   - affected files: `gallery.component.spec.ts` (and any other spec the grep finds).
8. Breakpoint inventory.
   - description: record, in the builder's report, every breakpoint in effect for the gallery. Known: Tailwind defaults sm 640 / md 768 / lg 1024 / xl 1280 / 2xl 1536 (grep the client styles, any `@theme` block and tailwind config for custom ones; none expected); `useDesktopSignal` default = md 768 (`isDesktop()`, drives side vs over drawer, margins, mosaic); `DETAILS_RAIL_MIN_WIDTH_PX = 1280` (`railWide`, details rail / `panelMode`) in `shared/utils/media-query.ts`; `(hover: none)` and `(hover: none) and (pointer: coarse)` matchMedia (touch tooltip behaviour); `gridColumnCount(..., isDesktop)` in `gallery-rows.util.ts`; photo-tooltip size thresholds and `sm:`/`md:`/`lg:`/`xl:`/`2xl:`/`max-` classes in `gallery.component.ts`, `app.html`, `photo-card.component.ts`. The union of these values defines the matrix columns in step 9.
   - key decision: derive the matrix from the grep, not from this list; any extra threshold found is added.
   - default: boundaries to test = 639/640, 767/768, 1023/1024, 1279/1280, 1535/1536 plus 375 and 2520.
   - verify: the inventory table exists in the report and each threshold maps to a matrix column.
   - affected files: none (read-only grep).
9. Browser verification matrix (Chrome DevTools MCP, rebuild Angular first).
   - description: at each width W in {375, 639, 640, 767, 768, 1023, 1024, 1279, 1280, 1535, 1536, 2520} check: selection bar with 0 / 1 / many selected, the view-scope offer row (`offerWholeView`), and wrap; floating notices with and without a selection (lift rule: wide edition card lifts, narrow card does not); end drawer closed and open (side vs over per md), details rail at >=1280; the photo tooltip near the bottom and right edges (docked rail vs floating).
   - key decision: defects found are fixed in this same change rather than logged.
   - default: use `resize_page` and `get_css_styles` / rects; record a pass/fail line per cell.
   - verify: per cell, nothing clipped or off-screen, no overlap between bar / notices / drawer, no horizontal page scrollbar (`document.documentElement.scrollWidth <= innerWidth`), last grid row reachable above the bar.
   - affected files: `gallery.component.ts` and others only if a defect is fixed.
10. Browser pass and gates.
   - description: run the viewer, exercise all layouts (see final gate). No code unless a defect is found.
   - key decision: none (verification step; merge into the gate if the builder prefers).
   - default: Chrome DevTools MCP per the project's preference, including the 400px checks for the open `over` drawer (card hidden) and the card bottom = viewport bottom - 8px, scratch DB per `project_local_viewer_browser_testing`.
   - verify: the checks listed in the gate below.
   - affected files: none.

## Final verification gate
- `cd client && npm run test` (vitest, at most 2 workers): new suites green; no existing suite regressed (grep for text-based bar lookups first).
- `cd client && npx tsc --noEmit -p tsconfig.app.json && npx tsc --noEmit -p tsconfig.spec.json` (both leaf projects; check exit codes, no pipe).
- `cd client && npx ng lint` clean.
- No custom CSS, no component-method calls added in the template (only signals / pipes / the existing `translate` pipe; the delete tooltip ternary uses signals and pipes only).
- Browser (Chrome DevTools MCP, rebuild Angular first):
  - Desktop 1440px, drawer closed: card bottom-left 16px margin, rounded, shadow; icons have tooltips on hover; every control reachable by Tab in the old order; Ctrl+A still selects all.
  - Desktop, filter drawer open (side mode) and details rail open: card right edge never beyond the content area's right edge minus 16px; wraps to a second row when squeezed (resize to ~900px with drawer open); notices (hidden-photos banner) remain visible and uncovered.
  - Notice/lift rule: wide edition card + hidden banner -> notice above the card; non-edition (short card) + banner -> same baseline, no lift.
  - Mobile 400px: card with 8px margin, count + clear/select-all/invert + Actions icon; tapping Actions opens the bottom sheet; the route's bottom bar is not visible during selection; no horizontal page overflow; narrow card wraps to 2 rows without clipping.
  - Scroll to the last row with a selection: fully visible above the card.
  - Open a `mat-menu` (rate, download) from the card: opens unclipped.
- Docs grep check from step 5 passes in all 7 languages.

## Adversarial review
- B1 (accepted): `.mat-drawer-container` is `z-index:1`, `position:relative`, so a `z-20` card would paint over the mobile `over` drawer. Decision: gate with `!overDrawerOpen()` like the notices; vitest case added (step 2).
- B2 (accepted): `app.html` `<main [class.pb-14]>` kept 56px padding while the nav is hidden during a selection, floating the card ~64px up. Decision: `pb-14` only while the nav is visible; step 6, with a 400px browser check and an audit of other `pb-14` routes.
- G3 (accepted): `isDesktop()` (md) breakpoint everywhere, `md:` classes, margin 16/8 shared by card and notices.
- G4 (accepted): `disabledInteractive` on every icon button; vitest asserts it on delete and download.
- G5 (accepted): spacer = measured bar height + margin (floor 112px); `photo-card.component.ts` `scroll-mb-28` raised (start `scroll-mb-44`) with comment rewritten; browser check on the last row.
- G6 (accepted): `tagsButton` desktop-only test and text-based `deleteButton`/`tagsButton` lookups are adapted; step 7 requires ADAPTED vs ASSERTION-CHANGED disclosure.
- G7 (accepted): `docs_parity.py` / `docs_xlinks.py` do not exist; replaced by a grep check over 7 docs (the "above the selection bar" phrase, the Multi-Select "Action bar appears..." line, the Mobile paragraph).
- G8 (accepted): notices' resting bottom goes 8 -> 16 on desktop even without a selection; intended and tested (step 4).
- G9 (accepted): overlap rule measures the `[data-gallery-notices]` rect rather than duplicating its width formula (step 1).
- N10 (note): the card is earlier in the DOM than before (inside the host), so tab order moves earlier; acceptable.
- N11 (note): tests locate the host via `closest('.relative.h-full')`.
- N12 (note): `data-selection-bar` and `data-selection-status` attributes are kept.
