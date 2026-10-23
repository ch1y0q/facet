import { inject } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationEnd, ParamMap, Router } from '@angular/router';
import { filter } from 'rxjs';

/**
 * Call `apply` with the query of every finished navigation to `path`, including a same-URL reload
 * (which the router does not report through `ActivatedRoute.queryParamMap`). A page whose filters
 * live in root signals uses it so a navigation made by the assistant sets the page to exactly that query.
 * Once `apply` ran for a query that carries any of `keys`, those keys are removed from the URL (history is
 * replaced), so Back and reload never re-apply the query over the user's own edits.
 * Must run in an injection context.
 */
export function onPageQuery(path: string, keys: readonly string[], apply: (query: ParamMap) => void): void {
  const router = inject(Router);
  let cleaning = false;
  router.events.pipe(
    filter((event): event is NavigationEnd => event instanceof NavigationEnd),
    takeUntilDestroyed(),
  ).subscribe(event => {
    // The cleanup navigation below is ours: re-running `apply` for it would hand the page an empty query.
    if (cleaning) return;
    const tree = router.parseUrl(event.urlAfterRedirects);
    if (`/${tree.root.children['primary']?.segments.map(s => s.path).join('/') ?? ''}` !== path) return;
    apply(tree.queryParamMap);
    const carried = keys.filter(key => tree.queryParamMap.has(key));
    if (carried.length === 0) return;
    cleaning = true;
    void Promise.resolve(router.navigate([path], {
      queryParams: Object.fromEntries(carried.map(key => [key, null])),
      queryParamsHandling: 'merge',
      replaceUrl: true,
    })).finally(() => { cleaning = false; });
  });
}
