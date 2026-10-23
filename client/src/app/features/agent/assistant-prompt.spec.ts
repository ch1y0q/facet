import { buildAssistantPrompt } from './assistant-prompt';

const TOKEN = 'fct_ab12SECRETSECRETSECRETSECRET';
const INPUT = { url: 'http://localhost:5000/mcp', token: TOKEN, levelLabel: 'LEVEL_LABEL', level: 'readonly' };
const KEY_PREFIX = 'dialog.connect_assistant.';

describe('buildAssistantPrompt', () => {
  it('orders the prose and appends the exact literals after each label', () => {
    const lines = buildAssistantPrompt(key => key.replace(KEY_PREFIX, ''), INPUT).split('\n');
    expect(lines).toEqual([
      'prompt_intro',
      '',
      'prompt_label_server facet',
      'prompt_label_url http://localhost:5000/mcp',
      'prompt_label_transport Streamable HTTP (MCP)',
      `prompt_label_header Authorization: Bearer ${TOKEN}`,
      'prompt_label_access LEVEL_LABEL (readonly)',
      '',
      'prompt_token_rules',
      '',
      'prompt_verify status',
      '',
      'prompt_capabilities',
    ]);
  });

  it('embeds the token exactly once and verbatim, even with odd characters', () => {
    const odd = 'fct_a\nb "c"';
    const prompt = buildAssistantPrompt(key => key, { ...INPUT, token: odd });
    expect(prompt.split(odd)).toHaveLength(2);
  });

  it('names no vendor client', () => {
    expect(buildAssistantPrompt(key => key, INPUT).toLowerCase()).not.toMatch(/claude|codex|cursor|anthropic|openai/);
  });

  it.each(['en', 'fr', 'de', 'it', 'es', 'pt', 'zh'])('renders with the real %s catalogue: no key leak, no vendor, no empty label', async lang => {
    const cat = (await import(`../../../../../i18n/translations/${lang}.json`)).default as { dialog: { connect_assistant: Record<string, string> } };
    const dict = cat.dialog.connect_assistant;
    const prompt = buildAssistantPrompt(key => dict[key.slice(KEY_PREFIX.length)] ?? key, INPUT);
    const lines = prompt.split('\n');
    expect(prompt).not.toContain('dialog.');
    expect(prompt).not.toMatch(/claude|codex|cursor|anthropic|openai/i);
    expect(lines).toHaveLength(13);
    expect(lines.filter(l => l.trim() !== '')).toHaveLength(9);
  });
});
