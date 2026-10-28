"""Owner-private, local organization tools; all data access uses authorized HTTP routes."""
from typing import Annotated
from uuid import UUID

from mcp.server.mcpserver import Context, MCPServer
from mcp.types import CallToolResult, ToolAnnotations
from pydantic import Field

from api.agent.internal_client import InternalClient, err
from api.agent.limits import encoded_size
from api.agent.runtime import run_tool
from api.agent.tools_common import READ_ANNOTATIONS, register_tool
from api.agent.tools_write import WRITE_TOOL_LEVELS

StackPath = Annotated[str, Field(min_length=1, max_length=4096)]
StackPaths = Annotated[list[StackPath], Field(max_length=1000)]
CreatePaths = Annotated[list[StackPath], Field(min_length=2, max_length=1000)]
Revision = Annotated[int, Field(strict=True, gt=0, le=9223372036854775807)]
# Revisioned edits and history reverts refuse repeats; creation has no idempotency key.
STACK_WRITE_ANNOTATIONS = ToolAnnotations(read_only_hint=False, destructive_hint=False,
                                         idempotent_hint=False, open_world_hint=False)


def _mutation_result(result: dict, max_bytes: int) -> dict:
    """Retain a successful write and its Undo receipt when the full stack exceeds the response cap."""
    if result['ok'] and encoded_size(result) > max_bytes:
        data = result['data']
        stack = data.get('stack')
        if stack is not None:
            return {**result, 'data': {**data, 'stack_truncated': True, 'stack': {
                'id': stack['id'], 'revision': stack['revision'], 'member_count': len(stack['members']),
            }}}
    return result


def register_stack_tools(server: MCPServer, client: InternalClient) -> None:
    async def get_photo_stack(ctx: Context, path: StackPath) -> CallToolResult:
        async def handler(grant, resolved, settings):
            return await client.call(grant, 'get_photo_stack', query={'path': path},
                                     timeout=settings['call_timeout_s'])
        return await run_tool(ctx, 'get_photo_stack', handler)

    async def create_photo_stack(ctx: Context, paths: CreatePaths, cover_path: StackPath) -> CallToolResult:
        async def handler(grant, resolved, settings):
            result = await client.call(grant, 'create_photo_stack', json={'paths': paths, 'cover_path': cover_path},
                                       timeout=settings['call_timeout_s'])
            return _mutation_result(result, settings['max_bytes'])
        return await run_tool(ctx, 'create_photo_stack', handler, write=True)

    async def update_photo_stack(ctx: Context, stack_id: UUID, paths: StackPaths,
                                 expected_revision: Revision, cover_path: StackPath | None = None) -> CallToolResult:
        async def handler(grant, resolved, settings):
            result = await client.call(grant, 'update_photo_stack', path_args={'stack_id': str(stack_id)},
                                       json={'paths': paths, 'cover_path': cover_path,
                                             'expected_revision': expected_revision}, timeout=settings['call_timeout_s'])
            return _mutation_result(result, settings['max_bytes'])
        return await run_tool(ctx, 'update_photo_stack', handler, write=True)

    async def unstack_photos(ctx: Context, stack_id: UUID, expected_revision: Revision) -> CallToolResult:
        async def handler(grant, resolved, settings):
            return await client.call(grant, 'unstack_photos', path_args={'stack_id': str(stack_id)},
                                     query={'expected_revision': expected_revision}, timeout=settings['call_timeout_s'])
        return await run_tool(ctx, 'unstack_photos', handler, write=True)

    async def undo_photo_stack(ctx: Context, entry_id: Revision) -> CallToolResult:
        async def handler(grant, resolved, settings):
            history = await client.call(grant, 'stack_history', timeout=settings['call_timeout_s'])
            if not history['ok']:
                return history
            entries = (history['data'] or {}).get('entries', [])
            if not any(entry.get('id') == entry_id and entry.get('kind') == 'stack' for entry in entries):
                return err('invalid_input', 'No available stack Undo entry with this entry_id')
            return await client.call(grant, 'undo_photo_stack', path_args={'entry_id': entry_id},
                                     timeout=settings['call_timeout_s'])
        return await run_tool(ctx, 'undo_photo_stack', handler, write=True)

    register_tool(server, get_photo_stack, 'get_photo_stack',
                  'Read the local manual stack containing this exact photo, or null. Owner-private; '
                  'only permitted members are returned. A partially visible stack is read-only.', READ_ANNOTATIONS)
    scope = (' Local organization only: no files, ratings or Keep/Reject decisions change, and no Immich call is made. '
             'Explicit paths only (at most 1000); never expand a tile or target an entire view implicitly. '
             'All members must be currently visible; partial stacks refuse edits. Successful changes return '
             '`undo.entry_id` for undo_photo_stack. A large mutation response sets `stack_truncated: true` and '
             'returns only the stack UUID/revision/member_count, preserving Undo; it is not a complete member list. '
             'After an outcome_unknown, read current state before retrying.')
    descriptions = {
        'create_photo_stack': 'Create a manual stack of 2–1000 explicit unstacked photos, in supplied order, '
                             'with cover_path naming a member. Non-idempotent: never blindly retry creation.',
        'update_photo_stack': 'Replace one local stack’s explicit member order and optionally cover. '
                             'Requires its UUID and expected_revision from get_photo_stack; stale revisions refuse. '
                             'Zero or one remaining member dissolves the group. An omitted cover keeps the current '
                             'cover if present, otherwise chooses the first surviving member.',
        'unstack_photos': 'Dissolve a local stack using its UUID and expected_revision from get_photo_stack. '
                         'Leaves all originals and independent decisions intact; stale revisions refuse.',
        'undo_photo_stack': 'Undo an available stack organization-history entry only. Requires entry_id from '
                            'a successful stack change. Refuses unrelated entries, later edits, membership reuse '
                            'and loss of visibility; reads history before using the existing authorized revert route.',
    }
    for fn in (create_photo_stack, update_photo_stack, unstack_photos, undo_photo_stack):
        register_tool(server, fn, fn.__name__, descriptions[fn.__name__] + scope,
                      STACK_WRITE_ANNOTATIONS, WRITE_TOOL_LEVELS[fn.__name__])
