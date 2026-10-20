import { TestBed } from '@angular/core/testing';
import { MatSnackBar } from '@angular/material/snack-bar';
import { Subject, of } from 'rxjs';
import { ApiService } from '../services/api.service';
import { I18nService } from '../services/i18n.service';
import { InpageChangeNotifier } from './inpage-change-notifier.service';

describe('InpageChangeNotifier', () => {
  let open: ReturnType<typeof vi.fn>;
  let undoMcpAction: ReturnType<typeof vi.fn>;
  let actions: Subject<void>[];
  let dismissals: Subject<void>[];
  let notifier: InpageChangeNotifier;

  beforeEach(() => {
    actions = [];
    dismissals = [];
    open = vi.fn(() => {
      const action = new Subject<void>();
      const dismissed = new Subject<void>();
      actions.push(action);
      dismissals.push(dismissed);
      return { onAction: () => action, afterDismissed: () => dismissed };
    });
    undoMcpAction = vi.fn(() => of({}));
    TestBed.configureTestingModule({
      providers: [
        { provide: MatSnackBar, useValue: { open } },
        { provide: ApiService, useValue: { undoMcpAction } },
        { provide: I18nService, useValue: { t: (key: string, vars?: Record<string, string>) => `${key} ${vars?.['count'] ?? ''}`.trim() } },
      ],
    });
    notifier = TestBed.inject(InpageChangeNotifier);
  });

  it('coalesces a burst into one growing count and undoes every batch of it', async () => {
    notifier.notify(2, 'b1');
    notifier.notify(3, 'b2');
    notifier.notify(1, 'b3');
    expect(open).toHaveBeenCalledTimes(3);
    expect(open.mock.calls.map(c => c[0])).toEqual([
      'dialog.connect_assistant.inpage_changed 2',
      'dialog.connect_assistant.inpage_changed 5',
      'dialog.connect_assistant.inpage_changed 6',
    ]);
    actions.at(-1)!.next();
    await Promise.resolve();
    await Promise.resolve();
    expect(undoMcpAction.mock.calls.map(c => c[0].batch_id)).toEqual(['b1', 'b2', 'b3']);
  });

  it('starts a fresh count once the snackbar is dismissed, and ignores zero-change calls', () => {
    notifier.notify(0, 'x');
    expect(open).not.toHaveBeenCalled();
    notifier.notify(2, 'b1');
    dismissals.at(-1)!.next();
    notifier.notify(1, 'b2');
    expect(open.mock.calls[1][0]).toBe('dialog.connect_assistant.inpage_changed 1');
  });
});
