import { ComponentRef, Injectable, Injector, inject } from '@angular/core';
import {
  ActivatedRouteSnapshot,
  BaseRouteReuseStrategy,
  DetachedRouteHandle,
  Router,
} from '@angular/router';

export const GALLERY_PATHS = ['', 'album/:albumId'];
export const PHOTO_PATH = 'photo';

const isGallery = (route: ActivatedRouteSnapshot) => GALLERY_PATHS.includes(route.routeConfig?.path ?? '-');

/**
 * Keeps the gallery alive while a photo is open, so going back reattaches it
 * instead of rebuilding it. Only a history back to the same gallery URL
 * reattaches; any other way out of the photo destroys the kept gallery.
 */
@Injectable()
export class GalleryReuseStrategy extends BaseRouteReuseStrategy {
  // The Router injects this strategy, so it can only be looked up lazily.
  private readonly injector = inject(Injector);
  private kept: { key: string; handle: DetachedRouteHandle } | null = null;

  private get router(): Router {
    return this.injector.get(Router);
  }

  override shouldDetach(route: ActivatedRouteSnapshot): boolean {
    const next = this.router.currentNavigation()?.finalUrl;
    return isGallery(route) && next?.root.children['primary']?.segments[0]?.path === PHOTO_PATH;
  }

  override store(route: ActivatedRouteSnapshot, handle: DetachedRouteHandle | null): void {
    if (!handle) {
      this.kept = null;
      return;
    }
    this.drop();
    this.kept = { key: this.keyOf(route), handle };
  }

  override shouldAttach(route: ActivatedRouteSnapshot): boolean {
    if (!this.kept) return false;
    if (isGallery(route) && this.isBackToKept(route)) return true;
    // Leaving the photo any other way: free the gallery before the next page is
    // built. The photo itself is asked about right after the gallery is stored.
    if (route.routeConfig?.path !== PHOTO_PATH) this.drop();
    return false;
  }

  // The router only asks after shouldAttach said yes.
  override retrieve(): DetachedRouteHandle | null {
    return this.kept?.handle ?? null;
  }

  private isBackToKept(route: ActivatedRouteSnapshot): boolean {
    return this.router.currentNavigation()?.trigger === 'popstate' && this.keyOf(route) === this.kept?.key;
  }

  private keyOf(route: ActivatedRouteSnapshot): string {
    return this.router.serializeUrl(this.router.createUrlTree(
      ['/', ...route.url.map(s => s.path)], { queryParams: route.queryParams },
    ));
  }

  private drop(): void {
    // A detached handle is the outlet's { componentRef }; nothing else frees it.
    (this.kept?.handle as { componentRef?: ComponentRef<unknown> } | undefined)?.componentRef?.destroy();
    this.kept = null;
  }
}
