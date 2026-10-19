"""Agent control surface: MCP endpoint (``/mcp``), bearer tokens and the tools.

Tools: read (``tools_read``), write with confirmed destructive runs (``tools_write``),
darkroom culling (``tools_culling``) and ``ui_*`` tools that drive the user's open tab
over the WebSocket bridge (``tools_ui``, ``bridge``, ``ui_tools``).

Named ``agent`` rather than ``mcp`` so a module of ours can never shadow the SDK.
Everything here reaches library data through the existing ``/api`` routes
(``internal_client``), never through a second SQL path.
"""
