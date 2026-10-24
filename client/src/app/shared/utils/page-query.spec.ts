import type { Mock } from 'vitest';
import { Component, EnvironmentInjector, createEnvironmentInjector, runInInjectionContext } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { ParamMap, Router, provideRouter } from '@angular/router';
import { onPageQuery } from './page-query';

@Component({ template: '' })
class StubComponent {}

describe('onPageQuery', () => {
  let router: Router;
  let apply: Mock<(query: ParamMap) => void>;

  const flush = async (): Promise<void> => {
    for (let i = 0; i < 5; i += 1) await new Promise(resolve => setTimeout(resolve, 0));
  };

  const setup = (): void => {
    TestBed.configureTestingModule({
      providers: [provideRouter([
        { path: 'albums', component: StubComponent },
        { path: 'other', component: StubComponent },
        { path: '', component: StubComponent },
      ])],
    });
    router = TestBed.inject(Router);
    apply = vi.fn();
  };

  const register = (path = '/albums', keys: readonly string[] = ['search']): void => {
    TestBed.runInInjectionContext(() => onPageQuery(path, keys, apply));
  };

  beforeEach(setup);

  it('applies the query of a navigation to the watched path', async () => {
    register();
    await router.navigateByUrl('/albums?search=cats');
    await flush();
    expect(apply).toHaveBeenCalledTimes(1);
    expect(apply.mock.calls[0][0].get('search')).toBe('cats');
  });

  it('ignores navigations to other paths', async () => {
    register();
    await router.navigateByUrl('/other?search=cats');
    await flush();
    expect(apply).not.toHaveBeenCalled();
  });

  it('removes the carried keys from the URL and does not re-apply for the cleanup navigation', async () => {
    register();
    await router.navigateByUrl('/albums?search=cats&keep=1');
    await flush();
    expect(apply).toHaveBeenCalledTimes(1);
    expect(router.url).toBe('/albums?keep=1');
  });

  it('does not navigate again when the query carries none of the keys', async () => {
    register();
    const navigate = vi.spyOn(router, 'navigate');
    await router.navigateByUrl('/albums?keep=1');
    await flush();
    expect(apply).toHaveBeenCalledTimes(1);
    expect(apply.mock.calls[0][0].has('search')).toBe(false);
    expect(navigate).not.toHaveBeenCalled();
    expect(router.url).toBe('/albums?keep=1');
  });

  it('applies again for a later query once the cleanup finished', async () => {
    register();
    await router.navigateByUrl('/albums?search=a');
    await flush();
    await router.navigateByUrl('/albums?search=b');
    await flush();
    expect(apply).toHaveBeenCalledTimes(2);
    expect(apply.mock.calls[1][0].get('search')).toBe('b');
  });

  it('stops listening once the injector is destroyed', async () => {
    const child = createEnvironmentInjector([], TestBed.inject(EnvironmentInjector));
    runInInjectionContext(child, () => onPageQuery('/albums', ['search'], apply));
    child.destroy();
    await router.navigateByUrl('/albums?search=cats');
    await flush();
    expect(apply).not.toHaveBeenCalled();
  });

  it('matches the root path "/"', async () => {
    register('/', ['q']);
    await router.navigateByUrl('/?q=1');
    await flush();
    expect(apply).toHaveBeenCalledTimes(1);
    expect(router.url).toBe('/');
  });
});
