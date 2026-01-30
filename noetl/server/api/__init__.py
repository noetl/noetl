"""
NoETL API package - V2 Event-Driven API only.

Pure event sourcing architecture:
- Event table is the single source of truth
- No legacy endpoints, no queue tables
- All state derived from events
"""

from fastapi import APIRouter
from fastapi.responses import JSONResponse

# V2 unified API (execute, events, commands)
from . import v2

# Essential management APIs (catalog, credentials, database utilities)
from . import credential, catalog, database, keychain

# Query/monitoring APIs
from . import execution, vars, dashboard, system, runtime

# Run API (playbook execution for sub-playbooks)
from . import run

# Context API (server-side template rendering)
from . import context

router = APIRouter()

@router.get("/health", response_class=JSONResponse)
async def api_health():
    return {"status": "ok"}

# V2 unified endpoints (execute, events, commands)
router.include_router(v2.router)

# Essential APIs
router.include_router(catalog.router)
router.include_router(credential.router)
router.include_router(database.router)
router.include_router(keychain.router)

# Query/monitoring APIs
router.include_router(execution.router)
router.include_router(vars.router)
router.include_router(dashboard.router)
router.include_router(system.router)
router.include_router(runtime.router)

# Run API (playbook execution for sub-playbooks)
router.include_router(run.router)

# Context API (server-side template rendering)
router.include_router(context.router)

__all__ = [
    "router",
    "v2",
    "catalog", "credential", "database", "keychain",
    "execution", "vars", "dashboard", "system", "runtime",
    "run", "context"
]
