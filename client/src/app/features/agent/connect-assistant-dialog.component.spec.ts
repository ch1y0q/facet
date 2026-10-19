import type { Mock } from 'vitest';
import { signal } from '@angular/core';
import { ComponentFixture, TestBed } from '@angular/core/testing';
import { HttpErrorResponse } from '@angular/common/http';
import { MatDialogRef } from '@angular/material/dialog';
import { MatSnackBar } from '@angular/material/snack-bar';
import { of, throwError } from 'rxjs';
import { ApiService } from '../../core/services/api.service';
import { AuthService } from '../../core/services/auth.service';
import { I18nService } from '../../core/services/i18n.service';
import { AgentBridgeService } from '../../core/agent/agent-bridge.service';
import { AgentWebMcpService, WebMcpState } from '../../core/agent/agent-web-mcp.service';
import { McpTokenCreated, McpTokenItem } from '../../core/api/types';
import { ConnectAssistantDialogComponent } from './connect-assistant-dialog.component';

const TOKEN_ROW: McpTokenItem = {
  id: 7, name: 'Laptop', level: 'readonly', token_prefix: 'fct_ab12', created_at: '2026-09-03T10:00:00',
  last_used_at: null, revoked: 0, user_id: 'u',
};
const SECRET = 'fct_ab12SECRETSECRETSECRETSECRET';

describe('ConnectAssistantDialogComponent', () => {
  let fixture: ComponentFixture<ConnectAssistantDialogComponent>;
  let listMcpTokens: Mock;
  let createMcpToken: Mock;
  let revokeMcpToken: Mock;
  let multiUser: boolean;
  let edition: boolean;
  let loginRequired: boolean;
  let connected: boolean;
  let webMcpState: WebMcpState;

  const text = (): string => (fixture.nativeElement as HTMLElement).textContent ?? '';
  const query = <T extends HTMLElement>(selector: string): T | null => (fixture.nativeElement as HTMLElement).querySelector<T>(selector);
  const queryAll = (selector: string): HTMLElement[] => Array.from((fixture.nativeElement as HTMLElement).querySelectorAll<HTMLElement>(selector));
  const flush = async (): Promise<void> => {
    await fixture.whenStable();
    fixture.detectChanges();
  };
  const create = async (): Promise<void> => {
    fixture = TestBed.createComponent(ConnectAssistantDialogComponent);
    fixture.detectChanges();
    await flush();
  };
  const buttonByText = (label: string): HTMLButtonElement | undefined =>
    queryAll('button').find(b => b.textContent?.includes(label)) as HTMLButtonElement | undefined;

  beforeEach(() => {
    multiUser = false;
    edition = false;
    loginRequired = true;
    connected = false;
    webMcpState = 'active';
    listMcpTokens = vi.fn(() => of({ tokens: [TOKEN_ROW] }));
    createMcpToken = vi.fn((body: { name: string; level: McpTokenItem['level'] }) =>
      of({ ...TOKEN_ROW, id: 8, name: body.name, level: body.level, token: SECRET } as McpTokenCreated));
    revokeMcpToken = vi.fn(() => of({ id: 7, ok: true }));
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { listMcpTokens, createMcpToken, revokeMcpToken } },
        { provide: AuthService, useValue: { isMultiUser: () => multiUser, isEdition: () => edition, loginPasswordRequired: () => loginRequired } },
        { provide: I18nService, useValue: { t: (key: string, vars?: Record<string, string>) => (vars ? `${key} ${Object.values(vars).join(' ')}` : key), translations: signal({}) } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: MatDialogRef, useValue: { close: vi.fn() } },
        { provide: AgentBridgeService, useValue: { tabId: 'tab123', connected: () => connected } },
        { provide: AgentWebMcpService, useValue: { state: () => webMcpState } },
      ],
    });
  });

  it('lists tokens by prefix only, with dd/MM/yyyy dates and no plaintext', async () => {
    await create();
    expect(queryAll('[data-testid="token-row"]')).toHaveLength(1);
    expect(text()).toContain('fct_ab12…');
    expect(text()).toContain('03/09/2026');
    expect(query('[data-testid="reveal"]')).toBeNull();
    expect(text()).not.toContain('SECRET');
  });

  it('offers only the readonly level to a single-user, non-edition session', async () => {
    await create();
    const options = queryAll('select[name="token-level"] option').map(o => o.textContent?.trim());
    expect(options).toEqual(['dialog.connect_assistant.level_readonly']);
  });

  it('adds "act as me" for multi-user accounts and "full editing" only for an edition session', async () => {
    multiUser = true;
    await create();
    expect(queryAll('select[name="token-level"] option')).toHaveLength(2);
    TestBed.resetTestingModule();
    multiUser = true;
    edition = true;
    TestBed.configureTestingModule({
      providers: [
        { provide: ApiService, useValue: { listMcpTokens, createMcpToken, revokeMcpToken } },
        { provide: AuthService, useValue: { isMultiUser: () => true, isEdition: () => true, loginPasswordRequired: () => true } },
        { provide: I18nService, useValue: { t: (key: string, vars?: Record<string, string>) => (vars ? `${key} ${Object.values(vars).join(' ')}` : key), translations: signal({}) } },
        { provide: MatSnackBar, useValue: { open: vi.fn() } },
        { provide: MatDialogRef, useValue: { close: vi.fn() } },
        { provide: AgentBridgeService, useValue: { tabId: 'tab123', connected: () => connected } },
        { provide: AgentWebMcpService, useValue: { state: () => webMcpState } },
      ],
    });
    await create();
    expect(queryAll('select[name="token-level"] option')).toHaveLength(3);
  });

  it('mints with the chosen level, reveals the plaintext once and puts it in the Claude Code snippet', async () => {
    await create();
    const input = query<HTMLInputElement>('input[name="token-name"]');
    input!.value = '  CI box ';
    input!.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    buttonByText('dialog.connect_assistant.mint')!.click();
    await flush();
    expect(createMcpToken).toHaveBeenCalledWith({ name: 'CI box', level: 'readonly' });
    expect(query('[data-testid="token-value"]')?.textContent).toBe(SECRET);
    const snippet = query('[data-testid="snippet"]')!.textContent!;
    expect(snippet).toBe(`claude mcp add --transport http facet ${location.origin}/mcp --header "Authorization: Bearer ${SECRET}"`);
    expect(listMcpTokens).toHaveBeenCalledTimes(2);
  });

  it('shows no plaintext token the next time the dialog opens', async () => {
    await create();
    const input = query<HTMLInputElement>('input[name="token-name"]');
    input!.value = 'x';
    input!.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    buttonByText('dialog.connect_assistant.mint')!.click();
    await flush();
    expect(text()).toContain(SECRET);
    fixture.destroy();
    await create();
    expect(text()).not.toContain(SECRET);
    expect(text()).not.toMatch(/fct_[A-Za-z0-9]{12,}/);
  });

  it('explains the token limit on a 412', async () => {
    createMcpToken.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 412 })));
    await create();
    const input = query<HTMLInputElement>('input[name="token-name"]');
    input!.value = 'x';
    input!.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    buttonByText('dialog.connect_assistant.mint')!.click();
    await flush();
    expect(query('[role="alert"]')?.textContent).toContain('dialog.connect_assistant.mint_limit');
  });

  it('asks for confirmation, then revokes and removes the row', async () => {
    await create();
    buttonByText('dialog.connect_assistant.revoke')!.click();
    fixture.detectChanges();
    expect(revokeMcpToken).not.toHaveBeenCalled();
    expect(text()).toContain('dialog.connect_assistant.revoke_confirm');
    buttonByText('dialog.connect_assistant.revoke_confirm_yes')!.click();
    await flush();
    expect(revokeMcpToken).toHaveBeenCalledWith(7);
    expect(queryAll('[data-testid="token-row"]')).toHaveLength(0);
  });

  it('shows an edition badge on edition tokens', async () => {
    listMcpTokens.mockReturnValue(of({ tokens: [{ ...TOKEN_ROW, level: 'edition' }] }));
    await create();
    expect(query('[data-testid="edition-badge"]')).not.toBeNull();
  });

  it('reflects the bridge status', async () => {
    await create();
    expect(query('[data-testid="bridge-status"]')?.textContent).toContain('dialog.connect_assistant.bridge_not_connected');
  });

  it('notes that in-page WebMCP needs a secure context only when it was skipped for that reason', async () => {
    await create();
    expect(query('[data-testid="insecure-note"]')).toBeNull();
    fixture.destroy();
    webMcpState = 'insecure_context';
    await create();
    expect(query('[data-testid="insecure-note"]')?.textContent).toContain('dialog.connect_assistant.insecure_context');
  });

  describe('grants the server will honour', () => {
    it('offers readonly only on an open install, even for an edition session', async () => {
      loginRequired = false;
      edition = true;
      await create();
      expect(queryAll('select[name="token-level"] option')).toHaveLength(1);
    });

    it('shows the level the server granted when it capped the request', async () => {
      multiUser = true;
      edition = true;
      createMcpToken.mockReturnValueOnce(of({ ...TOKEN_ROW, id: 9, name: 'x', level: 'readonly', token: SECRET } as McpTokenCreated));
      await create();
      const select = query<HTMLSelectElement>('select[name="token-level"]')!;
      select.value = 'edition';
      select.dispatchEvent(new Event('change'));
      fixture.detectChanges();
      await mintAs('x');
      expect(createMcpToken).toHaveBeenCalledWith({ name: 'x', level: 'edition' });
      const granted = query('[data-testid="granted-level"]')?.textContent;
      expect(granted).toContain('dialog.connect_assistant.level_readonly');
      expect(granted).not.toContain('level_edition');
    });
  });

  describe('failures', () => {
    it('reports a failed list load', async () => {
      listMcpTokens.mockReturnValue(throwError(() => new HttpErrorResponse({ status: 500 })));
      await create();
      expect(query('[role="alert"]')?.textContent).toContain('dialog.connect_assistant.load_failed');
    });

    it('reports a non-412 mint failure as mint_failed', async () => {
      createMcpToken.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 500 })));
      await create();
      await mintAs('x');
      expect(query('[role="alert"]')?.textContent).toContain('dialog.connect_assistant.mint_failed');
    });

    it('reports a failed revoke as revoke_failed and keeps the row', async () => {
      revokeMcpToken.mockReturnValueOnce(throwError(() => new HttpErrorResponse({ status: 404 })));
      await create();
      buttonByText('dialog.connect_assistant.revoke')!.click();
      fixture.detectChanges();
      buttonByText('dialog.connect_assistant.revoke_confirm_yes')!.click();
      await flush();
      const alert = query('[role="alert"]')?.textContent;
      expect(alert).toContain('dialog.connect_assistant.revoke_failed');
      expect(alert).not.toContain('load_failed');
      expect(queryAll('[data-testid="token-row"]')).toHaveLength(1);
    });
  });

  describe('copy', () => {
    afterEach(() => {
      Reflect.deleteProperty(navigator, 'clipboard');
      delete (document as unknown as Record<string, unknown>)['execCommand'];
    });

    it('falls back to a hidden textarea when navigator.clipboard is unavailable', async () => {
      Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
      const execCommand = vi.fn(() => true);
      (document as unknown as Record<string, unknown>)['execCommand'] = execCommand;
      await create();
      buttonByText('dialog.connect_assistant.copy')!.click();
      await flush();
      expect(execCommand).toHaveBeenCalledWith('copy');
      expect(document.querySelector('textarea')).toBeNull();
      expect(text()).toContain('dialog.connect_assistant.copied');
      expect(query('[data-testid="live-region"]')?.textContent).toContain('dialog.connect_assistant.copied');
    });

    it('says nothing when both copy routes fail', async () => {
      Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
      (document as unknown as Record<string, unknown>)['execCommand'] = vi.fn(() => false);
      await create();
      buttonByText('dialog.connect_assistant.copy')!.click();
      await flush();
      expect(query('[data-testid="live-region"]')?.textContent).toBe('');
    });
  });

  describe('accessibility', () => {
    it('keeps Create disabled until a name is typed', async () => {
      await create();
      expect(buttonByText('dialog.connect_assistant.mint')!.disabled).toBe(true);
      await mintAs('x', false);
      expect(buttonByText('dialog.connect_assistant.mint')!.disabled).toBe(false);
    });

    it('names the token on the Revoke buttons and the new token on the Copy button', async () => {
      await create();
      expect(query('button[aria-label="dialog.connect_assistant.revoke_aria Laptop"]')).not.toBeNull();
      await mintAs('x');
      expect(query('button[aria-label="dialog.connect_assistant.copy_token_aria"]')).not.toBeNull();
      expect(query('button[aria-label="dialog.connect_assistant.copy_snippet_aria"]')).not.toBeNull();
    });

    it('announces the mint in a polite live region and moves focus to the token field', async () => {
      await create();
      await mintAs('x');
      const live = query('[data-testid="live-region"]')!;
      expect(live.getAttribute('aria-live')).toBe('polite');
      expect(live.textContent).toContain('token_created_announce');
      expect(document.activeElement).toBe(query('[data-testid="token-value"]'));
    });

    it('moves focus to the list heading after a revoke', async () => {
      await create();
      buttonByText('dialog.connect_assistant.revoke')!.click();
      fixture.detectChanges();
      buttonByText('dialog.connect_assistant.revoke_confirm_yes')!.click();
      await flush();
      expect(document.activeElement?.id).toBe('connect-tokens-heading');
    });

    it('moves focus to the confirm button when Revoke turns into the confirm, and back to Revoke on cancel', async () => {
      await create();
      buttonByText('dialog.connect_assistant.revoke')!.click();
      await flush();
      expect(document.activeElement).toBe(query('[data-testid="revoke-confirm-yes"]'));
      query<HTMLButtonElement>('button[aria-label^="dialog.connect_assistant.cancel_revoke_aria"]')!.click();
      await flush();
      expect(document.activeElement).toBe(query('button[aria-label^="dialog.connect_assistant.revoke_aria"]'));
    });

    it('re-announces a repeated copy by clearing the live region first', async () => {
      vi.useFakeTimers();
      try {
        Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn(() => Promise.resolve()) }, configurable: true });
        await create();
        const live = query('[data-testid="live-region"]')!;
        const copyButton = buttonByText('dialog.connect_assistant.copy')!;
        copyButton.click();
        await flush();
        expect(live.textContent).toContain('dialog.connect_assistant.copied');
        copyButton.click();
        await flush();
        expect(live.textContent).toBe('');
        vi.advanceTimersByTime(150);
        fixture.detectChanges();
        expect(live.textContent).toContain('dialog.connect_assistant.copied');
      } finally {
        vi.useRealTimers();
        Reflect.deleteProperty(navigator, 'clipboard');
      }
    });

    it('names the Copy buttons by their visible "Copied" text while the copied state shows', async () => {
      Object.defineProperty(navigator, 'clipboard', { value: { writeText: vi.fn(() => Promise.resolve()) }, configurable: true });
      await create();
      query<HTMLButtonElement>('button[aria-label="dialog.connect_assistant.copy_snippet_aria"]')!.click();
      await new Promise(resolve => setTimeout(resolve, 20));
      fixture.detectChanges();
      expect(query('button[aria-label="dialog.connect_assistant.copied_snippet_aria"]')).not.toBeNull();
      Reflect.deleteProperty(navigator, 'clipboard');
    });

    it('does not use the low-contrast amber-600 text', async () => {
      await create();
      await mintAs('x');
      expect(fixture.nativeElement.innerHTML).not.toContain('text-amber-600');
    });
  });

  async function mintAs(name: string, click = true): Promise<void> {
    const input = query<HTMLInputElement>('input[name="token-name"]');
    input!.value = name;
    input!.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    if (!click) return;
    buttonByText('dialog.connect_assistant.mint')!.click();
    await flush();
    await flush();
  }
});
