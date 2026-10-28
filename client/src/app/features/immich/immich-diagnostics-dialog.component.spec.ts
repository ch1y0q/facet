import { ComponentFixture, TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { provideHttpClient } from '@angular/common/http';
import { provideHttpClientTesting, HttpTestingController } from '@angular/common/http/testing';
import { MatDialogRef } from '@angular/material/dialog';
import { provideRouter, Router } from '@angular/router';
import { Subject } from 'rxjs';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { ImmichDiagnosticsDialogComponent } from './immich-diagnostics-dialog.component';

const LOCAL = { configured: true, mapping_rules: 1, sample_limit: 200,
  sampled_photos: 10, mapped_photos: 8, last_push_at: null,
  connection: 'not_checked', version: null, stack_version_supported: null };

describe('Immich diagnostics HTTP dialog', () => {
  let fixture: ComponentFixture<ImmichDiagnosticsDialogComponent>;
  let http: HttpTestingController;
  let identity: ReturnType<typeof signal<string>>;
  let edition: ReturnType<typeof signal<boolean>>;
  let close: ReturnType<typeof vi.fn>;
  let closed: Subject<void>;

  beforeEach(() => {
    identity = signal('alice'); edition = signal(true); closed = new Subject();
    close = vi.fn(() => closed.next());
    TestBed.configureTestingModule({
      imports: [ImmichDiagnosticsDialogComponent],
      providers: [provideRouter([]), provideHttpClient(), provideHttpClientTesting(),
        { provide: AuthService, useValue: { identity, isInstallAdmin: edition } },
        { provide: I18nService, useValue: {
          t: (key: string, params?: Record<string, unknown>) => (params ? `${key} ${Object.values(params).join(' ')}` : key),
          translations: () => ({}) } },
        { provide: MatDialogRef, useValue: { close, beforeClosed: () => closed } },
      ],
    });
    http = TestBed.inject(HttpTestingController);
    fixture = TestBed.createComponent(ImmichDiagnosticsDialogComponent);
    fixture.detectChanges();
  });

  afterEach(() => { fixture.destroy(); http.verify(); });

  function read() {
    return http.expectOne(req => req.url === '/api/immich/diagnostics');
  }

  async function local() {
    const req = read();
    expect(req.request.method).toBe('GET');
    expect(req.request.params.get('check_connection')).toBe('false');
    req.flush(LOCAL); await fixture.whenStable(); fixture.detectChanges();
  }

  it('loads local status without starting a connection test, then tests only on explicit action', async () => {
    await local();
    expect(fixture.nativeElement.textContent).toContain('8 / 10');
    const pending = fixture.componentInstance.load(true);
    const req = read();
    expect(req.request.params.get('check_connection')).toBe('true');
    req.flush({ ...LOCAL, connection: 'connected', version: '3.1.0', stack_version_supported: true });
    await pending; fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('3.1.0');
    expect(fixture.nativeElement.textContent).toContain('immich_diagnostics.stack_version_ok');
  });

  it.each([
    ['access_denied', 'immich_diagnostics.access_denied'],
    ['unreachable', 'immich_diagnostics.unreachable'],
    ['invalid_config', 'immich_diagnostics.invalid_config'],
  ])('labels a %s connection result', async (connection, label) => {
    await local();
    const pending = fixture.componentInstance.load(true);
    read().flush({ ...LOCAL, connection });
    await pending; fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain(label);
  });

  it('warns that stack exchange needs Immich 3 on an older server', async () => {
    await local();
    const pending = fixture.componentInstance.load(true);
    read().flush({ ...LOCAL, connection: 'connected', version: '2.9.0', stack_version_supported: false });
    await pending; fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('immich_diagnostics.version 2.9.0');
    expect(fixture.nativeElement.textContent).toContain('immich_diagnostics.stack_version_old');
  });

  it('does not launch duplicate tests while a request is pending', async () => {
    const req = read();
    await fixture.componentInstance.load(true);
    http.expectNone('/api/immich/diagnostics?check_connection=true');
    req.flush(LOCAL); await fixture.whenStable();
  });

  it.each(['identity', 'edition', 'navigation', 'dismiss'])(
    'ignores late diagnostics and refuses new requests after %s changes', async change => {
      await local();
      const pending = fixture.componentInstance.load(true);
      const req = read();
      if (change === 'identity') identity.set('bob');
      else if (change === 'edition') edition.set(false);
      else if (change === 'navigation') {
        await TestBed.inject(Router).navigateByUrl('/?other=1');
      } else closed.next();
      req.flush({ ...LOCAL, connection: 'connected', version: '3.2.0', stack_version_supported: true });
      await pending; fixture.detectChanges();
      expect(fixture.nativeElement.textContent).not.toContain('3.2.0');
      await fixture.componentInstance.load(true);
      http.expectNone(req => req.url === '/api/immich/diagnostics');
    },
  );

  it('cancels an active HTTP read when the component is destroyed', async () => {
    const request = read(); fixture.destroy();
    expect(request.cancelled).toBe(true);
  });

  it('renders a safe retryable failure without provider detail', async () => {
    const req = read();
    req.flush({ detail: 'private remote key' }, { status: 503, statusText: 'Unavailable' });
    await fixture.whenStable(); fixture.detectChanges();
    expect(fixture.nativeElement.textContent).toContain('immich_diagnostics.failed');
    expect(fixture.nativeElement.textContent).not.toContain('private remote key');
    const retry = fixture.componentInstance.load(false); read().flush(LOCAL); await retry;
    fixture.detectChanges(); expect(fixture.nativeElement.textContent).not.toContain('immich_diagnostics.failed');
  });
});
