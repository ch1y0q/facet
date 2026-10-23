/**
 * True when a keyboard event originates from a text-entry context (input,
 * textarea, native select, or contenteditable), where global single-key
 * shortcuts must not fire. Shared by the gallery grid and the burst-culling
 * darkroom so both gate keyboard shortcuts the same way.
 */
export function isTypingContext(event: Event): boolean {
  const target = event.target as HTMLElement | null;
  if (!target) return false;
  return ['INPUT', 'TEXTAREA', 'SELECT'].includes(target.tagName) || target.isContentEditable;
}

/**
 * True when Enter or Space would activate the focused control (a button, link or menu item):
 * a page-level shortcut on those keys must leave it to the control.
 */
export function isControlActivation(event: Event): boolean {
  const target = event.target as HTMLElement | null;
  return !!target?.closest?.('button, a[href], [role="menuitem"], [role="option"]');
}
