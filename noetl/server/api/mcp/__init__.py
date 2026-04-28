"""MCP server lifecycle and discovery API.

Adds a catalog-driven shape for managing MCP servers without requiring
the GUI / CLI / external automation to know how each server is
provisioned: every Mcp catalog entry can declare a `lifecycle:` block
with verb -> Agent playbook path mappings (deploy / redeploy / status /
restart / undeploy / discover), a `discovery:` block for refreshing
the tool list against the running server, and a `runtime:` block for
the agent the GUI dispatches normal tool calls through.

Endpoints exposed under /api/mcp:
- POST /api/mcp/{path:path}/lifecycle/{verb} -- dispatch lifecycle agent
- POST /api/mcp/{path:path}/discover         -- refresh catalog tool list
- GET  /api/catalog/{path:path}/ui_schema    -- inferred workload form

The catalog still stores Mcp resources via the existing
`/api/catalog/register` endpoint with `resource_type: mcp`; this module
adds *operations* on top, it does not change registration semantics.
"""

from .endpoint import router

__all__ = ["router"]
