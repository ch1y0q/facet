import type { components } from './schema';

/**
 * Named aliases for response shapes generated from the FastAPI OpenAPI schema
 * by `npm run gen:api`. Alias a shape here instead of re-declaring it in a
 * component: three incompatible copies of the comparison-stats shape had
 * already drifted apart before this file existed, and the generated file is
 * regenerated and diffed in CI, so an alias cannot describe a response the
 * server no longer sends.
 *
 * Shapes that embed a photo row deliberately stay hand-written in
 * `shared/models/photo.model.ts` and `features/gallery/gallery.store.ts`. The
 * client declares `Photo` more strictly than the wire does — `filename` and
 * `aesthetic` are required there and optional in the generated type — because
 * those fields are read unconditionally, and widening them to match the
 * generated shape would push a null check into every consumer for a value the
 * server has always sent. `tests/test_api_contract.py` is what keeps the two
 * honest: it fails if the hand-written model declares a field the server does
 * not, and it type-checks every declared field against a live response.
 */
export type ComparisonStats = components['schemas']['ComparisonStatsResponse'];

export type DownloadOption = components['schemas']['DownloadOption'];

export type LightroomImportResponse = components['schemas']['LightroomImportResponse'];

export type LightroomManifest = components['schemas']['LightroomManifest'];

export type MergeSuggestionsResponse = components['schemas']['MergeSuggestionsResponse'];

export type McpTokenItem = components['schemas']['McpTokenItem'];

export type McpTokenCreate = components['schemas']['McpTokenCreate'];

export type McpTokenCreated = components['schemas']['McpTokenCreated'];

export type McpTokenList = components['schemas']['McpTokenList'];

export type McpTokenRevoked = components['schemas']['McpTokenRevoked'];

export type AgentActionBatch = components['schemas']['AgentActionBatch'];

export type AgentActionList = components['schemas']['AgentActionList'];

export type AgentUndoRequest = components['schemas']['AgentUndoRequest'];

export type AgentUndoResult = components['schemas']['AgentUndoResult'];

/** Level tiers of the in-page server tools; a tool needs at least its `required_level`. */
export type McpInpageLevel = 'readonly' | 'user' | 'edition';

/** One server tool the session may call in-page (`GET /api/mcp/inpage_tools`); `show` and `tab_id` are already stripped. */
export interface McpInpageTool {
  name: string;
  description: string;
  inputSchema: Record<string, unknown>;
  annotations: { readOnlyHint?: boolean; consequentialHint?: boolean; untrustedContentHint?: boolean };
  required_level: McpInpageLevel;
}

export interface McpInpageTools {
  level: McpInpageLevel;
  tools: McpInpageTool[];
}

/** Body of `POST /api/mcp/call`; `selection_snapshot` is the caller tab's `ui_get_selection` data. */
export interface McpCallRequest {
  tool: string;
  arguments: Record<string, unknown>;
  selection_snapshot?: unknown;
}

/** The tool envelope as a 200 body. `changed` counts photos a write changed (0 for a dry run), `batch_id` is its journal batch. */
export interface McpCallResponse {
  ok: boolean;
  data?: unknown;
  error?: string;
  message?: string;
  changed?: number;
  batch_id?: string;
}
