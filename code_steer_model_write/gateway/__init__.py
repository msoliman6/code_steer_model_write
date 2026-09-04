"""L2's Gateway (ARCHITECTURE.md 7.10): the one entry every caller uses -- the MCP server for
Claude Code and Codex, the CLI, the walk. `api.py` holds the operations as plain functions;
`server.py` exposes them as MCP tools with pydantic schemas. A request in is a RunSpec; what
comes out is a view of L7 State. Nothing here decides sequence."""
