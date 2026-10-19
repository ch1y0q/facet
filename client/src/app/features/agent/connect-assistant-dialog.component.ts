import { ChangeDetectionStrategy, Component, ElementRef, Injector, OnDestroy, afterNextRender, computed, inject, signal, viewChild } from '@angular/core';
import { DatePipe } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { HttpErrorResponse } from '@angular/common/http';
import { MatDialogModule } from '@angular/material/dialog';
import { MatButtonModule } from '@angular/material/button';
import { MatIconModule } from '@angular/material/icon';
import { MatSnackBar } from '@angular/material/snack-bar';
import { firstValueFrom } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { AgentBridgeService } from '../../core/agent/agent-bridge.service';
import { AgentWebMcpService } from '../../core/agent/agent-web-mcp.service';
import { McpTokenItem } from '../../core/api/types';
import { TranslatePipe } from '../../shared/pipes/translate.pipe';
import { i18nKeys } from '../../core/i18n/keys';

type TokenLevel = McpTokenItem['level'];

interface LevelOption {
  value: TokenLevel;
  label: string;
}

@Component({
  selector: 'app-connect-assistant-dialog',
  standalone: true,
  imports: [FormsModule, DatePipe, MatDialogModule, MatButtonModule, MatIconModule, TranslatePipe],
  changeDetection: ChangeDetectionStrategy.Eager,
  template: `
    <h2 mat-dialog-title>{{ I18N.dialog.connect_assistant.title | translate }}</h2>
    <mat-dialog-content class="flex flex-col gap-4">
      <p class="sr-only" role="status" aria-live="polite" data-testid="live-region">{{ liveMessage() }}</p>
      <p class="text-sm opacity-80">{{ I18N.dialog.connect_assistant.intro | translate }}</p>

      <section class="flex flex-col gap-1" aria-labelledby="connect-bridge-heading">
        <h3 id="connect-bridge-heading" class="text-sm font-medium">{{ I18N.dialog.connect_assistant.bridge_heading | translate }}</h3>
        <p class="text-sm flex items-center gap-2" data-testid="bridge-status">
          <mat-icon class="!text-base !w-4 !h-4" [class.text-green-600]="bridgeConnected()" [class.opacity-60]="!bridgeConnected()">{{ bridgeConnected() ? 'link' : 'link_off' }}</mat-icon>
          <span>{{ bridgeStatusKey() | translate: { id: tabId } }}</span>
        </p>
        @if (insecureContext()) {
          <p class="text-xs opacity-70" data-testid="insecure-note">{{ I18N.dialog.connect_assistant.insecure_context | translate }}</p>
        }
      </section>

      @if (createdToken(); as created) {
        <section class="flex flex-col gap-2 rounded-lg border border-amber-500/60 p-3" aria-labelledby="connect-reveal-heading" data-testid="reveal">
          <h3 id="connect-reveal-heading" class="text-sm font-medium">{{ I18N.dialog.connect_assistant.reveal_heading | translate }}</h3>
          <p class="text-xs text-amber-800 dark:text-amber-300">{{ I18N.dialog.connect_assistant.reveal_warning | translate }}</p>
          <p class="text-xs" data-testid="granted-level">{{ I18N.dialog.connect_assistant.reveal_level | translate: { level: (createdLevelKey() | translate) } }}</p>
          <div class="flex items-center gap-2">
            <code #tokenField tabindex="-1" class="flex-1 break-all rounded bg-black/10 px-2 py-1 text-xs" data-testid="token-value">{{ created.token }}</code>
            <button mat-stroked-button type="button" [attr.aria-label]="I18N.dialog.connect_assistant.copy_token_aria | translate" (click)="copy(created.token)">
              {{ (copied() === 'token' ? I18N.dialog.connect_assistant.copied : I18N.dialog.connect_assistant.copy) | translate }}
            </button>
          </div>
        </section>
      }

      <section class="flex flex-col gap-2" aria-labelledby="connect-snippet-heading">
        <h3 id="connect-snippet-heading" class="text-sm font-medium">{{ I18N.dialog.connect_assistant.snippet_heading | translate }}</h3>
        <div class="flex items-start gap-2">
          <pre class="flex-1 overflow-x-auto whitespace-pre-wrap break-all rounded bg-black/10 p-2 text-xs" data-testid="snippet">{{ snippet() }}</pre>
          <button mat-stroked-button type="button" [attr.aria-label]="I18N.dialog.connect_assistant.copy_snippet_aria | translate" (click)="copy(snippet(), 'snippet')">
            {{ (copied() === 'snippet' ? I18N.dialog.connect_assistant.copied : I18N.dialog.connect_assistant.copy) | translate }}
          </button>
        </div>
      </section>

      <section class="flex flex-col gap-2" aria-labelledby="connect-mint-heading">
        <h3 id="connect-mint-heading" class="text-sm font-medium">{{ I18N.dialog.connect_assistant.mint_heading | translate }}</h3>
        <label class="flex flex-col gap-1 text-sm">
          <span>{{ I18N.dialog.connect_assistant.name_label | translate }}</span>
          <input class="rounded border border-current/30 bg-transparent px-2 py-1" maxlength="100" name="token-name"
                 [placeholder]="I18N.dialog.connect_assistant.name_placeholder | translate"
                 [ngModel]="name()" (ngModelChange)="name.set($event)" (keydown.enter)="mint()" />
        </label>
        <label class="flex flex-col gap-1 text-sm">
          <span>{{ I18N.dialog.connect_assistant.level_label | translate }}</span>
          <select class="rounded border border-current/30 bg-transparent px-2 py-1" name="token-level" [(ngModel)]="level">
            @for (option of levelOptions(); track option.value) {
              <option class="text-black" [value]="option.value">{{ option.label | translate }}</option>
            }
          </select>
        </label>
        @if (error(); as message) {
          <p class="text-sm text-red-700 dark:text-red-400" role="alert">{{ message | translate }}</p>
        }
        <div>
          <button mat-flat-button type="button" [disabled]="!canMint()" (click)="mint()">
            {{ I18N.dialog.connect_assistant.mint | translate }}
          </button>
        </div>
      </section>

      <section class="flex flex-col gap-2" aria-labelledby="connect-tokens-heading">
        <h3 #tokensHeading id="connect-tokens-heading" tabindex="-1" class="text-sm font-medium">{{ I18N.dialog.connect_assistant.tokens_heading | translate }}</h3>
        @for (token of tokens(); track token.id) {
          <div class="flex flex-wrap items-center gap-2 rounded border border-current/20 px-2 py-1 text-sm" data-testid="token-row">
            <span class="font-medium">{{ token.name }}</span>
            <code class="text-xs opacity-70">{{ token.token_prefix }}…</code>
            @if (token.level === 'edition') {
              <span class="rounded bg-amber-500/20 px-1.5 text-xs text-amber-800 dark:text-amber-300" data-testid="edition-badge">{{ I18N.dialog.connect_assistant.level_edition_badge | translate }}</span>
            }
            <span class="text-xs opacity-70">{{ I18N.dialog.connect_assistant.col_created | translate }} {{ token.created_at | date: 'dd/MM/yyyy' }}</span>
            <span class="text-xs opacity-70">
              {{ I18N.dialog.connect_assistant.col_last_used | translate }}
              {{ token.last_used_at ? (token.last_used_at | date: 'dd/MM/yyyy') : (I18N.dialog.connect_assistant.never_used | translate) }}
            </span>
            <span class="ml-auto flex items-center gap-1">
              @if (confirmRevokeId() === token.id) {
                <span class="text-xs">{{ I18N.dialog.connect_assistant.revoke_confirm | translate }}</span>
                <button mat-button type="button" [attr.aria-label]="I18N.dialog.connect_assistant.revoke_confirm_yes_aria | translate: { name: token.name }" (click)="revoke(token.id)">{{ I18N.dialog.connect_assistant.revoke_confirm_yes | translate }}</button>
                <button mat-button type="button" [attr.aria-label]="I18N.dialog.connect_assistant.cancel_revoke_aria | translate: { name: token.name }" (click)="confirmRevokeId.set(null)">{{ I18N.dialog.cancel | translate }}</button>
              } @else {
                <button mat-button type="button" [attr.aria-label]="I18N.dialog.connect_assistant.revoke_aria | translate: { name: token.name }" (click)="confirmRevokeId.set(token.id)">{{ I18N.dialog.connect_assistant.revoke | translate }}</button>
              }
            </span>
          </div>
        } @empty {
          <p class="text-sm opacity-70">{{ I18N.dialog.connect_assistant.no_tokens | translate }}</p>
        }
      </section>
    </mat-dialog-content>
    <mat-dialog-actions align="end">
      <button mat-button mat-dialog-close>{{ I18N.dialog.close | translate }}</button>
    </mat-dialog-actions>
  `,
})
export class ConnectAssistantDialogComponent implements OnDestroy {
  protected readonly I18N = i18nKeys();
  private readonly api = inject(ApiService);
  private readonly auth = inject(AuthService);
  private readonly i18n = inject(I18nService);
  private readonly snackBar = inject(MatSnackBar);
  private readonly bridge = inject(AgentBridgeService);
  private readonly webMcp = inject(AgentWebMcpService);

  protected readonly tabId = this.bridge.tabId;
  private readonly injector = inject(Injector);
  private readonly tokenField = viewChild<ElementRef<HTMLElement>>('tokenField');
  private readonly tokensHeading = viewChild<ElementRef<HTMLElement>>('tokensHeading');
  protected readonly name = signal('');
  protected level: TokenLevel = 'readonly';
  protected readonly tokens = signal<McpTokenItem[]>([]);
  /** The just-minted plaintext. Held only here, cleared when the dialog closes; never stored or routed. */
  protected readonly createdToken = signal<{ token: string; level: TokenLevel } | null>(null);
  protected readonly busy = signal(false);
  protected readonly canMint = computed(() => this.name().trim().length > 0 && !this.busy());
  /** Spoken by the polite live region: the mint, and the copy, happen where a screen-reader user is not looking. */
  protected readonly liveMessage = signal('');
  protected readonly error = signal<string | null>(null);
  protected readonly confirmRevokeId = signal<number | null>(null);
  protected readonly copied = signal<'token' | 'snippet' | null>(null);

  protected readonly bridgeConnected = computed(() => this.bridge.connected());
  protected readonly bridgeStatusKey = computed(() =>
    this.bridgeConnected()
      ? this.I18N.dialog.connect_assistant.bridge_connected
      : this.I18N.dialog.connect_assistant.bridge_not_connected,
  );
  protected readonly insecureContext = computed(() => this.webMcp.state() === 'insecure_context');

  /**
   * Only the grants the server will honour: an open install holds `readonly` at most, `user` is a
   * multi-user account concept (a single password has no such rung), `edition` needs an edition session.
   */
  protected readonly levelOptions = computed<LevelOption[]>(() => {
    const options: LevelOption[] = [{ value: 'readonly', label: this.I18N.dialog.connect_assistant.level_readonly }];
    if (!this.auth.isMultiUser() && !this.auth.loginPasswordRequired()) return options;
    if (this.auth.isMultiUser()) options.push({ value: 'user', label: this.I18N.dialog.connect_assistant.level_user });
    if (this.auth.isEdition()) options.push({ value: 'edition', label: this.I18N.dialog.connect_assistant.level_edition });
    return options;
  });

  /** The level the server actually granted, which it may have capped below the one requested. */
  protected readonly createdLevelKey = computed(() => {
    const level = this.createdToken()?.level ?? 'readonly';
    const keys = this.I18N.dialog.connect_assistant;
    return level === 'edition' ? keys.level_edition : level === 'user' ? keys.level_user : keys.level_readonly;
  });

  protected readonly snippet = computed(() => {
    const token = this.createdToken()?.token ?? this.i18n.t(this.I18N.dialog.connect_assistant.snippet_placeholder_token);
    return `claude mcp add --transport http facet ${location.origin}/mcp --header "Authorization: Bearer ${token}"`;
  });

  constructor() {
    void this.refresh();
  }

  ngOnDestroy(): void {
    this.createdToken.set(null);
  }

  private async refresh(): Promise<void> {
    try {
      this.tokens.set((await firstValueFrom(this.api.listMcpTokens())).tokens.filter(t => !t.revoked));
    } catch {
      this.error.set(this.I18N.dialog.connect_assistant.load_failed);
    }
  }

  protected async mint(): Promise<void> {
    const name = this.name().trim();
    if (!name || this.busy()) return;
    this.busy.set(true);
    this.error.set(null);
    try {
      const created = await firstValueFrom(this.api.createMcpToken({ name, level: this.level }));
      this.createdToken.set({ token: created.token, level: created.level });
      this.name.set('');
      this.liveMessage.set(this.i18n.t(this.I18N.dialog.connect_assistant.token_created_announce, { name: created.name }));
      afterNextRender(() => this.tokenField()?.nativeElement.focus(), { injector: this.injector });
      await this.refresh();
    } catch (err) {
      this.error.set(err instanceof HttpErrorResponse && err.status === 412
        ? this.I18N.dialog.connect_assistant.mint_limit
        : this.I18N.dialog.connect_assistant.mint_failed);
    } finally {
      this.busy.set(false);
    }
  }

  protected async revoke(id: number): Promise<void> {
    this.confirmRevokeId.set(null);
    try {
      await firstValueFrom(this.api.revokeMcpToken(id));
      this.tokens.update(rows => rows.filter(row => row.id !== id));
      this.snackBar.open(this.i18n.t(this.I18N.dialog.connect_assistant.revoked), '', { duration: 2000 });
      this.liveMessage.set(this.i18n.t(this.I18N.dialog.connect_assistant.revoked));
      // The revoked row (and its focused button) is gone; land on the list's heading rather than on <body>.
      afterNextRender(() => this.tokensHeading()?.nativeElement.focus(), { injector: this.injector });
    } catch {
      this.error.set(this.I18N.dialog.connect_assistant.load_failed);
    }
  }

  /** `navigator.clipboard` is undefined on plain-http LAN (no secure context), so fall back to a hidden textarea. */
  protected async copy(text: string, what: 'token' | 'snippet' = 'token'): Promise<void> {
    let done = false;
    try {
      await navigator.clipboard.writeText(text);
      done = true;
    } catch {
      const area = document.createElement('textarea');
      area.value = text;
      area.setAttribute('readonly', '');
      area.style.position = 'fixed';
      area.style.opacity = '0';
      document.body.appendChild(area);
      area.select();
      try {
        done = document.execCommand('copy');
      } finally {
        area.remove();
      }
    }
    if (!done) return;
    this.copied.set(what);
    this.liveMessage.set(this.i18n.t(this.I18N.dialog.connect_assistant.copied));
    setTimeout(() => this.copied.set(null), 2000);
  }
}
