"""
NoETL API package.

Execution state architecture:
- noetl.event is the append-only event-sourcing table
- noetl.command is the worker command projection
- noetl.execution is the execution-state projection
- APIs read command, event, and execution projections together
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

# Unified execution API (execute, events, commands)
from . import core

# Essential management APIs (catalog, credentials, database utilities)
from . import credential, catalog, database, keychain, playbook_tests

# MCP lifecycle / discovery / ui_schema operations on top of the catalog.
from . import mcp

# Query/monitoring APIs
from . import execution, vars, dashboard, system, runtime

# Context API (server-side template rendering)
from . import context

# Result storage API (preferred naming)
from . import result

# TempRef storage API (legacy, for backwards compatibility)
from . import temp

router = APIRouter()

@router.get("/health", response_class=JSONResponse)
async def api_health():
    return {"status": "ok"}

# Unified execution endpoints (execute, events, commands)
router.include_router(core.router)

# Essential APIs
router.include_router(catalog.router)
router.include_router(credential.router)
router.include_router(database.router)
router.include_router(keychain.router)
router.include_router(playbook_tests.router)

# MCP lifecycle / discovery / ui_schema endpoints — depend on catalog.
router.include_router(mcp.router)

# Query/monitoring APIs
router.include_router(execution.router)
router.include_router(vars.router)
router.include_router(dashboard.router)
router.include_router(system.router)
router.include_router(runtime.router)

# Context API (server-side template rendering)
router.include_router(context.router)

# Result storage API (preferred naming)
router.include_router(result.router)

# TempRef storage API (legacy, for backwards compatibility)
router.include_router(temp.router)

__all__ = [
    "router",
    "core",
    "catalog", "credential", "database", "keychain", "playbook_tests", "mcp",
    "execution", "vars", "dashboard", "system", "runtime",
    "context", "result", "temp"
]
