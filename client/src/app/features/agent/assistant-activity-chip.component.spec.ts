import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { Router } from '@angular/router';
import { ActivityEntry, AssistantChangesService } from '../../core/agent/assistant-changes.service';
import { I18nService } from '../../core/services/i18n.service';
import { GalleryStore } from '../gallery/gallery.store';
import { AssistantActivityChipComponent } from './assistant-activity-chip.component';

const entry = (id: number, paths: string[] | null): ActivityEntry => ({ id, at: Date.now(), kind: 'write', tool: 'set_rating', count: paths?.length ?? null, paths, showPaths: null });

describe('AssistantActivityChipComponent', () => {
  let active: ReturnType<typeof signal<boolean>>;
  let activity: ReturnType<typeof signal<ActivityEntry[]>>;
  let showPaths: ReturnType<typeof vi.fn>;
  let navigate: ReturnType<typeof vi.fn>;
  let router: { url: string; navigate: ReturnType<typeof vi.fn> };
  let translations: ReturnType<typeof signal<Record<string, string>>>;
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
    translations = signal<Record<string, string>>({});
    activity = signal<ActivityEntry[]>([entry(2, ['/a.jpg', '/b.jpg']), entry(1, null)]);
    showPaths = vi.fn(async () => []);
    navigate = vi.fn(async () => true);
    router = { url: '/persons', navigate };
    TestBed.configureTestingModule({
      providers: [
        { provide: AssistantChangesService, useValue: { active, activity } },
        { provide: GalleryStore, useValue: { showPaths } },
        { provide: Router, useValue: router },
        { provide: I18nService, useValue: { locale: signal('en'), translations: signal({}), t: (key: string) => translations()[key] ?? key } },
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
    expect(rows[0].textContent).toContain('set_rating');
    expect(rows[0].querySelector('[data-testid="activity-show"]')).not.toBeNull();
    expect(rows[1].querySelector('[data-testid="activity-show"]')).toBeNull();
  });

  it('shows the translated tool label, falling back to the raw name', async () => {
    translations.set({ 'assistant_activity.tools.set_rating': 'Rated photos' });
    active.set(true);
    fixture.detectChanges();
    await open();
    expect(panel()[0].textContent).toContain('Rated photos');
    activity.set([{ ...entry(3, null), tool: 'mystery_tool' }]);
    fixture.detectChanges();
    expect(panel()[0].textContent).toContain('mystery_tool');
  });

  it('a ui entry text differs from the Show photos button text', async () => {
    translations.set({ 'assistant_activity.ui.ui_show_photos': 'Showed photos', 'assistant_activity.show_photos': 'Show photos' });
    activity.set([{ id: 9, at: Date.now(), kind: 'ui', tool: 'ui_show_photos', count: null, paths: ['/a.jpg'], showPaths: null }]);
    active.set(true);
    fixture.detectChanges();
    await open();
    const row = panel()[0];
    const label = row.querySelector('[data-testid="activity-label"]')!.textContent!.trim();
    const button = row.querySelector('[data-testid="activity-show"]')!.textContent!.trim();
    expect(label).toBe('Showed photos');
    expect(label).not.toBe(button);
  });

  it('names each Show photos button after its own entry', async () => {
    translations.set({ 'assistant_activity.show_photos': 'Show photos' });
    activity.set([{ ...entry(1, ['/a.jpg']), tool: 'tool_a' }, { ...entry(2, ['/b.jpg']), tool: 'tool_b' }]);
    active.set(true);
    fixture.detectChanges();
    await open();
    const names = [...document.querySelectorAll('[data-testid="activity-show"]')].map(b => b.getAttribute('aria-label'));
    expect(names).toHaveLength(2);
    expect(names[0]).toBe('Show photos: tool_a');
    expect(names[1]).toMatch(/: tool_b$/);
  });

  it('shows no Show photos button for an empty showPaths with no paths', async () => {
    activity.set([{ ...entry(6, null), showPaths: [] }]);
    active.set(true);
    fixture.detectChanges();
    await open();
    expect(document.querySelector('[data-testid="activity-show"]')).toBeNull();
  });

  it('Show photos uses showPaths over paths, and appears for showPaths alone', async () => {
    activity.set([{ ...entry(5, null), showPaths: ['/r1.jpg'] }]);
    active.set(true);
    fixture.detectChanges();
    await open();
    (document.querySelector('[data-testid="activity-show"]') as HTMLButtonElement).click();
    await tick();
    expect(showPaths).toHaveBeenCalledWith(['/r1.jpg']);
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
