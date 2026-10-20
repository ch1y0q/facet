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

  const text = (): string => (fixture.nativeElement as HTMLElement).textContent ?? '';
  const query = <T extends HTMLElement>(selector: string): T | null => (fixture.nativeElement as HTMLElement).querySelector<T>(selector);
  const queryAll = <T extends HTMLElement = HTMLElement>(selector: string): T[] => Array.from((fixture.nativeElement as HTMLElement).querySelectorAll<T>(selector));
  const flush = async (): Promise<void> => {
    await fixture.whenStable();
    fixture.detectChanges();
  };
  const create = async (): Promise<void> => {
    fixture = TestBed.createComponent(ConnectAssistantDialogComponent);
    fixture.detectChanges();
    await flush();
  };
  const promptValue = (): string => query<HTMLTextAreaElement>('[data-testid="prompt"]')?.value ?? '';
  const buttonByText = (label: string): HTMLButtonElement | undefined =>
    queryAll('button').find(b => b.textContent?.includes(label)) as HTMLButtonElement | undefined;

  beforeEach(() => {
    multiUser = false;
    edition = false;
    loginRequired = true;
    connected = false;
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
      ],
    });
  });

  it('lists tokens with the prefix only as a tooltip, with dd/MM/yyyy dates and no plaintext', async () => {
    await create();
    expect(queryAll('[data-testid="token-row"]')).toHaveLength(1);
    expect(query('[data-testid="token-row"] [title]')?.getAttribute('title')).toBe('fct_ab12…');
    expect(query('[data-testid="token-row"]')?.textContent).not.toContain('fct_ab12');
    expect(text()).toContain('03/09/2026');
    expect(query('[data-testid="reveal"]')).toBeNull();
    expect(query('[data-testid="prompt"]')).toBeNull();
    expect(text()).not.toContain('SECRET');
  });

  it('shows the Manage tokens disclosure with the token count, and no tab id', async () => {
    await create();
    const summary = query('[data-testid="tokens-disclosure"] summary')!;
    expect(summary.textContent).toContain('dialog.connect_assistant.manage_tokens 1');
    expect(query('[data-testid="bridge-status"]')?.textContent).not.toContain('tab123');
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
      ],
    });
    await create();
    expect(queryAll('select[name="token-level"] option')).toHaveLength(3);
  });

  it('mints with the chosen level and shows one vendor-neutral prompt holding the token', async () => {
    await create();
    expect(query('input[name="token-name"]')).not.toBeNull();
    const input = query<HTMLInputElement>('input[name="token-name"]');
    input!.value = '  CI box ';
    input!.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    buttonByText('dialog.connect_assistant.mint')!.click();
    await flush();
    expect(createMcpToken).toHaveBeenCalledWith({ name: 'CI box', level: 'readonly' });
    const prompt = promptValue();
    expect(prompt).toContain(SECRET);
    expect(prompt).toContain(`${location.origin}/mcp`);
    expect(prompt).toContain(`Authorization: Bearer ${SECRET}`);
    expect(prompt).toContain('status');
    expect(prompt.toLowerCase()).not.toMatch(/claude|codex|cursor/);
    expect(query('input[name="token-name"]')).toBeNull();
    expect(query('[data-testid="token-value"]')).toBeNull();
    expect(listMcpTokens).toHaveBeenCalledTimes(2);
  });

  it('returns to the form on Done, clears every plaintext copy and focuses the name field', async () => {
    await create();
    await mintAs('x');
    expect(promptValue()).toContain(SECRET);
    buttonByText('dialog.connect_assistant.done')!.click();
    await flush();
    expect(query('[data-testid="prompt"]')).toBeNull();
    expect(queryAll<HTMLTextAreaElement>('textarea').every(t => !t.value.includes(SECRET))).toBe(true);
    expect(text()).not.toContain(SECRET);
    expect(document.activeElement).toBe(query('input[name="token-name"]'));
  });

  it('offers exactly one copy button on the prompt step', async () => {
    await create();
    await mintAs('x');
    expect(queryAll('button').filter(b => b.textContent?.includes('dialog.connect_assistant.copy'))).toHaveLength(1);
    expect(buttonByText('dialog.connect_assistant.copy_prompt')!.hasAttribute('aria-label')).toBe(false);
  });

  it('shows no plaintext token the next time the dialog opens', async () => {
    await create();
    const input = query<HTMLInputElement>('input[name="token-name"]');
    input!.value = 'x';
    input!.dispatchEvent(new Event('input'));
    fixture.detectChanges();
    buttonByText('dialog.connect_assistant.mint')!.click();
    await flush();
    expect(promptValue()).toContain(SECRET);
    const instance = fixture.componentInstance as unknown as { createdToken: () => unknown };
    expect(instance.createdToken()).not.toBeNull();
    fixture.destroy();
    expect(instance.createdToken()).toBeNull();
    await create();
    expect(promptValue()).toBe('');
    expect(text()).not.toContain(SECRET);
    expect(text()).not.toMatch(/fct_[A-Za-z0-9]{12,}/);
  });

  it('keeps the tokens disclosure open across mint and Done once the user opened it', async () => {
    await create();
    const details = query<HTMLDetailsElement>('[data-testid="tokens-disclosure"]')!;
    details.open = true;
    details.dispatchEvent(new Event('toggle'));
    await mintAs('x');
    buttonByText('dialog.connect_assistant.done')!.click();
    await flush();
    expect(query<HTMLDetailsElement>('[data-testid="tokens-disclosure"]')!.open).toBe(true);
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
    expect(query('[data-testid="tokens-disclosure"] summary')?.textContent).toContain('manage_tokens 0');
  });

  it('shows an edition badge on edition tokens', async () => {
    listMcpTokens.mockReturnValue(of({ tokens: [{ ...TOKEN_ROW, level: 'edition' }] }));
    await create();
    expect(query('[data-testid="edition-badge"]')).not.toBeNull();
  });

  it('reflects the bridge status', async () => {
    await create();
    expect(query('[data-testid="bridge-status"]')?.textContent).toContain('dialog.connect_assistant.tab_not_connected');
    expect(query('[data-testid="bridge-status"]')?.textContent).not.toContain('tab123');
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
      const granted = promptValue();
      expect(granted).toContain('dialog.connect_assistant.level_readonly (readonly)');
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
      await mintAs('x');
      buttonByText('dialog.connect_assistant.copy_prompt')!.click();
      await flush();
      expect(execCommand).toHaveBeenCalledWith('copy');
      expect(document.querySelector('textarea:not([data-testid="prompt"])')).toBeNull();
      expect(text()).toContain('dialog.connect_assistant.copied');
      expect(query('[data-testid="live-region"]')?.textContent).toContain('dialog.connect_assistant.copied');
    });

    it('says nothing when both copy routes fail', async () => {
      Object.defineProperty(navigator, 'clipboard', { value: undefined, configurable: true });
      (document as unknown as Record<string, unknown>)['execCommand'] = vi.fn(() => false);
      await create();
      await mintAs('x');
      buttonByText('dialog.connect_assistant.copy_prompt')!.click();
      await flush();
      expect(query('[data-testid="live-region"]')?.textContent).not.toContain('dialog.connect_assistant.copied');
    });
  });

  describe('accessibility', () => {
    it('keeps Create disabled until a name is typed', async () => {
      await create();
      expect(buttonByText('dialog.connect_assistant.mint')!.disabled).toBe(true);
      await mintAs('x', false);
      expect(buttonByText('dialog.connect_assistant.mint')!.disabled).toBe(false);
    });

    it('names the token on the Revoke buttons and the prompt on the Copy button', async () => {
      await create();
      expect(query('button[aria-label="dialog.connect_assistant.revoke_aria Laptop"]')).not.toBeNull();
      await mintAs('x');
      expect(buttonByText('dialog.connect_assistant.copy_prompt')).toBeDefined();
    });

    it('announces the mint in a polite live region and moves focus to the prompt heading', async () => {
      await create();
      await mintAs('x');
      const live = query('[data-testid="live-region"]')!;
      expect(live.getAttribute('aria-live')).toBe('polite');
      expect(live.textContent).toContain('token_created_announce');
      expect(document.activeElement?.id).toBe('connect-prompt-heading');
    });

    it('moves focus to the disclosure summary after a revoke', async () => {
      await create();
      buttonByText('dialog.connect_assistant.revoke')!.click();
      fixture.detectChanges();
      buttonByText('dialog.connect_assistant.revoke_confirm_yes')!.click();
      await flush();
      expect(document.activeElement).toBe(query('[data-testid="tokens-disclosure"] summary'));
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
        await mintAs('x');
        const live = query('[data-testid="live-region"]')!;
        const copyButton = buttonByText('dialog.connect_assistant.copy_prompt')!;
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
      await mintAs('x');
      buttonByText('dialog.connect_assistant.copy_prompt')!.click();
      await new Promise(resolve => setTimeout(resolve, 20));
      fixture.detectChanges();
      expect(buttonByText('dialog.connect_assistant.copied')).toBeDefined();
      expect(buttonByText('dialog.connect_assistant.copy_prompt')).toBeUndefined();
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
