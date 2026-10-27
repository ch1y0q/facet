import { closeOverlayDirectives } from './overlays';

describe('closeOverlayDirectives', () => {
  it('hides tooltips immediately, closes menus and closes selects', () => {
    const tooltip = { hide: vi.fn() };
    const menu = { closeMenu: vi.fn() };
    const select = { close: vi.fn() };
    closeOverlayDirectives([tooltip], [menu], [select]);
    expect(tooltip.hide).toHaveBeenCalledWith(0);
    expect(menu.closeMenu).toHaveBeenCalledTimes(1);
    expect(select.close).toHaveBeenCalledTimes(1);
  });

  it('accepts tooltips alone', () => {
    const tooltip = { hide: vi.fn() };
    closeOverlayDirectives([tooltip]);
    expect(tooltip.hide).toHaveBeenCalledWith(0);
  });
});
