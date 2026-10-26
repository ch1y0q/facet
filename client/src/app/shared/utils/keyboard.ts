/**
 * True when a keyboard event belongs to text entry or a control with keyboard
 * navigation/typeahead (including ARIA menus, selects and comboboxes), where
 * page-level shortcuts must not fire. Shared by the gallery, photo page and
 * darkroom so they gate keyboard shortcuts the same way.
 */
export function isTypingContext(event: Event): boolean {
  const target = event.target as HTMLElement | null;
  if (!target) return false;
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable
    || !!target.closest?.('[role="combobox"], [role="listbox"], [role="option"], [role="menu"], [role="menubar"], [role^="menuitem"]');
}

/**
 * True when Enter or Space would activate the focused control (a button, link or menu item):
 * a page-level shortcut on those keys must leave it to the control.
 */
export function isControlActivation(event: Event): boolean {
  const target = event.target as HTMLElement | null;
  return !!target?.closest?.('button, a[href], [role="menuitem"], [role="option"]');
}
