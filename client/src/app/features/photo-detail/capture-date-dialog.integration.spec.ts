import { provideHttpClient, withXhr } from '@angular/common/http';
import { HttpTestingController, provideHttpClientTesting } from '@angular/common/http/testing';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { MAT_DIALOG_DATA, MatDialogRef } from '@angular/material/dialog';
import { provideRouter } from '@angular/router';
import { Subject } from 'rxjs';
import { AuthService, AuthStatus } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from '../gallery/gallery.store';
import { CaptureDateDialogComponent, CaptureDateDialogData } from './capture-date-dialog.component';

const translations = { capture_date: { title: 'Correct capture date', offset: 'Offset in seconds',
  invalid: 'Use a nonzero whole number of seconds within ±366 days; select at most 1000 photos.',
  counts: '{changed} changed · {skipped} skipped', photo: 'Photo', before: 'Before', after: 'After',
  error: 'Could not complete the action.', preview: 'Preview', apply: 'Apply correction', use_file: 'Use file date' },
  ui: { buttons: { cancel: 'Cancel' } } };
const preview = { changed: 1, skipped: 2, samples: [
  { path: '/photo.jpg', old_date: '2024:01:01 00:00:00', new_date: '2023:12:31 23:58:30' },
], preview_token: 'first-token' };

describe('Capture-date dialog rendered controls and HTTP', () => {
  let fixture: ComponentFixture<CaptureDateDialogComponent>;
  let http: HttpTestingController;
  let root: HTMLElement;
  let closed: Subject<void>;
  let dialog: { close: ReturnType<typeof vi.fn>; disableClose: boolean; beforeClosed: () => Subject<void> };
  let store: { refreshPaths: ReturnType<typeof vi.fn>; patchPhoto: ReturnType<typeof vi.fn> };

  async function create(data: CaptureDateDialogData = { paths: ['/photo.jpg'], count: 1, manuallySet: true }) {
    TestBed.resetTestingModule();
    closed = new Subject<void>();
    dialog = { close: vi.fn(), disableClose: false, beforeClosed: () => closed };
    store = { refreshPaths: vi.fn(), patchPhoto: vi.fn() };
    TestBed.configureTestingModule({ imports: [CaptureDateDialogComponent], providers: [
      provideHttpClient(withXhr()), provideHttpClientTesting(), provideRouter([]),
      { provide: MAT_DIALOG_DATA, useValue: data }, { provide: MatDialogRef, useValue: dialog },
      { provide: GalleryStore, useValue: store },
    ] });
    http = TestBed.inject(HttpTestingController);
    const status: AuthStatus = { authenticated: true, multi_user: true, edition_enabled: true,
      edition_authenticated: true, edition_password_required: true, login_password_required: true,
      user_id: 'alice', user_role: 'user', display_name: 'Alice', features: {}, download_profiles: [] };
    TestBed.inject(AuthService).status.set(status);
    const i18n = TestBed.inject(I18nService);
    i18n.locale.set('en');
    const loaded = i18n.load();
    http.expectOne('/api/i18n/en').flush(translations);
    await loaded;
    fixture = TestBed.createComponent(CaptureDateDialogComponent);
    root = fixture.nativeElement;
    fixture.detectChanges();
    await fixture.whenStable();
  }

  function button(label: string): HTMLButtonElement {
    const found = [...root.querySelectorAll('button')].find(item => item.textContent?.trim() === label);
    expect(found, label).toBeDefined();
    return found!;
  }
  function input(): HTMLInputElement { return root.querySelector('input')!; }
  async function offset(value: string) {
    input().value = value;
    input().dispatchEvent(new Event('input', { bubbles: true }));
    fixture.detectChanges();
    await fixture.whenStable();
  }
  async function settle() { fixture.detectChanges(); await fixture.whenStable(); fixture.detectChanges(); }
  afterEach(() => { try { http?.verify(); } finally { TestBed.resetTestingModule(); } });

  it.each(['', '0', '0.5', '31622401', '-31622401'])('associates invalid offset %j with its rendered explanation and refuses requests', async value => {
    await create();
    await offset(value);
    expect(input().labels?.[0]?.textContent).toContain('Offset in seconds');
    expect(input().getAttribute('aria-invalid')).toBe('true');
    const description = input().getAttribute('aria-describedby');
    expect(description).toBeTruthy();
    const error = root.querySelector(`[id="${description}"]`);
    expect(error?.getAttribute('role')).toBe('alert');
    expect(error?.textContent).toContain(translations.capture_date.invalid);
    expect(button('Preview').disabled).toBe(true);
    expect(button('Apply correction').disabled).toBe(true);
    button('Preview').click();
    http.expectNone(request => request.url.includes('capture_date'));
    await offset('-90');
    expect(input().getAttribute('aria-invalid')).toBe('false');
    expect(input().getAttribute('aria-describedby')).toBeNull();
    expect(root.querySelector('[role="alert"]')).toBeNull();
    expect(button('Preview').disabled).toBe(false);
  });

  it.each([-31622400, 31622400])('maps the inclusive offset boundary %i from the number input into HTTP', async value => {
    await create(); await offset(String(value));
    expect(button('Preview').disabled).toBe(false);
    button('Preview').click();
    const request = http.expectOne('/api/photos/capture_date/preview');
    expect(request.request.body.offset_seconds).toBe(value);
    expect(typeof request.request.body.offset_seconds).toBe('number');
    request.flush({ ...preview, changed: 0, samples: [] }); await settle();
    expect(button('Apply correction').disabled).toBe(true);
  });

  it('renders preview counts, scoped column headers and samples from the input-mapped request', async () => {
    await create(); await offset('-90'); button('Preview').click(); fixture.detectChanges();
    const request = http.expectOne('/api/photos/capture_date/preview');
    expect(request.request.body).toEqual({ photo_paths: ['/photo.jpg'], exclude: [], offset_seconds: -90 });
    await vi.waitFor(() => expect(input().disabled).toBe(true));
    expect(button('Cancel').disabled).toBe(true);
    expect(button('Preview').disabled).toBe(true);
    request.flush(preview); await settle();
    expect(root.querySelector('[role="status"]')?.textContent).toContain('1 changed · 2 skipped');
    const headers = [...root.querySelectorAll('thead th')];
    expect(headers.map(item => item.textContent?.trim())).toEqual(['Photo', 'Before', 'After']);
    expect(headers.map(item => item.getAttribute('scope'))).toEqual(['col', 'col', 'col']);
    expect([...root.querySelectorAll('tbody td')].map(item => item.textContent?.trim())).toEqual([
      '/photo.jpg', '2024:01:01 00:00:00', '2023:12:31 23:58:30',
    ]);
    expect(button('Apply correction').disabled).toBe(false);
    await offset('60');
    expect(root.querySelector('table')).toBeNull();
    expect(button('Apply correction').disabled).toBe(true);
  });

  it('renders preview failure and permits a successful retry without publishing edits', async () => {
    await create(); button('Preview').click();
    http.expectOne('/api/photos/capture_date/preview').flush({}, { status: 503, statusText: 'Unavailable' });
    await settle();
    expect(root.querySelector('[role="alert"]')?.textContent).toContain(translations.capture_date.error);
    expect(button('Preview').disabled).toBe(false); expect(input().disabled).toBe(false);
    expect(button('Apply correction').disabled).toBe(true);
    button('Preview').click(); fixture.detectChanges();
    expect(root.querySelector('[role="alert"]')).toBeNull();
    http.expectOne('/api/photos/capture_date/preview').flush(preview); await settle();
    expect(button('Apply correction').disabled).toBe(false);
    expect(store.patchPhoto).not.toHaveBeenCalled(); expect(dialog.close).not.toHaveBeenCalled();
  });

  it('clears a conflicting preview and requires a new token before the rendered apply can succeed', async () => {
    await create(); await offset('-90'); button('Preview').click();
    http.expectOne('/api/photos/capture_date/preview').flush(preview); await settle();
    button('Apply correction').click(); fixture.detectChanges();
    expect(dialog.disableClose).toBe(true);
    const apply = http.expectOne('/api/photos/capture_date/apply');
    expect(apply.request.body.preview_token).toBe('first-token');
    apply.flush({}, { status: 409, statusText: 'Conflict' }); await settle();
    expect(root.querySelector('[role="alert"]')?.textContent).toContain(translations.capture_date.error);
    expect(root.querySelector('table')).toBeNull();
    expect(button('Apply correction').disabled).toBe(true); expect(dialog.disableClose).toBe(false);
    expect(store.patchPhoto).not.toHaveBeenCalled(); expect(store.refreshPaths).not.toHaveBeenCalled();
    button('Preview').click();
    http.expectOne('/api/photos/capture_date/preview').flush({ ...preview, preview_token: 'retry-token' }); await settle();
    button('Apply correction').click();
    const retry = http.expectOne('/api/photos/capture_date/apply');
    expect(retry.request.body).toEqual({ photo_paths: ['/photo.jpg'], exclude: [], offset_seconds: -90, preview_token: 'retry-token' });
    retry.flush({ changed: 1 }); await settle();
    expect(store.patchPhoto).toHaveBeenCalledWith('/photo.jpg', { date_taken: preview.samples[0].new_date, date_manually_set: 1 });
    expect(store.refreshPaths).toHaveBeenCalledWith(null);
    expect(dialog.close).toHaveBeenCalledWith({ date_taken: preview.samples[0].new_date, date_manually_set: 1 });
  });

  it('renders reset failure, restores controls and publishes only the successful reset retry', async () => {
    await create(); button('Use file date').click(); fixture.detectChanges();
    expect(dialog.disableClose).toBe(true);
    await vi.waitFor(() => expect(input().disabled).toBe(true));
    const reset = http.expectOne('/api/photo/capture_date?path=%2Fphoto.jpg');
    expect(reset.request.method).toBe('DELETE');
    reset.flush({}, { status: 500, statusText: 'Unreadable' }); await settle();
    expect(root.querySelector('[role="alert"]')?.textContent).toContain(translations.capture_date.error);
    expect(button('Use file date').disabled).toBe(false); expect(dialog.disableClose).toBe(false);
    expect(store.patchPhoto).not.toHaveBeenCalled(); expect(store.refreshPaths).not.toHaveBeenCalled();
    button('Use file date').click();
    http.expectOne('/api/photo/capture_date?path=%2Fphoto.jpg').flush({ date_taken: null, date_manually_set: 0 }); await settle();
    expect(store.patchPhoto).toHaveBeenCalledWith('/photo.jpg', { date_taken: null, date_manually_set: 0 });
    expect(dialog.close).toHaveBeenCalledWith({ date_taken: null, date_manually_set: 0 });
  });

  it('disables preview for oversized selections and hides reset when unavailable', async () => {
    await create({ paths: [], count: 1001, filters: { review_status: 'kept' }, manuallySet: false });
    expect(button('Preview').disabled).toBe(true);
    expect([...root.querySelectorAll('button')].some(item => item.textContent?.trim() === 'Use file date')).toBe(false);
    expect(input().getAttribute('aria-invalid')).toBe('true');
    http.expectNone(request => request.url.includes('capture_date'));
  });
});
