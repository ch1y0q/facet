import { ChangeDetectionStrategy, Component, DestroyRef, effect, inject, signal } from '@angular/core';
import { NavigationStart, Router } from '@angular/router';
import { MAT_DIALOG_DATA, MatDialog, MatDialogModule, MatDialogRef } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { firstValueFrom } from 'rxjs';
import { takeUntilDestroyed } from '@angular/core/rxjs-interop';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { PhotoStackService } from '../../core/services/photo-stack.service';
import { components } from '../../core/api/schema';
import { i18nKeys } from '../../core/i18n/keys';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { FilenamePipe } from '../../shared/pipes/filename.pipe';
import { PluralKeyPipe } from '../../shared/pipes/plural-key.pipe';
import { ThumbnailUrlPipe } from '../../shared/pipes/thumbnail-url.pipe';
import { GalleryStore } from './gallery.store';
import { StackDialogComponent } from './stack-dialog.component';

type Suggestion = components['schemas']['StackSuggestion'];

@Component({
  selector: 'app-stack-suggestions-dialog',
  imports: [MatDialogModule, MatButtonModule, TranslatePipe, ThumbnailUrlPipe, FilenamePipe, PluralKeyPipe],
  changeDetection: ChangeDetectionStrategy.OnPush,
  template: `
    <h2 mat-dialog-title>{{ I18N.stacks.suggestions | translate }}</h2>
    <mat-dialog-content>
      <p class="text-sm mb-3">{{ I18N.stacks.suggestions_hint | translate }}</p>
      @if (loading()) { <p role="status">{{ I18N.ui.labels.loading | translate }}</p> }
      @if (failed()) { <p role="alert">{{ I18N.stacks.error | translate }}</p> }
      @if (!loading() && !failed() && !candidates().length) {
        <p role="status">{{ I18N.stacks.suggestions_empty | translate }}</p>
      }
      @for (candidate of candidates(); track candidate.key) {
        <section class="border-b border-current/20 py-3">
          <h3 class="font-medium">{{ (candidate.kind === 'burst' ? I18N.stacks.suggestion_burst : I18N.stacks.suggestion_duplicate) | translate }}</h3>
          <p>{{ candidate.paths.length | pluralKey:I18N.stacks.member_count:I18N.stacks.member_count_plural | translate:{ count: candidate.paths.length } }}</p>
          <div class="flex gap-2 overflow-x-auto my-2">
            @for (path of candidate.paths; track path) {
              <img [src]="path | thumbnailUrl:160" [alt]="path | filename" loading="lazy" decoding="async" class="w-20 h-20 object-contain shrink-0" />
            }
          </div>
          <button mat-flat-button (click)="review(candidate)" [disabled]="!auth.isEdition() || reviewing()">{{ I18N.stacks.suggestion_review | translate }}</button>
          <button mat-button (click)="dismiss(candidate.key)" [disabled]="reviewing()">{{ I18N.stacks.suggestion_dismiss | translate }}</button>
        </section>
      }
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button (click)="load()" [disabled]="loading() || reviewing()">{{ I18N.stacks.reload | translate }}</button>
      <button mat-button mat-dialog-close>{{ I18N.dialog.close | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class StackSuggestionsDialogComponent {
  protected readonly I18N = i18nKeys();
  protected readonly auth = inject(AuthService);
  private readonly api = inject(ApiService);
  private readonly stacks = inject(PhotoStackService);
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
  private readonly dismissed = new Set<string>();
  readonly candidates = signal<Suggestion[]>([]);
  readonly loading = signal(false);
  readonly failed = signal(false);
  readonly reviewing = signal(false);

  constructor() {
    this.ref.beforeClosed().pipe(takeUntilDestroyed()).subscribe(() => { this.closed = true; });
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
    if (!this.current() || this.reviewing()) return;
    const sequence = ++this.sequence;
    this.loading.set(true); this.failed.set(false); this.candidates.set([]);
    try {
      const result = await firstValueFrom(this.api.post<components['schemas']['StackSuggestionsResponse']>(
        '/stacks/suggestions', { filters: this.data.filters }).pipe(takeUntilDestroyed(this.destroyRef)));
      if (this.current() && sequence === this.sequence)
        this.candidates.set(result.suggestions.filter(candidate => !this.dismissed.has(candidate.key)));
    } catch {
      if (this.current() && sequence === this.sequence) this.failed.set(true);
    } finally {
      if (this.current() && sequence === this.sequence) this.loading.set(false);
    }
  }

  dismiss(key: string): void {
    if (!this.current() || this.reviewing()) return;
    this.dismissed.add(key); this.candidates.update(items => items.filter(item => item.key !== key));
  }

  async review(candidate: Suggestion): Promise<void> {
    if (!this.current() || !this.auth.isEdition() || this.reviewing()
      || !this.candidates().includes(candidate)) return;
    this.reviewing.set(true);
    try {
      const ref = this.dialogs.open(StackDialogComponent, { width: '900px', maxWidth: '96vw', data: {
        paths: [...candidate.paths], activePath: candidate.cover_path,
      } });
      this.editor = ref;
      await firstValueFrom(ref.afterClosed().pipe(takeUntilDestroyed(this.destroyRef)));
    } catch {
      if (this.current()) this.failed.set(true);
    } finally {
      this.editor = null;
      if (this.current()) { this.reviewing.set(false); await this.load(); }
    }
  }
}
