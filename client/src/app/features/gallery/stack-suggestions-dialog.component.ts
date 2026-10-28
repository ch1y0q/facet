import { ChangeDetectionStrategy, Component, DestroyRef, computed, effect, inject, linkedSignal, signal } from '@angular/core';
import { NavigationStart, Router } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialog, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatProgressBarModule } from '@angular/material/progress-bar';
import { firstValueFrom } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { PhotoStackService } from '../../core/services/photo-stack.service';
import { UndoService } from '../../core/services/undo.service';
import { components } from '../../core/api/schema';
import { i18nKeys } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { FilenamePipe } from '../../shared/pipes/filename.pipe';
import { PluralKeyPipe } from '../../shared/pipes/plural-key.pipe';
import { RENDERED_THUMBNAIL_EDGE, ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { isTypingContext } from '../../shared/utils/keyboard';
import { ZoomPanDirective } from '../../shared/directives/zoom-pan.directive';
import { GalleryStore } from './gallery.store';
import { StackActionsService } from './stack-actions.service';
import { SKIP_SUGGESTION, StackDialogComponent } from './stack-dialog.component';

type Suggestion = components['schemas']['StackSuggestion'];

// Each successful load chooses fresh preview URLs only for this dialog.
let previewSequence = 0;
function nextPreviewToken(): string { return `${Date.now().toString(36)}-${++previewSequence}`; }

/** One suggestion at a time, darkroom style: the focused frame is shown large and becomes the cover. */
@Component({
  selector: 'app-stack-suggestions-dialog',
  imports: [MatDialogModule, MatButtonModule, MatIconModule, MatProgressBarModule,
    TranslatePipe, ThumbnailUrlPipe, FilenamePipe, PluralKeyPipe, ZoomPanDirective],
  changeDetection: ChangeDetectionStrategy.OnPush,
  host: { class: 'flex flex-col h-full' },
  template: `
    <h2 mat-dialog-title>{{ I18N.stacks.suggestions | translate }}</h2>
    <mat-dialog-content class="!flex !flex-col gap-3 flex-1 min-h-0 !max-h-none">
      <p class="text-sm">{{ I18N.stacks.suggestions_hint | translate }}</p>
      @if (loading()) { <p role="status">{{ I18N.ui.labels.loading | translate }}</p> }
      @if (failed()) { <p role="alert">{{ I18N.stacks.suggestions_error | translate }}</p> }
      @if (actionFailed()) { <p role="alert">{{ I18N.stacks.suggestion_failed | translate }}</p> }
      @if (!loading() && !failed() && !candidate()) {
        <p role="status">{{ (handled() ? I18N.stacks.suggestions_done : I18N.stacks.suggestions_empty) | translate }}</p>
      }
      @if (candidate(); as current) {
        <div class="flex items-center gap-3 text-sm">
          <span class="font-medium">{{ (current.kind === 'burst' ? I18N.stacks.suggestion_burst : I18N.stacks.suggestion_duplicate) | translate }}</span>
          <span>{{ current.paths.length | pluralKey:I18N.stacks.member_count:I18N.stacks.member_count_plural | translate:{ count: current.paths.length } }}</span>
          <span class="ml-auto" role="status">{{ I18N.stacks.suggestion_progress | translate:{ position: handled() + 1, count: total() } }}</span>
        </div>
        <mat-progress-bar mode="determinate" aria-hidden="true"
                          [value]="100 * handled() / total()" />
        @if (focusedPath(); as path) {
          <div [appZoomPan]="path" #zoom="zoomPan"
               class="relative flex-1 min-h-[40vh] bg-[var(--mat-sys-surface-container)] rounded overflow-hidden cursor-grab">
            <img [src]="path | thumbnailUrl:renderedEdge:previewToken()" [alt]="path | filename"
                 decoding="async" class="absolute inset-0 w-full h-full object-contain pointer-events-none select-none"
                 [style.transform]="zoom.transform()" />
            <span class="absolute top-2 left-2 px-2 py-0.5 rounded bg-black/70 text-white text-xs">
              {{ I18N.stacks.cover | translate }} · {{ path | filename }}
            </span>
          </div>
        }
        <div class="flex items-center gap-2">
          <button mat-icon-button (click)="step(-1)" [disabled]="busy()" aria-keyshortcuts="ArrowLeft"
                  [attr.aria-label]="I18N.stacks.suggestion_cover_previous | translate"><mat-icon>chevron_left</mat-icon></button>
          <div class="flex gap-2 overflow-x-auto flex-1 p-1.5">
            @for (path of current.paths; track path; let i = $index) {
              <button type="button" class="shrink-0 rounded outline-2 outline-offset-2"
                      [style.outline-color]="i === focus() ? 'var(--mat-sys-primary)' : 'transparent'"
                      [attr.aria-pressed]="i === focus()" (click)="focus.set(i)"
                      [attr.aria-label]="I18N.stacks.cover_for | translate:{ path: (path | filename) }">
                <img [src]="path | thumbnailUrl:160:previewToken()" alt="" loading="lazy" decoding="async"
                     class="w-20 h-20 object-contain block" />
              </button>
            }
          </div>
          <button mat-icon-button (click)="step(1)" [disabled]="busy()" aria-keyshortcuts="ArrowRight"
                  [attr.aria-label]="I18N.stacks.suggestion_cover_next | translate"><mat-icon>chevron_right</mat-icon></button>
        </div>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      @if (candidate(); as current) {
        <button mat-button (click)="review(current)" [disabled]="!auth.isEdition() || busy()">{{ I18N.stacks.suggestion_edit_members | translate }}</button>
        <button mat-button (click)="skip()" aria-keyshortcuts="X" [disabled]="!auth.isEdition() || busy()">{{ I18N.stacks.suggestion_skip | translate }}</button>
        <button mat-flat-button (click)="stack()" aria-keyshortcuts="S" [disabled]="!auth.isEdition() || busy()">{{ I18N.stacks.suggestion_stack | translate }}</button>
      } @else {
        <button mat-button (click)="load()" [disabled]="loading() || busy()">{{ I18N.stacks.suggestions_reload | translate }}</button>
      }
      <button mat-button mat-dialog-close>{{ I18N.dialog.close | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class StackSuggestionsDialogComponent {
  protected readonly I18N = i18nKeys();
  protected readonly renderedEdge = RENDERED_THUMBNAIL_EDGE;
  protected readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly stacks = inject(PhotoStackService);
  private readonly undo = inject(UndoService);
  private readonly stackActions = inject(StackActionsService);
  private readonly store = inject(GalleryStore);
  private readonly dialogs = inject(MatDialog);
  private readonly router = inject(Router);
  private readonly ref = inject(MatDialogRef<StackSuggestionsDialogComponent>);
  private readonly destroyRef = inject(DestroyRef);
  private readonly data = inject<{ filters: Record<string, string> }>(MAT_DIALOG_DATA);
  private readonly scope = JSON.stringify(this.data.filters);
  private readonly session = this.stacks.context();
  private closed = false;
  private editor: MatDialogRef<StackDialogComponent> | null = null;
  private sequence = 0;
  readonly candidates = signal<Suggestion[]>([]);
  readonly candidate = computed(() => this.candidates()[0] ?? null);
  readonly focus = linkedSignal(() => {
    const current = this.candidate();
    return current ? Math.max(0, current.paths.indexOf(current.cover_path)) : 0;
  });
  readonly focusedPath = computed(() => this.candidate()?.paths[this.focus()] ?? null);
  /** Suggestions stacked or skipped in this dialog, for the progress readout. */
  readonly handled = signal(0);
  readonly total = computed(() => this.handled() + this.candidates().length);
  readonly previewToken = signal('');
  readonly loading = signal(false);
  readonly failed = signal(false);
  readonly actionFailed = signal(false);
  readonly busy = signal(false);

  constructor() {
    this.ref.beforeClosed().pipe(takeUntilDestroyed()).subscribe(() => { this.closed = true; });
    // The dialog's own key stream, not a host listener: a decision replaces the focused
    // filmstrip button, and focus falling to <body> must not end the keyboard review.
    this.ref.keydownEvents().pipe(takeUntilDestroyed()).subscribe(event => this.onKeydown(event));
    this.router.events.pipe(takeUntilDestroyed()).subscribe(event => {
      if (event instanceof NavigationStart) this.invalidate();
    });
    effect(() => {
      this.auth.identity(); this.store.filters();
      if (!this.current()) this.invalidate();
    });
    void this.load();
  }

  private invalidate(): void {
    this.closed = true; this.candidates.set([]); this.editor?.close(); this.ref.close();
  }

  private current(): boolean {
    return !this.closed && !this.destroyRef.destroyed && this.session()
      && !this.store.pinnedPaths() && JSON.stringify(this.store.filterPayload()) === this.scope;
  }

  async load(): Promise<void> {
    if (!this.current() || this.busy()) return;
    const sequence = ++this.sequence;
    this.loading.set(true); this.failed.set(false); this.candidates.set([]);
    try {
      const result = await firstValueFrom(this.api.post<components['schemas']['StackSuggestionsResponse']>(
        '/stacks/suggestions', { filters: this.data.filters }).pipe(takeUntilDestroyed(this.destroyRef)));
      if (this.current() && sequence === this.sequence) {
        this.previewToken.set(nextPreviewToken());
        this.candidates.set(result.suggestions);
      }
    } catch {
      if (this.current() && sequence === this.sequence) this.failed.set(true);
    } finally {
      if (this.current() && sequence === this.sequence) this.loading.set(false);
    }
  }

  private onKeydown(event: KeyboardEvent): void {
    if (event.defaultPrevented || this.editor || isTypingContext(event)
      || event.ctrlKey || event.metaKey || event.altKey) return;
    switch (event.key) {
      case 'ArrowLeft': this.step(-1); break;
      case 'ArrowRight': this.step(1); break;
      case 's': case 'S': void this.stack(); break;
      case 'x': case 'X': void this.skip(); break;
      default: return;
    }
    event.preventDefault();
  }

  step(delta: number): void {
    const count = this.candidate()?.paths.length ?? 0;
    if (count && !this.busy()) this.focus.update(i => (i + delta + count) % count);
  }

  async stack(): Promise<void> {
    const candidate = this.candidate();
    const cover = this.focusedPath();
    if (!candidate || !cover) return;
    await this.decide(candidate, () =>
      this.stackActions.create(candidate.paths, cover, () => this.putBack(candidate)));
  }

  /** Persisted per account: the same photos are not suggested again until their group changes. */
  async skip(): Promise<void> {
    const candidate = this.candidate();
    if (!candidate) return;
    await this.decide(candidate, async () => {
      await firstValueFrom(this.stacks.dismissSuggestion(candidate.kind, candidate.paths));
      this.undo.register({
        labelKey: this.I18N.stacks.suggestion_skipped,
        undo: async () => {
          this.stacks.assertLive(this.session);
          await firstValueFrom(this.stacks.restoreSuggestion(candidate.key));
          this.putBack(candidate);
        },
      });
    });
  }

  private async decide(candidate: Suggestion, write: () => Promise<void>): Promise<void> {
    if (!this.current() || !this.auth.isEdition() || this.busy() || this.candidate() !== candidate) return;
    this.busy.set(true); this.actionFailed.set(false);
    try {
      await write();
      if (this.current()) {
        this.candidates.update(items => items.filter(item => item.key !== candidate.key));
        this.handled.update(n => n + 1);
      }
    } catch {
      if (this.current()) this.actionFailed.set(true);
    } finally {
      if (this.current()) this.busy.set(false);
    }
  }

  private putBack(candidate: Suggestion): void {
    if (!this.current() || this.candidates().some(item => item.key === candidate.key)) return;
    this.candidates.update(items => [candidate, ...items]);
    this.handled.update(n => Math.max(0, n - 1));
  }

  /** Full editor for removing members or reordering; the focused frame is proposed as cover. */
  async review(candidate: Suggestion): Promise<void> {
    if (!this.current() || !this.auth.isEdition() || this.busy()
      || !this.candidates().includes(candidate)) return;
    this.busy.set(true);
    let skipped = false;
    try {
      const ref = this.dialogs.open(StackDialogComponent, { width: '900px', maxWidth: '96vw', data: {
        paths: [...candidate.paths], activePath: this.focusedPath() ?? candidate.cover_path, skippable: true,
      } });
      this.editor = ref;
      skipped = await firstValueFrom(ref.afterClosed().pipe(takeUntilDestroyed(this.destroyRef))) === SKIP_SUGGESTION;
    } catch {
      if (this.current()) this.failed.set(true);
    } finally {
      this.editor = null;
      if (this.current()) {
        this.busy.set(false);
        // The whole suggested group is skipped, as the Skip button would, not the members left in the editor.
        if (skipped) await this.skip();
        await this.load();
      }
    }
  }
}
