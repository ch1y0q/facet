import { TestBed } from '@angular/core/testing';
import { signal } from '@angular/core';
import { provideRouter } from '@angular/router';
import { of } from 'rxjs';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { AuthService } from '../../core/services/auth.service';
import { PhotoStackService } from '../../core/services/photo-stack.service';
import { UndoService, UndoableCommand } from '../../core/services/undo.service';
import { GalleryStore } from './gallery.store';
import { StackActionsService } from './stack-actions.service';

describe('StackActionsService', () => {
  let live: ReturnType<typeof signal<boolean>>;
  let stacks: { context: ReturnType<typeof vi.fn>; create: ReturnType<typeof vi.fn>; revert: ReturnType<typeof vi.fn> };
  let record: ReturnType<typeof vi.fn>;
  let refresh: ReturnType<typeof vi.fn>;
  let register: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    live = signal(true);
    stacks = {
      context: vi.fn(() => () => live()),
      create: vi.fn(() => of({ stack: null, undo: { entry_id: 3 } })),
      revert: vi.fn(() => of({})),
    };
    record = vi.fn(); refresh = vi.fn(async () => undefined); register = vi.fn();
    TestBed.configureTestingModule({
      providers: [provideRouter([]),
        { provide: PhotoStackService, useValue: stacks },
        { provide: UserActivityJournal, useValue: { record } },
        { provide: GalleryStore, useValue: { refreshPaths: refresh } },
        { provide: UndoService, useValue: { register } },
        { provide: AuthService, useValue: { isEdition: () => true } },
      ],
    });
  });

  it('journals, refreshes and offers an Undo that does the same in reverse', async () => {
    const undone = vi.fn();
    await TestBed.inject(StackActionsService).create(['/a', '/b'], '/b', undone);
    expect(stacks.create).toHaveBeenCalledWith(['/a', '/b'], '/b');
    expect(record).toHaveBeenCalledWith('stack', ['/a', '/b'], 'create');
    expect(refresh).toHaveBeenCalledWith(null);
    const command = register.mock.calls[0][0] as UndoableCommand;
    expect(command.labelParams).toEqual({ count: 2 });
    await command.undo();
    expect(stacks.revert).toHaveBeenCalledWith(3);
    expect(record).toHaveBeenCalledWith('stack', ['/a', '/b'], 'undo');
    expect(undone).toHaveBeenCalled();
  });

  it('refuses an Undo from an expired session', async () => {
    await TestBed.inject(StackActionsService).create(['/a', '/b'], '/a');
    live.set(false);
    await expect((register.mock.calls[0][0] as UndoableCommand).undo()).rejects.toThrow();
    expect(stacks.revert).not.toHaveBeenCalled();
  });

  it('offers no Undo when the server reports none', async () => {
    stacks.create.mockReturnValueOnce(of({ stack: null, undo: null }));
    await TestBed.inject(StackActionsService).create(['/a', '/b'], '/a');
    expect(register).not.toHaveBeenCalled();
  });
});
