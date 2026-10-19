/**
 * Shared shapes of the agent UI-tool layer: the contract entries generated
 * from the server's `api/agent/ui_tools.py`, the result envelope both consumers
 * (the tab bridge and in-page WebMCP) receive, and the error type a handler
 * throws.
 */

/** The only error codes the bridge protocol lets a tab report; the server maps any other to `upstream_error`. */
export const UI_TOOL_ERROR_CODES = [
  'invalid_input', 'not_found', 'forbidden_level', 'no_active_view', 'upstream_error', 'too_large',
] as const;

export type UiToolErrorCode = (typeof UI_TOOL_ERROR_CODES)[number];

export interface UiToolAnnotations {
  readOnlyHint: boolean;
  untrustedContentHint: boolean;
  destructiveHint?: boolean;
  idempotentHint?: boolean;
}

/** The subset of JSON Schema the contract uses. */
export interface JsonSchema {
  type?: string | string[];
  enum?: unknown[];
  properties?: Record<string, JsonSchema>;
  required?: string[];
  additionalProperties?: boolean | JsonSchema;
  items?: JsonSchema;
  minItems?: number;
  maxItems?: number;
  minLength?: number;
  maxLength?: number;
  minimum?: number;
  maximum?: number;
  default?: unknown;
  description?: string;
}

export interface UiToolContract {
  name: string;
  description: string;
  inputSchema: JsonSchema;
  annotations: UiToolAnnotations;
}

export interface UiToolContractFile {
  version: string;
  tools: UiToolContract[];
  error_codes: string[];
}

export type UiToolEnvelope =
  | { ok: true; data: unknown }
  | { ok: false; error: UiToolErrorCode; message: string };

export type UiToolHandler = (args: Record<string, unknown>) => Promise<unknown>;

export class UiToolError extends Error {
  constructor(readonly code: UiToolErrorCode, message: string) {
    super(message);
    this.name = 'UiToolError';
  }
}
