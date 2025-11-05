# Plugin Architecture Refactoring Analysis

## Current Structure Analysis

### Directory Structure

```
noetl/plugin/
├── __init__.py                 # Main plugin registry
├── auth/                       # Shared: Authentication resolution
│   ├── constants.py
│   ├── duckdb.py
│   ├── http.py
│   ├── normalize.py
│   ├── postgres.py
│   ├── resolver.py
│   └── utils.py
├── tool/                       # Shared: Worker utilities (MCP-compliant)
│   ├── execution.py            # Task routing/execution
│   ├── reporting.py            # Event reporting to server
│   ├── retry.py                # Retry policy evaluation
│   └── sql.py                  # SQL utilities
├── save/                       # Shared: Result storage handlers
│   ├── config.py
│   ├── duckdb.py
│   ├── executor.py
│   ├── http.py
│   ├── postgres.py
│   ├── python.py
│   └── rendering.py
├── result/                     # Shared: Loop result aggregation
│   └── aggregation.py
├── secret/                     # Shared: External secret resolution
│   ├── executor.py
│   └── wrapper.py
├── iterator/                   # Shared: Loop execution control
│   ├── config.py
│   ├── execution.py
│   ├── executor.py
│   └── utils.py
├── workbook/                   # Shared: Reusable task catalog
│   ├── catalog.py
│   └── executor.py
├── postgres/                   # Action Plugin: PostgreSQL tasks
│   ├── auth.py
│   ├── command.py
│   ├── execution.py
│   ├── executor.py
│   └── response.py
├── http/                       # Action Plugin: HTTP requests
│   ├── auth.py
│   ├── executor.py
│   └── response.py
├── python/                     # Action Plugin: Python code execution
│   └── executor.py
├── duckdb/                     # Action Plugin: DuckDB queries
│   ├── auth/
│   ├── config.py
│   ├── connections.py
│   ├── executor.py
│   ├── sql/
│   └── types.py
├── snowflake/                  # Action Plugin: Snowflake tasks
│   ├── auth.py
│   ├── command.py
│   ├── execution.py
│   ├── executor.py
│   ├── response.py
│   └── transfer.py
├── snowflake_transfer/         # Action Plugin: Snowflake data transfer
│   └── executor.py
└── transfer/                   # Action Plugin: Data transfer tasks
    └── executor.py
```

### Current Import Patterns

**Worker imports from plugins:**
```python
from noetl.plugin import report_event          # 7 places in worker.py
from noetl.plugin import execute_task          # 1 place in worker.py
from noetl.plugin.tool.retry import RetryPolicy  # 1 place in worker.py
from noetl.plugin.result import process_loop_aggregation_job  # 1 place in worker.py
```

**Plugin cross-dependencies:**
```python
# iterator uses save
from noetl.plugin.save import execute_save_task

# All action plugins use shared tool/auth
from ..auth import resolve_*_auth
```

## Problem Statement

1. **Naming Confusion**: `noetl/plugin/tool` doesn't clearly indicate it's a shared library for worker-plugin communication
2. **Mixed Responsibilities**: Some modules are shared infrastructure (tool, auth, save, result, iterator, workbook, secret), while others are action implementations (postgres, http, python, duckdb, snowflake)
3. **Unclear Boundaries**: No clear separation between:
   - Worker-side infrastructure (tool, reporting, retry)
   - Plugin-side shared utilities (auth, save)
   - Controller plugins (iterator, workbook, result, secret)
   - Action plugins (postgres, http, python, duckdb, snowflake)
4. **Direct Database Access**: workbook/catalog.py still accesses NoETL database directly (should use HTTP API)

## Proposed Refactoring

### Option 1: Three-Tier Structure (Recommended)

```
noetl/plugin/
├── __init__.py                     # Main registry

# TIER 1: Worker Runtime (shared infrastructure for all plugins)
├── runtime/                        # Renamed from 'tool'
│   ├── __init__.py
│   ├── execution.py                # Task routing
│   ├── events.py                   # Renamed from reporting.py
│   ├── retry.py                    # Retry policy
│   └── utils.py                    # SQL split, etc.

# TIER 2: Shared Services (cross-plugin functionality)
├── shared/
│   ├── __init__.py
│   ├── auth/                       # Authentication resolution
│   │   ├── __init__.py
│   │   ├── constants.py
│   │   ├── resolver.py
│   │   ├── postgres.py
│   │   ├── http.py
│   │   ├── duckdb.py
│   │   └── utils.py
│   ├── storage/                    # Renamed from 'save'
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── executor.py
│   │   ├── postgres.py
│   │   ├── duckdb.py
│   │   ├── http.py
│   │   └── python.py
│   └── secrets/                    # External secret manager integration
│       ├── __init__.py
│       ├── executor.py
│       └── wrapper.py

# TIER 3: Controller Plugins (special-purpose executors)
├── controller/
│   ├── __init__.py
│   ├── iterator/                   # Loop execution
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── execution.py
│   │   └── executor.py
│   ├── workbook/                   # Reusable task catalog
│   │   ├── __init__.py
│   │   ├── catalog.py              # TODO: Remove direct DB access
│   │   └── executor.py
│   ├── result/                     # Result aggregation
│   │   ├── __init__.py
│   │   └── aggregation.py
│   └── playbook/                   # Sub-playbook execution
│       ├── __init__.py
│       └── executor.py

# TIER 4: Action Plugins (task type implementations)
├── actions/
│   ├── __init__.py
│   ├── postgres/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── command.py
│   │   ├── execution.py
│   │   ├── executor.py
│   │   └── response.py
│   ├── http/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── executor.py
│   │   └── response.py
│   ├── python/
│   │   ├── __init__.py
│   │   └── executor.py
│   ├── duckdb/
│   │   ├── __init__.py
│   │   ├── auth/
│   │   ├── config.py
│   │   ├── connections.py
│   │   ├── executor.py
│   │   └── sql/
│   ├── snowflake/
│   │   ├── __init__.py
│   │   ├── auth.py
│   │   ├── command.py
│   │   ├── execution.py
│   │   ├── executor.py
│   │   └── response.py
│   └── transfer/
│       ├── __init__.py
│       ├── snowflake_transfer/
│       │   └── executor.py
│       └── generic/
│           └── executor.py
```

### Option 2: Flat with Prefixes (Simpler Migration)

```
noetl/plugin/
├── __init__.py

# Shared infrastructure (prefix: core_)
├── core_runtime/                   # Renamed from tool
├── core_auth/                      # Shared auth
├── core_storage/                   # Renamed from save
├── core_secrets/                   # Shared secrets

# Controller (prefix: flow_)
├── flow_iterator/
├── flow_workbook/
├── flow_result/
├── flow_playbook/

# Actions (no prefix needed - clear context)
├── postgres/
├── http/
├── python/
├── duckdb/
├── snowflake/
└── transfer/
```

## Recommended Approach: Option 1 (Three-Tier)

### Rationale

1. **Clear Separation of Concerns**:
   - `runtime/` = Worker infrastructure (events, execution routing, retry)
   - `shared/` = Cross-plugin services (auth, storage, secrets)
   - `controller/` = Flow control plugins (iterator, workbook, result)
   - `actions/` = Task execution plugins (postgres, http, python, etc.)

2. **Better Discoverability**:
   - New developers immediately understand the hierarchy
   - Clear import paths indicate functionality level
   - Self-documenting structure

3. **Cleaner Dependencies**:
   ```python
   # Worker imports
   from noetl.plugin.runtime import execute_task, report_event, RetryPolicy
   
   # Action plugins import
   from noetl.plugin.shared.auth import resolve_auth_map
   from noetl.plugin.shared.storage import execute_save_task
   
   # Controller plugins import
   from noetl.plugin.runtime import report_event
   from noetl.plugin.shared.storage import execute_save_task
   ```

4. **Extensibility**:
   - Easy to add new action plugins under `actions/`
   - Easy to add new shared services under `shared/`
   - Clear place for new controller patterns

## Migration Plan

### Phase 1: Rename and Reorganize (No Breaking Changes)

1. **Create new directory structure** while keeping old imports working via `__init__.py` re-exports
2. **Move modules** to new locations:
   ```bash
   # Runtime
   mv noetl/plugin/tool noetl/plugin/runtime
   mv noetl/plugin/runtime/reporting.py noetl/plugin/runtime/events.py
   
   # Shared services
   mkdir -p noetl/plugin/shared/{auth,storage,secrets}
   mv noetl/plugin/auth/* noetl/plugin/shared/auth/
   mv noetl/plugin/save/* noetl/plugin/shared/storage/
   mv noetl/plugin/secret/* noetl/plugin/shared/secrets/
   
   # Controller
   mkdir -p noetl/plugin/controller
   mv noetl/plugin/{iterator,workbook,result,playbook} noetl/plugin/controller/
   
   # Actions
   mkdir -p noetl/plugin/actions
   mv noetl/plugin/{postgres,http,python,duckdb,snowflake,snowflake_transfer,transfer} noetl/plugin/actions/
   ```

3. **Update `noetl/plugin/__init__.py`** to maintain backward compatibility:
   ```python
   # Backward compatibility exports
   from .runtime import execute_task, report_event, sql_split
   from .runtime.retry import RetryPolicy
   from .controller.result import process_loop_aggregation_job
   
   # Action executors
   from .actions.postgres import execute_postgres_task
   from .actions.http import execute_http_task
   # ... etc
   ```

### Phase 2: Update Imports (Gradual)

1. **Update worker imports** (noetl/worker/worker.py):
   ```python
   # New imports
   from noetl.plugin.runtime import execute_task, report_event, RetryPolicy
   from noetl.plugin.controller.result import process_loop_aggregation_job
   ```

2. **Update action plugin imports**:
   ```python
   # In postgres/executor.py
   from noetl.plugin.shared.auth import resolve_auth_map
   
   # In iterator/executor.py
   from noetl.plugin.shared.storage import execute_save_task
   ```

3. **Remove backward compatibility** exports after all imports updated

### Phase 3: Fix Architectural Issues

1. **Remove direct DB access in workbook/catalog.py**:
   - Add server API endpoint: `GET /api/workload/{execution_id}`
   - Update workbook plugin to fetch via HTTP
   - Remove `get_async_db_connection` import

2. **Consolidate transfer plugins**:
   - Move `snowflake_transfer` under `actions/transfer/snowflake/`
   - Create `actions/transfer/` as parent package

## Benefits

### Developer Experience
- **Clear mental model**: Three tiers (runtime, shared, plugins)
- **Easy navigation**: Find code by responsibility level
- **Self-documenting**: Directory names explain purpose

### Maintainability
- **Isolated changes**: Changes to action plugins don't affect runtime
- **Clear dependencies**: Import paths show dependency direction
- **Testability**: Each tier can be tested independently

### Extensibility
- **Add new action plugins**: Just create under `actions/`
- **Add new shared services**: Add under `shared/`
- **Add new controller patterns**: Add under `controller/`

## Implementation Checklist

- [ ] Create new directory structure
- [ ] Move modules to new locations
- [ ] Update `__init__.py` for backward compatibility
- [ ] Update worker imports
- [ ] Update plugin imports
- [ ] Update tests
- [ ] Update documentation
- [ ] Remove workbook direct DB access
- [ ] Remove backward compatibility exports
- [ ] Update deployment scripts if needed

## Notes

- **No functional changes**: This is a pure refactoring for better organization
- **Backward compatible**: Old imports work during migration
- **Gradual migration**: Can be done incrementally without breaking existing code
- **Worker-only**: Plugins should only be imported/used in worker, never in server
