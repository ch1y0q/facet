import { computed, signal } from '@angular/core';
import { TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Subject } from 'rxjs';
import { AuthService } from '../services/auth.service';
import { I18nService } from '../services/i18n.service';
import { InpageChangeNotifier } from './inpage-change-notifier.service';

describe('InpageChangeNotifier', () => {
  let open: ReturnType<typeof vi.fn>;
  let dismiss: ReturnType<typeof vi.fn>;
  let authStatus: ReturnType<typeof signal<{ authenticated: boolean; user_id: string | null } | null>>;
  let dismissals: Subject<void>[];
  let notifier: InpageChangeNotifier;

  const flush = async (): Promise<void> => {
    TestBed.tick();
    await new Promise(resolve => setTimeout(resolve, 0));
  };

  beforeEach(() => {
    dismissals = [];
    dismiss = vi.fn();
    authStatus = signal({ authenticated: true, user_id: 'alice' });
    open = vi.fn(() => {
      const dismissed = new Subject<void>();
      dismissals.push(dismissed);
      return { afterDismissed: () => dismissed, dismiss };
    });
    TestBed.configureTestingModule({
      providers: [
        { provide: MatSnackBar, useValue: { open } },
        { provide: AuthService, useValue: { identity: computed(() => `${authStatus()?.authenticated ? 1 : 0}|${authStatus()?.user_id ?? ''}`) } },
        { provide: I18nService, useValue: { t: (key: string, vars?: Record<string, string>) => `${key} ${vars?.['count'] ?? ''}`.trim() } },
      ],
    });
    notifier = TestBed.inject(InpageChangeNotifier);
  });

  it('coalesces a burst into one growing count', () => {
    notifier.notify(2);
    notifier.notify(3);
    notifier.notify(1);
    expect(open.mock.calls.map(c => c[0])).toEqual([
      'dialog.connect_assistant.inpage_changed_plural 2',
      'dialog.connect_assistant.inpage_changed_plural 5',
      'dialog.connect_assistant.inpage_changed_plural 6',
    ]);
  });

  it('uses the singular form for one photo and offers a Close action', () => {
    notifier.notify(1);
    expect(open.mock.calls[0][0]).toBe('dialog.connect_assistant.inpage_changed 1');
    expect(open.mock.calls[0][1]).toBe('dialog.close');
  });

  it('starts a fresh count once the snackbar is dismissed, and ignores zero-change calls', () => {
    notifier.notify(0);
    expect(open).not.toHaveBeenCalled();
    notifier.notify(2);
    dismissals.at(-1)!.next();
    notifier.notify(1);
    expect(open.mock.calls[1][0]).toBe('dialog.connect_assistant.inpage_changed 1');
  });

  it('drops the burst on logout and on a user switch, but not on an unrelated status change', async () => {
    await flush();
    notifier.notify(2);
    authStatus.set({ authenticated: true, user_id: 'alice' });
    await flush();
    expect(dismiss).not.toHaveBeenCalled();
    authStatus.set({ authenticated: true, user_id: 'bob' });
    await flush();
    expect(dismiss).toHaveBeenCalledTimes(1);
    notifier.notify(1);
    expect(open.mock.calls.at(-1)![0]).toBe('dialog.connect_assistant.inpage_changed 1');
    authStatus.set(null);
    await flush();
    expect(dismiss).toHaveBeenCalledTimes(2);
    notifier.notify(4);
    expect(open.mock.calls.at(-1)![0]).toBe('dialog.connect_assistant.inpage_changed_plural 4');
  });

  describe('with the real snackbar', () => {
    beforeEach(() => {
      TestBed.resetTestingModule();
      TestBed.configureTestingModule({
        providers: [
          { provide: AuthService, useValue: { identity: computed(() => `${authStatus()?.authenticated ? 1 : 0}|${authStatus()?.user_id ?? ''}`) } },
          { provide: I18nService, useValue: { t: (key: string) => key === 'dialog.close' ? 'Close' : key } },
        ],
      });
      notifier = TestBed.inject(InpageChangeNotifier);
    });

    afterEach(() => {
      TestBed.inject(MatSnackBar).dismiss();
      TestBed.resetTestingModule();
    });

    it('shows a Close button that dismisses the snackbar', async () => {
      notifier.notify(2);
      await vi.waitFor(() => expect(document.querySelector('.mat-mdc-snack-bar-action')?.textContent?.trim()).toBe('Close'));
      (document.querySelector('.mat-mdc-snack-bar-action') as HTMLButtonElement).click();
      await vi.waitFor(() => expect(document.querySelector('.mat-mdc-snack-bar-action')).toBeNull());
    });
  });
});
