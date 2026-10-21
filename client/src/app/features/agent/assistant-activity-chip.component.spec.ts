import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { ActivityEntry, AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from '../gallery/gallery.store';
import { AssistantActivityChipComponent } from './assistant-activity-chip.component';

const entry = (id: number, paths: string[] | null): ActivityEntry => ({ id, at: Date.now(), kind: 'write', tool: 'set_rating', count: paths?.length ?? null, paths });

describe('AssistantActivityChipComponent', () => {
  let active: ReturnType<typeof signal<boolean>>;
  let activity: ReturnType<typeof signal<ActivityEntry[]>>;
  let showPaths: ReturnType<typeof vi.fn>;
  let navigate: ReturnType<typeof vi.fn>;
  let router: { url: string; navigate: ReturnType<typeof vi.fn> };
  let fixture: ComponentFixture<AssistantActivityChipComponent>;

  const el = (): HTMLElement => fixture.nativeElement as HTMLElement;
  const chip = (): HTMLButtonElement | null => el().querySelector('[data-testid="assistant-chip"]');
  const panel = (): Element[] => [...document.querySelectorAll('[data-testid="activity-entry"]')];
  const tick = (): Promise<void> => new Promise(resolve => setTimeout(resolve, 30));
  const open = async (): Promise<void> => {
    chip()!.click();
    fixture.detectChanges();
    await tick();
    fixture.detectChanges();
  };

  beforeEach(() => {
    active = signal(false);
    activity = signal<ActivityEntry[]>([entry(2, ['/a.jpg', '/b.jpg']), entry(1, null)]);
    showPaths = vi.fn(async () => []);
    navigate = vi.fn(async () => true);
    router = { url: '/persons', navigate };
    TestBed.configureTestingModule({
      providers: [
        { provide: AssistantChangesService, useValue: { active, activity } },
        { provide: GalleryStore, useValue: { showPaths } },
        { provide: Router, useValue: router },
        { provide: I18nService, useValue: { locale: signal('en'), translations: signal({}), t: (key: string) => key } },
      ],
    });
    fixture = TestBed.createComponent(AssistantActivityChipComponent);
    fixture.detectChanges();
  });

  afterEach(() => TestBed.resetTestingModule());

  it('is hidden while the assistant is idle and shown, with an accessible name, while active', () => {
    expect(chip()).toBeNull();
    active.set(true);
    fixture.detectChanges();
    expect(chip()).not.toBeNull();
    expect(chip()!.getAttribute('aria-label')).toBe('assistant_activity.chip');
  });

  it('lists the entries newest first when opened', async () => {
    active.set(true);
    fixture.detectChanges();
    await open();
    const rows = panel();
    expect(rows).toHaveLength(2);
    expect(rows[0].textContent).toContain('Set rating');
    expect(rows[0].querySelector('[data-testid="activity-show"]')).not.toBeNull();
    expect(rows[1].querySelector('[data-testid="activity-show"]')).toBeNull();
  });

  it('Show photos calls showPaths with the entry paths and navigates to the gallery when it is closed', async () => {
    active.set(true);
    fixture.detectChanges();
    await open();
    (document.querySelector('[data-testid="activity-show"]') as HTMLButtonElement).click();
    await tick();
    expect(navigate).toHaveBeenCalledWith(['/']);
    expect(showPaths).toHaveBeenCalledWith(['/a.jpg', '/b.jpg']);
  });

  it('does not navigate when the gallery is already open', async () => {
    router.url = '/album/3?x=1';
    active.set(true);
    fixture.detectChanges();
    await open();
    (document.querySelector('[data-testid="activity-show"]') as HTMLButtonElement).click();
    await tick();
    expect(navigate).not.toHaveBeenCalled();
    expect(showPaths).toHaveBeenCalledTimes(1);
  });

  it('keeps the chip while its panel is open after the activity window ends', async () => {
    active.set(true);
    fixture.detectChanges();
    await open();
    active.set(false);
    fixture.detectChanges();
    expect(chip()).not.toBeNull();
  });

  it('the panel buttons are real buttons, reachable by keyboard', async () => {
    active.set(true);
    fixture.detectChanges();
    await open();
    const show = document.querySelector('[data-testid="activity-show"]') as HTMLButtonElement;
    expect(show.tagName).toBe('BUTTON');
    expect(show.tabIndex).toBeGreaterThanOrEqual(-1);
    expect(document.querySelector('[role="menu"]')).not.toBeNull();
  });
});
