import { Component, OnDestroy } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { Location } from '@angular/common';
import { provideLocationMocks } from '@angular/common/testing';
import { NavigationEnd, provideRouter, RouteReuseStrategy, Router } from '@angular/router';
import { filter, firstValueFrom } from 'rxjs';
import { RouterTestingHarness } from '@angular/router/testing';
import { GalleryReuseStrategy } from './gallery-reuse.strategy';

let destroyed = 0;

@Component({ template: 'gallery' })
class GalleryStub implements OnDestroy {
  ngOnDestroy(): void {
    destroyed++;
  }
}

@Component({ template: 'other' })
class OtherStub {}

describe('GalleryReuseStrategy', () => {
  let harness: RouterTestingHarness;
  let gallery: GalleryStub;

  beforeEach(async () => {
    destroyed = 0;
    TestBed.configureTestingModule({
      providers: [
        provideRouter([
          { path: '', component: GalleryStub },
          { path: 'photo', component: OtherStub },
          { path: 'persons', component: OtherStub },
        ]),
        provideLocationMocks(),
        { provide: RouteReuseStrategy, useClass: GalleryReuseStrategy },
      ],
    });
    harness = await RouterTestingHarness.create();
    // Starts the router's popstate listener, which Location.back() needs.
    TestBed.inject(Router).initialNavigation();
    gallery = await harness.navigateByUrl('/', GalleryStub);
    await harness.navigateByUrl('/photo?path=a.jpg');
  });

  const back = async () => {
    const done = firstValueFrom(TestBed.inject(Router).events.pipe(filter(e => e instanceof NavigationEnd)));
    TestBed.inject(Location).back();
    await done;
  };

  it('reattaches the same gallery on a history back', async () => {
    await back();
    expect(harness.routeDebugElement?.componentInstance).toBe(gallery);
    expect(destroyed).toBe(0);
  });

  it('builds a fresh gallery when the photo navigates to it instead', async () => {
    await TestBed.inject(Router).navigateByUrl('/');
    expect(harness.routeDebugElement?.componentInstance).not.toBe(gallery);
    expect(destroyed).toBe(1);
  });

  it('destroys the kept gallery when the photo leaves elsewhere', async () => {
    await harness.navigateByUrl('/persons');
    expect(destroyed).toBe(1);
  });
});
