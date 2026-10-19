"""Agent control surface: MCP endpoint (``/mcp``), bearer tokens and the read tools.

Named ``agent`` rather than ``mcp`` so a module of ours can never shadow the SDK.
Everything here reaches library data through the existing ``/api`` routes
(``internal_client``), never through a second SQL path.
"""
