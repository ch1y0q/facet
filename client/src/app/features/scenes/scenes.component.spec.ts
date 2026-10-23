import type { Mock } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute, Router } from '@angular/router';
import { of } from 'rxjs';
import { MatSnackBar } from '@angular/material/snack-bar';
import { ApiService } from '../../core/services/api.service';
import { AlbumService } from '../../core/services/album.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { PageContextService } from '../../core/agent/page-context.service';
import { GalleryStore } from '../gallery/gallery.store';
import { ScenesComponent } from './scenes.component';

describe('ScenesComponent page context', () => {
  let mockApi: { get: Mock };
  let pageContext: PageContextService;

  const setup = (album: string | null = null): ScenesComponent => {
    mockApi = { get: vi.fn(() => of({ scenes: [], total: 7, page: 1, per_page: 20, total_pages: 1 })) };
    TestBed.configureTestingModule({
      providers: [
        ScenesComponent,
        { provide: ApiService, useValue: mockApi },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: I18nService, useValue: { t: vi.fn((key: string) => key) } },
        { provide: ActivatedRoute, useValue: { snapshot: { queryParamMap: { get: () => album } } } },
        { provide: Router, useValue: { navigate: vi.fn() } },
        { provide: AlbumService, useValue: { listNonSmart: () => of([]) } },
        { provide: AuthService, useValue: { isEdition: vi.fn(() => false) } },
        { provide: GalleryStore, useValue: { config: () => null } },
      ],
    });
    pageContext = TestBed.inject(PageContextService);
    return TestBed.inject(ScenesComponent);
  };

  it('registers the scenes page with an empty scope before anything loads', () => {
    setup();
    expect(pageContext.snapshot()).toEqual({ id: 'scenes', album_id: null, total: 0 });
  });

  it('reports the album scope and total once loaded', async () => {
    const component = setup('42');
    await component.ngOnInit();
    expect(pageContext.snapshot()).toEqual({ id: 'scenes', album_id: '42', total: 7 });
  });

  it('removes the registration when the component is destroyed', () => {
    setup();
    expect(pageContext.snapshot()).not.toBeNull();
    TestBed.resetTestingModule();
    expect(pageContext.snapshot()).toBeNull();
  });
});
