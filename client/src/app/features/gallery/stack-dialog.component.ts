import { ChangeDetectionStrategy, Component, DestroyRef, ElementRef, OnInit, computed, effect, inject, signal, viewChild, viewChildren } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationStart, Router } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom, Observable, Subject, takeUntil } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { PhotoStack, PhotoStackService, StackMutation, StackRegroupPreview, StackRegroupMode } from '../../core/services/photo-stack.service';
import { i18nKeys } from '../../core/i18n/keys';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { PluralKeyPipe } from '../../shared/pipes/plural-key.pipe';
import { FilenamePipe } from '../../shared/pipes/filename.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { Photo } from '../../shared/models/photo.model';
import { GalleryStore } from './gallery.store';
import { StackActionsService } from './stack-actions.service';
import { BY_PATHS_MAX } from './gallery-filters.util';
import { isTypingContext } from '../../shared/utils/keyboard';
import { reconcileRegroupDraft, regroupSourceEffects } from './stack-regroup-state';
import { STACK_MAX_MEMBERS, STACK_MIN_MEMBERS } from './stack-limits';

export interface StackDialogData {
  stackId?: string;
  paths?: string[];
  activePath?: string | null;
  /** Explicit selection only. A whole-view selection must never be materialized implicitly. */
  selectedPaths?: string[];
  /** Opened from a stack suggestion: too few members left offers to skip the suggestion instead. */
  skippable?: boolean;
}

/** Editor result asking the suggestion review to skip the group it was opened on. */
export const SKIP_SUGGESTION = 'skip';

const MUTATION_FAILURE: Record<number, 'conflict' | 'unavailable'> = { 409: 'conflict', 404: 'unavailable', 403: 'unavailable' };

/** Compare stored camera walltimes without guessing a timezone. EXIF and ISO
 *  separators must not make December sort before January in the same year. */
function captureDateKey(date: string | null | undefined): string {
  return date ? date.replace(/^(\d{4}):(\d{2}):(\d{2})/, '$1-$2-$3').replace('T', ' ') : '\uffff';
}

@Component({
  selector: 'app-stack-dialog',
  standalone: true,
  imports: [MatDialogModule, MatButtonModule, MatIconModule, MatTooltipModule, ThumbnailUrlPipe, FilenamePipe, PluralKeyPipe, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'flex flex-col h-full min-h-0 min-w-0' },
  template: `
    <h2 mat-dialog-title class="shrink-0">{{ (stack() ? I18N.stacks.title : I18N.stacks.create) | translate }}</h2>
    <mat-dialog-content class="!flex !flex-col !max-h-none min-h-0 flex-1 !px-3 sm:!px-6 overflow-x-hidden">
      <p class="text-sm opacity-80 mb-3">{{ (editable() ? I18N.stacks.hint : I18N.stacks.read_only) | translate }}</p>
      @if (regrouping() && preview()?.source_stacks?.length) {
        <fieldset class="border-0 p-0 mb-3" [disabled]="saving() || !editable()">
          <legend class="text-sm font-medium mb-1">{{ I18N.stacks.regroup_policy | translate }}</legend>
          <div class="flex flex-wrap gap-2">
            <button mat-stroked-button data-stack-mode="combine" [attr.aria-pressed]="mode() === 'combine'" (click)="changeMode('combine')">{{ I18N.stacks.regroup_combine | translate }}</button>
            <button mat-stroked-button data-stack-mode="selected" [attr.aria-pressed]="mode() === 'selected'" (click)="changeMode('selected')">{{ I18N.stacks.regroup_selected | translate }}</button>
          </div>
          <p class="text-sm mt-2 opacity-80">{{ (mode() === 'combine' ? I18N.stacks.regroup_combine_hint : I18N.stacks.regroup_selected_hint) | translate }}</p>
        </fieldset>
      }
      @if (loading()) { <p role="status">{{ I18N.ui.labels.loading | translate }}</p> }
      @if (error(); as failure) {
        <div role="alert" class="my-3">
          <p>{{ I18N.stacks[failure] | translate }}</p>
          <button mat-button data-stack-retry (click)="retry()" [disabled]="saving() || loading()">{{ (failure === 'error' ? I18N.stacks.regroup_retry : I18N.stacks.reload) | translate }}</button>
        </div>
      }
      @if (ready()) {
        <div class="flex flex-wrap justify-between items-center gap-2 text-sm mb-2" aria-live="polite">
          <p data-stack-member-count>{{ paths().length | pluralKey:I18N.stacks.member_count:I18N.stacks.member_count_plural | translate:{ count: paths().length } }}</p>
          @if (regrouping()) { <p>{{ I18N.stacks.regroup_counts | translate:{ selected: explicitPaths().length, effective: paths().length } }}</p> }
        </div>
        @if (extraCount()) { <p class="text-sm mb-2" role="status">{{ extraCount() | pluralKey:I18N.stacks.regroup_extra:I18N.stacks.regroup_extra_plural | translate:{ count: extraCount() } }}</p> }
        @if (focused(); as path) {
          <div class="relative bg-black/90 rounded-xl flex items-center justify-center shrink-0 h-[28dvh] min-h-32 sm:h-[36dvh] overflow-hidden">
            <img data-stack-preview [src]="path | thumbnailUrl:1920" [alt]="path | filename" decoding="async" class="w-full h-full object-contain" />
            @if (path === cover()) { <span class="absolute top-2 left-2 rounded-full bg-black/75 text-white px-3 py-1 text-xs flex items-center gap-1"><mat-icon aria-hidden="true">star</mat-icon>{{ I18N.stacks.cover | translate }}</span> }
          </div>
          <div class="flex items-center justify-between gap-2 my-2 min-w-0">
            <span class="text-sm truncate" [title]="path">{{ path | filename }}</span>
            <button mat-icon-button (click)="openMember(path)" [disabled]="saving()" [attr.aria-label]="I18N.stacks.open_member | translate:{ path }"><mat-icon>open_in_new</mat-icon></button>
          </div>
        }
        @if (paths().length < 2) { <p role="status" class="my-3">{{ (regrouping() ? I18N.stacks.regroup_minimum : I18N.stacks.dissolve_hint) | translate }}</p> }
        <ol class="grid grid-cols-[repeat(auto-fill,minmax(112px,1fr))] sm:grid-cols-[repeat(auto-fill,minmax(144px,1fr))] gap-2 pb-3">
          @for (path of paths(); track path; let index = $index; let first = $first; let last = $last) {
            <li data-stack-tile class="min-w-0 rounded-lg border border-current/20 overflow-hidden" [class.border-[var(--mat-sys-primary)]]="path === focused()">
              <button #thumbnail [attr.data-stack-focus]="path" class="relative block w-full cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-[-3px]" (click)="focusMember(path)" [disabled]="saving()"
                [attr.aria-pressed]="path === focused()" [attr.aria-label]="I18N.stacks.regroup_focus | translate:{ path }">
                <img [src]="path | thumbnailUrl:640" [alt]="path | filename" loading="lazy" decoding="async" class="w-full h-[84px] sm:h-[108px] object-contain bg-black/70" />
                @if (path === cover()) { <span class="absolute top-1 left-1 rounded bg-black/80 text-white px-1 text-xs">{{ I18N.stacks.cover | translate }}</span> }
              </button>
              <span data-stack-filename class="block text-xs truncate px-2 pt-2" tabindex="0" [matTooltip]="path" [title]="path" [attr.aria-label]="path">{{ path | filename }}</span>
              @if (editable()) {
                <button mat-button class="!w-full" [attr.data-stack-cover]="path" (click)="setCover(path)" [disabled]="saving()" [attr.aria-pressed]="path === cover()" [attr.aria-label]="I18N.stacks.cover_for | translate:{ path }">
                  <mat-icon>{{ path === cover() ? 'star' : 'star_outline' }}</mat-icon>{{ I18N.stacks.cover | translate }}
                </button>
                <div class="flex justify-center">
                  <button mat-icon-button class="!w-9 !h-10 !p-2" (click)="move(index, -1)" [disabled]="saving() || first" [attr.aria-label]="I18N.stacks.move_up | translate:{ path }"><mat-icon>arrow_back</mat-icon></button>
                  <button mat-icon-button class="!w-9 !h-10 !p-2" (click)="move(index, 1)" [disabled]="saving() || last" [attr.aria-label]="I18N.stacks.move_down | translate:{ path }"><mat-icon>arrow_forward</mat-icon></button>
                  <button mat-icon-button class="!w-9 !h-10 !p-2" [attr.data-stack-remove]="path" (click)="remove(path)" [disabled]="saving()" [attr.aria-label]="I18N.stacks.remove | translate:{ path }"><mat-icon>remove_circle_outline</mat-icon></button>
                </div>
              }
            </li>
          }
        </ol>
        @if (sourceEffects().length) {
          <section class="rounded-lg border border-current/20 p-3 text-sm mb-3" [attr.aria-label]="I18N.stacks.regroup_sources | translate">
            <h3 class="font-medium mb-2">{{ I18N.stacks.regroup_sources | translate }}</h3>
            @for (source of sourceEffects(); track source.id) {
              <p data-stack-source class="mb-1"><span class="font-medium">{{ source.cover | filename }}</span>: {{ I18N.stacks.regroup_moved | translate:{ moved: source.moved, total: source.total } }} · {{ I18N.stacks[source.outcome] | translate:{ count: source.remaining } }}</p>
            }
          </section>
        }
        @if (editable() && additions().length) {
          <button mat-button data-stack-add (click)="addSelected()" [disabled]="saving() || loading() || paths().length + additions().length > STACK_MAX_MEMBERS">{{ additions().length | pluralKey:I18N.stacks.add_selected:I18N.stacks.add_selected_plural | translate:{ count: additions().length } }}</button>
        }
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end" class="shrink-0 !px-3 sm:!px-6 border-t border-current/10 !gap-1">
      <button #closeButton mat-button (click)="close()" [disabled]="saving()">{{ I18N.dialog.close | translate }}</button>
      @if (ready()) {
        @if (skippable()) { <button mat-button (click)="skipSuggestion()" [disabled]="saving()">{{ I18N.stacks.suggestion_skip_group | translate }}</button> }
        @if (stack()) { <button mat-button (click)="selectMembers()" [disabled]="saving()">{{ I18N.stacks.select_all | translate:{ count: memberCount() } }}</button> }
        @if (editable()) {
          @if (stack() && !regrouping()) { <button mat-button (click)="unstack()" [disabled]="saving()">{{ I18N.stacks.unstack | translate }}</button> }
          <button mat-flat-button data-stack-save (click)="save()" [disabled]="saving() || loading() || !dirty() || !valid()">{{ (stack() ? I18N.ui.buttons.save : I18N.stacks.create) | translate }}</button>
        }
      }
    </mat-dialog-actions>
  `,
})
export class StackDialogComponent implements OnInit {
  protected readonly I18N = i18nKeys();
  protected readonly STACK_MAX_MEMBERS = STACK_MAX_MEMBERS;
  readonly data = inject<StackDialogData>(MAT_DIALOG_DATA);
  private readonly api = inject(ApiService);
  private readonly stacks = inject(PhotoStackService);
  private readonly auth = inject(AuthService);
  private readonly store = inject(GalleryStore);
  private readonly actions = inject(StackActionsService);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialogRef<StackDialogComponent>);
  private readonly destroyRef = inject(DestroyRef);
  private readonly session = this.stacks.context();
  private readonly initialEdition = this.auth.isEdition();
  private readonly cancelLoad = new Subject<void>();
  private retryAction: 'load' | 'save' | 'add' = 'load';
  private readonly closeButton = viewChild<ElementRef<HTMLButtonElement>>('closeButton');
  private readonly thumbnails = viewChildren<ElementRef<HTMLButtonElement>>('thumbnail');
  private closing = false;
  private loadSequence = 0;
  readonly stack = signal<PhotoStack | null>(null);
  readonly paths = signal<string[]>([]);
  readonly cover = signal('');
  readonly focused = signal('');
  readonly regrouping = signal(!this.data.stackId && !this.data.skippable);
  readonly mode = signal<StackRegroupMode>('combine');
  readonly explicitPaths = signal([...new Set(this.data.paths ?? [])]);
  readonly preview = signal<StackRegroupPreview | null>(null);
  readonly previewCurrent = signal(false);
  private readonly excluded = new Set<string>();
  readonly sourceEffects = computed(() => regroupSourceEffects(this.regrouping() ? this.preview() : null, this.paths()));
  readonly extraCount = computed(() => this.regrouping() ? this.paths().filter(path => !this.explicitPaths().includes(path)).length : 0);
  readonly ready = signal(false);
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly error = signal<'error' | 'conflict' | 'unavailable' | 'regroup_limit' | null>(null);
  readonly editable = computed(() => this.auth.isEdition() && (!this.data.stackId || this.stack()?.editable === true));
  readonly memberCount = computed(() => this.stack()?.members.length ?? this.paths().length);
  readonly additions = computed(() => (this.data.selectedPaths ?? []).filter(path => !this.paths().includes(path)));
  readonly skippable = computed(() => this.data.skippable === true && this.editable() && !this.stack()
    && this.paths().length < STACK_MIN_MEMBERS);
  readonly valid = computed(() => this.paths().length <= STACK_MAX_MEMBERS
    && (this.regrouping() ? this.previewCurrent() && this.paths().length >= STACK_MIN_MEMBERS
      : this.stack() !== null || this.paths().length >= STACK_MIN_MEMBERS));
  readonly dirty = computed(() => {
    const previous = this.stack();
    return this.regrouping() || !previous || previous.cover_path !== this.cover() || JSON.stringify(previous.members.map(m => m.path)) !== JSON.stringify(this.paths());
  });

  constructor() {
    this.dialog.keydownEvents().pipe(takeUntilDestroyed()).subscribe(event => this.onKeydown(event));
    this.dialog.beforeClosed().pipe(takeUntilDestroyed()).subscribe(() => { this.closing = true; this.cancelLoad.next(); });
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) this.invalidate();
    });
    effect(() => {
      this.auth.identity();
      if (!this.session() || this.auth.isEdition() !== this.initialEdition) this.invalidate();
    });
  }

  ngOnInit(): void { void this.load(); }
  private current(): boolean { return !this.destroyRef.destroyed && !this.closing && this.session() && this.auth.isEdition() === this.initialEdition; }
  private invalidate(): void {
    this.closing = true; this.cancelLoad.next(); this.paths.set([]); this.stack.set(null); this.ready.set(false); this.dialog.close();
  }
  close(): void { if (!this.saving()) this.dialog.close(); }
  skipSuggestion(): void { if (this.skippable() && !this.saving()) this.dialog.close(SKIP_SUGGESTION); }

  async load(): Promise<void> {
    if (this.regrouping()) { await this.loadPreview(); return; }
    if (!this.current() || this.saving()) return;
    const sequence = ++this.loadSequence;
    this.loading.set(true); this.ready.set(false); this.error.set(null);
    try {
      if (this.data.stackId) {
        const stack = await firstValueFrom(this.stacks.get(this.data.stackId).pipe(takeUntil(this.cancelLoad), takeUntilDestroyed(this.destroyRef)));
        if (!this.current() || sequence !== this.loadSequence) return;
        if (!stack) { this.error.set('unavailable'); return; }
        this.stack.set(stack); this.paths.set(stack.members.map(member => member.path)); this.cover.set(stack.cover_path);
      } else {
        const paths = [...new Set(this.data.paths ?? [])];
        if (paths.length < STACK_MIN_MEMBERS || paths.length > STACK_MAX_MEMBERS) { this.error.set('unavailable'); return; }
        const photos: Photo[] = [];
        for (let offset = 0; offset < paths.length; offset += BY_PATHS_MAX) {
          const res = await firstValueFrom(this.api.post<{ photos: Photo[]; missing: string[] }>('/photos/by_paths',
            { paths: paths.slice(offset, offset + BY_PATHS_MAX) }).pipe(takeUntil(this.cancelLoad), takeUntilDestroyed(this.destroyRef)));
          if (!this.current() || sequence !== this.loadSequence) return;
          photos.push(...res.photos);
        }
        if (photos.length !== paths.length) { this.error.set('unavailable'); return; }
        const byPath = new Map(photos.map(photo => [photo.path, photo]));
        this.paths.set(paths.sort((a, b) => captureDateKey(byPath.get(a)?.date_taken).localeCompare(captureDateKey(byPath.get(b)?.date_taken)) || a.localeCompare(b)));
        this.cover.set(this.data.activePath && paths.includes(this.data.activePath) ? this.data.activePath : (this.data.paths?.[0] ?? paths[0]));
      }
      this.focused.set(this.paths().includes(this.data.activePath ?? '') ? this.data.activePath! : this.cover());
      this.ready.set(true);
    } catch { if (this.current() && sequence === this.loadSequence) this.error.set('error'); }
    finally { if (this.current() && sequence === this.loadSequence) this.loading.set(false); }
  }

  async loadPreview(): Promise<void> {
    if (!this.current() || this.saving()) return;
    if (this.explicitPaths().length < STACK_MIN_MEMBERS || this.explicitPaths().length > STACK_MAX_MEMBERS) {
      this.error.set('unavailable'); return;
    }
    const sequence = ++this.loadSequence;
    this.cancelLoad.next();
    this.loading.set(true); this.previewCurrent.set(false); this.error.set(null); this.retryAction = 'load';
    const previous = this.ready() ? { paths: this.paths(), cover: this.cover() } : null;
    try {
      const preview = await firstValueFrom(this.stacks.previewRegroup(this.explicitPaths(), this.mode())
        .pipe(takeUntil(this.cancelLoad), takeUntilDestroyed(this.destroyRef)));
      if (!this.current() || sequence !== this.loadSequence) return;
      const draft = reconcileRegroupDraft(preview, previous, this.excluded);
      this.preview.set(preview); this.paths.set(draft.paths); this.cover.set(draft.cover);
      if (!draft.paths.includes(this.focused())) this.focused.set(draft.cover);
      this.previewCurrent.set(true); this.ready.set(true);
    } catch (failure) {
      if (this.current() && sequence === this.loadSequence) this.showFailure(failure);
    } finally { if (this.current() && sequence === this.loadSequence) this.loading.set(false); }
  }
  changeMode(mode: StackRegroupMode): void {
    if (!this.current() || !this.editable() || this.saving() || mode === this.mode()) return;
    this.mode.set(mode); void this.loadPreview();
  }
  retry(): void {
    if (this.retryAction === 'add') void this.addSelected();
    else if (this.retryAction === 'save' && this.error() === 'error') void this.save();
    else void this.load();
  }
  focusMember(path: string): void {
    if (this.current() && !this.saving() && this.paths().includes(path)) this.focused.set(path);
  }
  private onKeydown(event: KeyboardEvent): void {
    if (!this.current() || this.saving() || event.defaultPrevented || isTypingContext(event)
      || event.isComposing || event.keyCode === 229 || event.ctrlKey || event.metaKey || event.altKey || event.shiftKey
      || !['ArrowLeft', 'ArrowRight'].includes(event.key)
      || (event.target as HTMLElement | null)?.closest('[role="slider"], [role="radiogroup"], input, select')) return;
    const index = this.paths().indexOf(this.focused());
    const next = this.paths()[index + (event.key === 'ArrowRight' ? 1 : -1)];
    event.preventDefault(); event.stopPropagation();
    if (next) {
      this.focusMember(next);
      const button = this.thumbnails()[this.paths().indexOf(next)]?.nativeElement;
      button?.focus({ preventScroll: true }); button?.scrollIntoView?.({ block: 'nearest', inline: 'nearest' });
    }
  }
  private showFailure(failure: unknown): void {
    const status = (failure as { status?: number }).status;
    this.error.set(status === 422 ? 'regroup_limit' : MUTATION_FAILURE[status ?? 0] ?? 'error');
    if (this.regrouping() && status !== undefined && [403, 404, 409, 422].includes(status)) this.previewCurrent.set(false);
  }

  setCover(path: string): void { if (this.current() && this.editable() && !this.saving() && !this.loading() && this.paths().includes(path)) this.cover.set(path); }
  move(index: number, delta: number): void {
    if (!this.current() || !this.editable() || this.saving() || this.loading()) return;
    const paths = [...this.paths()]; const target = index + delta;
    if (index < 0 || index >= paths.length || target < 0 || target >= paths.length) return;
    [paths[index], paths[target]] = [paths[target], paths[index]]; this.paths.set(paths);
  }
  remove(path: string): void {
    if (!this.current() || !this.editable() || this.saving() || this.loading()) return;
    const index = this.paths().indexOf(path);
    if (index < 0) return;
    const next = this.paths()[index + 1] ?? this.paths()[index - 1] ?? '';
    const buttons = this.thumbnails();
    const removedHasFocus = buttons[index]?.nativeElement.closest('li')?.contains(document.activeElement);
    const nextButton = buttons[index + 1]?.nativeElement ?? buttons[index - 1]?.nativeElement;
    if (this.regrouping()) this.excluded.add(path);
    this.paths.update(paths => paths.filter(member => member !== path));
    if (this.focused() === path || removedHasFocus) this.focused.set(next);
    if (removedHasFocus) (nextButton ?? this.closeButton()?.nativeElement)?.focus();
    if (this.cover() === path) this.cover.set(this.paths()[0] ?? '');
  }
  async addSelected(): Promise<void> {
    if (!this.current() || !this.editable() || this.saving() || this.loading()
      || this.paths().length + this.additions().length > STACK_MAX_MEMBERS) return;
    const additions = this.additions();
    const paths = [...this.paths(), ...additions];
    const mode = this.regrouping() ? this.mode() : 'combine';
    const sequence = ++this.loadSequence;
    this.loading.set(true); this.error.set(null); this.retryAction = 'add';
    try {
      const preview = await firstValueFrom(this.stacks.previewRegroup(paths, mode)
        .pipe(takeUntil(this.cancelLoad), takeUntilDestroyed(this.destroyRef)));
      if (!this.current() || sequence !== this.loadSequence) return;
      if (preview.source_stacks.some(source => source.id !== this.stack()?.id) || this.regrouping()) {
        // Only an explicit addition crossing a source boundary changes strict edit semantics.
        const sourcePaths = this.stack()?.members.map(member => member.path) ?? [];
        sourcePaths.filter(path => !paths.includes(path)).forEach(path => this.excluded.add(path));
        additions.forEach(path => this.excluded.delete(path));
        this.explicitPaths.set(paths); this.mode.set(mode); this.regrouping.set(true);
        const draft = reconcileRegroupDraft(preview, { paths, cover: this.cover() }, this.excluded);
        this.preview.set(preview); this.paths.set(draft.paths); this.cover.set(draft.cover); this.previewCurrent.set(true);
      } else this.paths.set(paths);
    } catch (failure) { if (this.current() && sequence === this.loadSequence) this.showFailure(failure); }
    finally { if (this.current() && sequence === this.loadSequence) this.loading.set(false); }
  }
  selectMembers(): void {
    if (!this.current() || !this.ready() || this.saving()) return;
    // Select stored, permitted membership, never unsaved draft additions/removals.
    this.store.restoreSelection(this.stack()?.members.map(member => member.path) ?? this.paths()); this.dialog.close();
  }
  async openMember(path: string): Promise<void> {
    if (!this.current() || this.saving() || !this.paths().includes(path)) return;
    const allowed = () => {
      const pinned = this.store.pinnedPaths();
      return pinned === null || pinned.includes(path);
    };
    if (!allowed()) return;
    this.saving.set(true); this.error.set(null);
    try {
      const photo = await firstValueFrom(this.api.get<Photo>('/photo', { path }).pipe(takeUntil(this.cancelLoad), takeUntilDestroyed(this.destroyRef)));
      if (!this.current() || !allowed()) return;
      this.dialog.close();
      await this.stacks.navigateMember(path, photo, allowed, this.router.url.startsWith('/photo?'));
    } catch { if (this.current()) this.error.set('error'); }
    finally { if (this.current()) this.saving.set(false); }
  }
  async save(): Promise<void> {
    if (!this.current() || !this.ready() || !this.editable() || !this.valid() || !this.dirty() || this.saving() || this.loading()) return;
    const preview = this.preview();
    if (this.regrouping()) {
      if (preview && this.previewCurrent()) await this.mutate(this.stacks.regroup(preview, this.paths(), this.cover()), preview.source_stacks.length ? 'update' : 'create');
      return;
    }
    const stack = this.stack();
    await this.mutate(stack ? this.stacks.update(stack, this.paths(), this.paths().length ? this.cover() : null) : this.stacks.create(this.paths(), this.cover()), stack ? 'update' : 'create');
  }
  async unstack(): Promise<void> {
    const stack = this.stack();
    if (!this.current() || this.regrouping() || !stack || !this.editable() || this.saving() || this.loading()) return;
    await this.mutate(this.stacks.unstack(stack), 'unstack');
  }
  private async mutate(request: Observable<StackMutation>, action: 'create' | 'update' | 'unstack'): Promise<void> {
    this.saving.set(true); this.error.set(null); this.dialog.disableClose = true;
    const paths = [...new Set([...(this.stack()?.members.map(member => member.path) ?? []), ...this.paths()])];
    try {
      const applied = await this.actions.commit(request, {
        paths, action, labelKey: this.I18N.stacks.saved, session: this.session, live: () => this.current(),
      });
      if (applied) this.dialog.close(true);
    } catch (failure) {
      if (this.current()) {
        this.retryAction = 'save'; this.showFailure(failure);
      }
    } finally {
      if (this.current()) { this.saving.set(false); this.dialog.disableClose = false; }
    }
  }
}
