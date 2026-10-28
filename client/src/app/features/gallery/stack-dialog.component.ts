import { ChangeDetectionStrategy, Component, DestroyRef, OnInit, computed, effect, inject, signal } from '@angular/core';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { NavigationStart, Router } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatTooltipModule } from '@angular/material/tooltip';
import { firstValueFrom, Observable } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { PhotoStack, PhotoStackService, StackMutation } from '../../core/services/photo-stack.service';
import { UndoService } from '../../core/services/undo.service';
import { UserActivityJournal } from '../../core/agent/user-activity-journal.service';
import { i18nKeys } from '../../core/i18n/keys';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { PluralKeyPipe } from '../../shared/pipes/plural-key.pipe';
import { FilenamePipe } from '../../shared/pipes/filename.pipe';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { Photo } from '../../shared/models/photo.model';
import { GalleryStore } from './gallery.store';
import { BY_PATHS_MAX } from './gallery-filters.util';

export interface StackDialogData {
  stackId?: string;
  paths?: string[];
  activePath?: string | null;
  /** Explicit selection only. A whole-view selection must never be materialized implicitly. */
  selectedPaths?: string[];
}

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
  template: `
    <h2 mat-dialog-title>{{ (stack() ? I18N.stacks.title : I18N.stacks.create) | translate }}</h2>
    <mat-dialog-content>
      <p class="text-sm opacity-80 mb-3">{{ (editable() ? I18N.stacks.hint : I18N.stacks.read_only) | translate }}</p>
      @if (loading()) { <p role="status">{{ I18N.ui.labels.loading | translate }}</p> }
      @if (error(); as failure) {
        <p role="alert" class="my-3">{{ I18N.stacks[failure] | translate }}</p>
        <button mat-button (click)="load()" [disabled]="saving()">{{ I18N.stacks.reload | translate }}</button>
      }
      @if (ready()) {
        @if (paths().length < 2) { <p role="status" class="my-3">{{ I18N.stacks.dissolve_hint | translate }}</p> }
        <p data-stack-member-count class="text-sm mb-3">{{ paths().length | pluralKey:I18N.stacks.member_count:I18N.stacks.member_count_plural | translate:{ count: paths().length } }}</p>
        <ol class="flex flex-col gap-2 max-h-[50vh] overflow-y-auto">
          @for (path of paths(); track path; let index = $index; let first = $first; let last = $last) {
            <li class="flex flex-wrap sm:flex-nowrap items-center gap-2 rounded-lg p-2 border border-current/20" [class.border-[var(--mat-sys-primary)]]="path === cover()">
              <button class="shrink-0 rounded focus-visible:outline-2 cursor-pointer" (click)="openMember(path)" [disabled]="saving()"
                [attr.aria-label]="I18N.stacks.open_member | translate:{ path }">
                <img [src]="path | thumbnailUrl:160" [alt]="path" loading="lazy" decoding="async" class="w-20 h-16 object-contain rounded" />
              </button>
              <span data-stack-filename class="text-sm truncate min-w-0 flex-1" tabindex="0" [matTooltip]="path" [title]="path" [attr.aria-label]="path">{{ path | filename }}</span>
              @if (editable()) {
                <div class="flex items-center gap-1">
                  <button mat-button (click)="setCover(path)" [disabled]="saving()" [attr.aria-pressed]="path === cover()"
                    [attr.aria-label]="I18N.stacks.cover_for | translate:{ path }">
                    <mat-icon>{{ path === cover() ? 'star' : 'star_outline' }}</mat-icon>{{ I18N.stacks.cover | translate }}
                  </button>
                  <button mat-icon-button (click)="move(index, -1)" [disabled]="saving() || first" [attr.aria-label]="I18N.stacks.move_up | translate:{ path }"><mat-icon>arrow_upward</mat-icon></button>
                  <button mat-icon-button (click)="move(index, 1)" [disabled]="saving() || last" [attr.aria-label]="I18N.stacks.move_down | translate:{ path }"><mat-icon>arrow_downward</mat-icon></button>
                  <button mat-icon-button (click)="remove(path)" [disabled]="saving()" [attr.aria-label]="I18N.stacks.remove | translate:{ path }"><mat-icon>remove_circle_outline</mat-icon></button>
                </div>
              } @else if (path === cover()) { <mat-icon [attr.aria-label]="I18N.stacks.cover | translate">star</mat-icon> }
            </li>
          }
        </ol>
        @if (editable() && additions().length) {
          <button mat-button (click)="addSelected()" [disabled]="saving() || paths().length + additions().length > 1000">{{ I18N.stacks.add_selected | translate:{ count: additions().length } }}</button>
        }
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="close()" [disabled]="saving()">{{ I18N.dialog.close | translate }}</button>
      @if (ready()) {
        @if (stack()) {
          <button mat-button (click)="selectMembers()" [disabled]="saving()">{{ I18N.stacks.select_all | translate:{ count: memberCount() } }}</button>
        }
        @if (editable()) {
          @if (stack()) { <button mat-button (click)="unstack()" [disabled]="saving()">{{ I18N.stacks.unstack | translate }}</button> }
          <button mat-flat-button (click)="save()" [disabled]="saving() || !dirty() || !valid()">{{ (stack() ? I18N.ui.buttons.save : I18N.stacks.create) | translate }}</button>
        }
      }
    </mat-dialog-actions>
  `,
})
export class StackDialogComponent implements OnInit {
  protected readonly I18N = i18nKeys();
  readonly data = inject<StackDialogData>(MAT_DIALOG_DATA);
  private readonly api = inject(ApiService);
  private readonly stacks = inject(PhotoStackService);
  private readonly auth = inject(AuthService);
  private readonly store = inject(GalleryStore);
  private readonly journal = inject(UserActivityJournal);
  private readonly undo = inject(UndoService);
  private readonly router = inject(Router);
  private readonly dialog = inject(MatDialogRef<StackDialogComponent>);
  private readonly destroyRef = inject(DestroyRef);
  private readonly session = this.stacks.context();
  private closing = false;
  private loadSequence = 0;
  readonly stack = signal<PhotoStack | null>(null);
  readonly paths = signal<string[]>([]);
  readonly cover = signal('');
  readonly ready = signal(false);
  readonly loading = signal(false);
  readonly saving = signal(false);
  readonly error = signal<'error' | 'conflict' | 'unavailable' | null>(null);
  readonly editable = computed(() => this.auth.isEdition() && (!this.data.stackId || this.stack()?.editable === true));
  readonly memberCount = computed(() => this.stack()?.members.length ?? this.paths().length);
  readonly additions = computed(() => (this.data.selectedPaths ?? []).filter(path => !this.paths().includes(path)));
  readonly valid = computed(() => this.paths().length <= 1000 && (this.stack() !== null || this.paths().length >= 2));
  readonly dirty = computed(() => {
    const previous = this.stack();
    return !previous || previous.cover_path !== this.cover() || JSON.stringify(previous.members.map(m => m.path)) !== JSON.stringify(this.paths());
  });

  constructor() {
    this.dialog.beforeClosed().pipe(takeUntilDestroyed()).subscribe(() => { this.closing = true; });
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) this.invalidate();
    });
    effect(() => {
      this.auth.identity();
      if (!this.session()) this.invalidate();
    });
  }

  ngOnInit(): void { void this.load(); }
  private current(): boolean { return !this.destroyRef.destroyed && !this.closing && this.session(); }
  private invalidate(): void {
    this.closing = true; this.paths.set([]); this.stack.set(null); this.ready.set(false); this.dialog.close();
  }
  close(): void { if (!this.saving()) this.dialog.close(); }

  async load(): Promise<void> {
    if (!this.current() || this.saving()) return;
    const sequence = ++this.loadSequence;
    this.loading.set(true); this.ready.set(false); this.error.set(null);
    try {
      if (this.data.stackId) {
        const stack = await firstValueFrom(this.stacks.get(this.data.stackId).pipe(takeUntilDestroyed(this.destroyRef)));
        if (!this.current() || sequence !== this.loadSequence) return;
        if (!stack) { this.error.set('unavailable'); return; }
        this.stack.set(stack); this.paths.set(stack.members.map(member => member.path)); this.cover.set(stack.cover_path);
      } else {
        const paths = [...new Set(this.data.paths ?? [])];
        if (paths.length < 2 || paths.length > 1000) { this.error.set('unavailable'); return; }
        const photos: Photo[] = [];
        for (let offset = 0; offset < paths.length; offset += BY_PATHS_MAX) {
          const res = await firstValueFrom(this.api.post<{ photos: Photo[]; missing: string[] }>('/photos/by_paths',
            { paths: paths.slice(offset, offset + BY_PATHS_MAX) }).pipe(takeUntilDestroyed(this.destroyRef)));
          if (!this.current() || sequence !== this.loadSequence) return;
          photos.push(...res.photos);
        }
        if (photos.length !== paths.length) { this.error.set('unavailable'); return; }
        const byPath = new Map(photos.map(photo => [photo.path, photo]));
        this.paths.set(paths.sort((a, b) => captureDateKey(byPath.get(a)?.date_taken).localeCompare(captureDateKey(byPath.get(b)?.date_taken)) || a.localeCompare(b)));
        this.cover.set(this.data.activePath && paths.includes(this.data.activePath) ? this.data.activePath : (this.data.paths?.[0] ?? paths[0]));
      }
      this.ready.set(true);
    } catch { if (this.current() && sequence === this.loadSequence) this.error.set('error'); }
    finally { if (this.current() && sequence === this.loadSequence) this.loading.set(false); }
  }

  setCover(path: string): void { if (this.editable() && !this.saving() && this.paths().includes(path)) this.cover.set(path); }
  move(index: number, delta: number): void {
    if (!this.editable() || this.saving()) return;
    const paths = [...this.paths()]; const target = index + delta;
    if (index < 0 || index >= paths.length || target < 0 || target >= paths.length) return;
    [paths[index], paths[target]] = [paths[target], paths[index]]; this.paths.set(paths);
  }
  remove(path: string): void {
    if (!this.editable() || this.saving()) return;
    this.paths.update(paths => paths.filter(member => member !== path));
    if (this.cover() === path) this.cover.set(this.paths()[0] ?? '');
  }
  addSelected(): void {
    if (!this.editable() || this.saving() || this.paths().length + this.additions().length > 1000) return;
    this.paths.update(paths => [...paths, ...this.additions()]);
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
      const photo = await firstValueFrom(this.api.get<Photo>('/photo', { path }));
      if (!this.current() || !allowed()) return;
      this.dialog.close();
      await this.stacks.navigateMember(path, photo, allowed, this.router.url.startsWith('/photo?'));
    } catch { if (this.current()) this.error.set('error'); }
    finally { if (this.current()) this.saving.set(false); }
  }
  async save(): Promise<void> {
    if (!this.current() || !this.ready() || !this.editable() || !this.valid() || !this.dirty() || this.saving()) return;
    const stack = this.stack();
    await this.mutate(stack ? this.stacks.update(stack, this.paths(), this.paths().length ? this.cover() : null) : this.stacks.create(this.paths(), this.cover()), stack ? 'update' : 'create');
  }
  async unstack(): Promise<void> {
    const stack = this.stack();
    if (!this.current() || !stack || !this.editable() || this.saving()) return;
    await this.mutate(this.stacks.unstack(stack), 'unstack');
  }
  private async mutate(request: Observable<StackMutation>, action: 'create' | 'update' | 'unstack'): Promise<void> {
    this.saving.set(true); this.error.set(null); this.dialog.disableClose = true;
    const paths = [...new Set([...(this.stack()?.members.map(member => member.path) ?? []), ...this.paths()])];
    try {
      const result = await firstValueFrom(request);
      if (!this.current() || !this.auth.isEdition()) return;
      this.journal.record('stack', paths, action);
      void this.store.refreshPaths(null);
      const entryId = result.undo?.entry_id;
      if (entryId !== undefined) {
        this.undo.register({ labelKey: this.I18N.stacks.saved, undo: async () => {
          if (!this.session() || !this.auth.isEdition()) throw new Error('Stack session expired');
          await firstValueFrom(this.stacks.revert(entryId));
          if (!this.session() || !this.auth.isEdition()) throw new Error('Stack session expired');
          this.journal.record('stack', paths, 'undo'); await this.store.refreshPaths(null);
        } });
      }
      this.dialog.close(true);
    } catch (failure) {
      if (this.current()) {
        const status = (failure as { status?: number }).status;
        this.error.set(status === 409 ? 'conflict' : status === 404 || status === 403 ? 'unavailable' : 'error');
      }
    } finally {
      if (this.current()) { this.saving.set(false); this.dialog.disableClose = false; }
    }
  }
}
