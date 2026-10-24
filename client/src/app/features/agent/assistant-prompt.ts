import { i18nKeys } from '../../core/i18n/keys';

type Translate = (key: string, params?: Record<string, string>) => string;

interface AssistantPromptInput {
  url: string;
  token: string;
  /** Translated label of the granted level. */
  levelLabel: string;
  /** Raw level id, appended after the label so the exact grant is unambiguous. */
  level: string;
}

const SERVER_NAME = 'facet';
const TRANSPORT = 'Streamable HTTP (MCP)';
const STATUS_TOOL = 'status';

/**
 * The vendor-neutral setup prompt: translated prose around literals (server name, URL, transport,
 * header, tool name, token, level id) that are appended here, never in a catalogue, so a
 * translator cannot alter them.
 */
export function buildAssistantPrompt(t: Translate, p: AssistantPromptInput): string {
  const k = i18nKeys().dialog.connect_assistant;
  return [
    t(k.prompt_intro),
    '',
    `${t(k.prompt_label_server)} ${SERVER_NAME}`,
    `${t(k.prompt_label_url)} ${p.url}`,
    `${t(k.prompt_label_transport)} ${TRANSPORT}`,
    `${t(k.prompt_label_header)} Authorization: Bearer ${p.token}`,
    `${t(k.prompt_label_access)} ${p.levelLabel} (${p.level})`,
    '',
    t(k.prompt_token_rules),
    '',
    `${t(k.prompt_verify)} ${STATUS_TOOL}`,
    '',
    t(k.prompt_capabilities),
  ].join('\n');
}
