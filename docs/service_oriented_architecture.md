# Service-Oriented Architecture (SOA) Pattern in NoETL

## Overview

NoETL follows a service-oriented architecture pattern where each API package owns and manages its database table operations. This eliminates code duplication and establishes clear boundaries between components.

## Architecture Principles

### 1. Single Responsibility
Each service package owns operations for its specific database table:

```
noetl/server/api/
├── catalog/          → Manages noetl.catalog table
│   ├── service.py    → Catalog CRUD operations
│   ├── schema.py     → Pydantic models for catalog
│   └── endpoint.py   → REST API routes
│
├── broker/           → Manages noetl.event table
│   ├── service.py    → Event emission and queries
│   ├── schema.py     → Pydantic models for events
│   └── endpoint.py   → REST API routes
│
└── queue/            → Manages noetl.queue table
    ├── service.py    → Job enqueue/lease/complete
    ├── schema.py     → Pydantic models for queue
    └── endpoint.py   → REST API routes
```

### 2. No Code Duplication
When one service needs data from another table, it calls the owning service instead of writing duplicate SQL queries.

**Anti-Pattern (Before):**
```python
# queue/service.py - BAD: Duplicate query
async def enqueue_job(...):
    # Duplicating event table query
    async with conn.cursor() as cur:
        await cur.execute(
            "SELECT catalog_id FROM noetl.event WHERE execution_id = %s",
            (execution_id,)
        )
```

**Correct Pattern (After):**
```python
# queue/service.py - GOOD: Call EventService
from noetl.server.api.broker.service import EventService

async def enqueue_job(...):
    # Use EventService for event table queries
    catalog_id = await EventService.get_catalog_id_from_execution(execution_id)
```

### 3. Consistent Database Access Patterns

All services follow the same pattern for database operations:

```python
from psycopg.rows import dict_row
from noetl.core.db.pool import get_pool_connection

async def some_operation(...):
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute("SELECT field FROM table WHERE id = %(id)s", {"id": value})
            row = await cur.fetchone()
            if row:
                return row["field"]  # Dict access, not tuple
```

**Key components:**
- ✅ Use `get_pool_connection()` for connection pooling
- ✅ Use `row_factory=dict_row` for dictionary-based row access
- ✅ Use named parameters `%(param)s` with dict args
- ✅ Access fields by name `row["field"]` instead of index `row[0]`

## Service Communication Patterns

### Internal Server Communication
When services on the same server need to communicate, they call service methods directly:

```python
# Internal call within server
from noetl.server.api.broker.service import EventService
from noetl.server.api.catalog.service import CatalogService

# Queue service calls event service
catalog_id = await EventService.get_catalog_id_from_execution(execution_id)

# Run service calls catalog service
catalog_entry = await CatalogService.fetch_entry(path=path, version=version)
```

### External Communication
External clients (CLI, workers, other servers) communicate via REST API:

```python
# External call via REST API
import httpx

async with httpx.AsyncClient() as client:
    response = await client.post(
        f"{server_url}/api/events",
        json=event_payload
    )
```

## Service Responsibilities

### CatalogService (`noetl.server.api.catalog.service`)

**Owns:** `noetl.catalog` table

**Primary Operations:**
- `fetch_entry(catalog_id, path, version)` - Retrieve catalog entries
- `register_resource(content, resource_type)` - Register new playbooks/resources
- `fetch_entries(resource_type)` - List catalog entries
- `get_catalog_id(path, version)` - Get catalog ID for path+version
- `get_latest_version(path)` - Get latest version number

**Use When:**
- Loading playbook content
- Registering new playbooks
- Looking up catalog metadata
- Version management

### EventService (`noetl.server.api.broker.service`)

**Owns:** `noetl.event` table

**Primary Operations:**
- `emit_event(request)` - Emit execution events
- `get_event(event_id)` - Retrieve single event
- `list_events(query)` - Query events with filters
- `get_catalog_id_from_execution(execution_id)` - Get catalog from execution

**Use When:**
- Recording execution events
- Querying execution history
- Retrieving execution metadata
- Finding catalog_id for an execution

### QueueService (`noetl.server.api.queue.service`)

**Owns:** `noetl.queue` table

**Primary Operations:**
- `enqueue_job(...)` - Add job to queue
- `lease_job(worker_id)` - Atomically lease job for worker
- `complete_job(queue_id)` - Mark job completed
- `fail_job(queue_id)` - Mark job failed with retry
- `list_jobs(...)` - Query queue status

**Use When:**
- Publishing work to queue
- Workers leasing jobs
- Managing job lifecycle
- Queue monitoring

## Cross-Service Integration Examples

### Example 1: Queue Enqueuing Needs Catalog ID

```python
# noetl/server/api/queue/service.py
from noetl.server.api.broker.service import EventService

class QueueService:
    @staticmethod
    async def enqueue_job(execution_id: str, node_id: str, ...):
        # Convert execution_id to int
        execution_id_int = int(execution_id)
        
        # Get catalog_id from EventService (owns event table)
        catalog_id = await EventService.get_catalog_id_from_execution(execution_id_int)
        
        # Now enqueue job with catalog_id
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute(
                    """
                    INSERT INTO noetl.queue (execution_id, catalog_id, node_id, ...)
                    VALUES (%(execution_id)s, %(catalog_id)s, %(node_id)s, ...)
                    """,
                    {"execution_id": execution_id_int, "catalog_id": catalog_id, ...}
                )
```

### Example 2: Execution Service Needs Playbook Content

```python
# noetl/server/api/run/service.py
from noetl.server.api.catalog.service import CatalogService

class ExecutionService:
    @staticmethod
    async def execute_playbook(path: str, version: str):
        # Get playbook from CatalogService (owns catalog table)
        catalog_entry = await CatalogService.fetch_entry(path=path, version=version)
        
        # Parse and execute playbook
        playbook = yaml.safe_load(catalog_entry.content)
        ...
```

## Migration Pattern

When refactoring existing code to follow SOA pattern:

### Step 1: Identify Duplicate Queries
Look for SQL queries accessing tables owned by other services.

### Step 2: Check if Service Method Exists
Check the owning service for an existing method that provides the needed data.

### Step 3: Add Service Method if Needed
If no method exists, add one to the owning service:

```python
# Add to EventService
@staticmethod
async def get_catalog_id_from_execution(execution_id: int | str) -> int:
    """Get catalog_id from execution's first event."""
    execution_id_int = int(execution_id)
    
    async with get_pool_connection() as conn:
        async with conn.cursor(row_factory=dict_row) as cur:
            await cur.execute(
                "SELECT catalog_id FROM noetl.event WHERE execution_id = %(execution_id)s ORDER BY created_at LIMIT 1",
                {"execution_id": execution_id_int}
            )
            row = await cur.fetchone()
            if row and row["catalog_id"]:
                return int(row["catalog_id"])
            raise ValueError(f"No catalog_id found for execution {execution_id}")
```

### Step 4: Replace Duplicate Query with Service Call
```python
# Before
catalog_id = await self._query_catalog_id(execution_id)  # Duplicate

# After
from noetl.server.api.broker.service import EventService
catalog_id = await EventService.get_catalog_id_from_execution(execution_id)
```

### Step 5: Remove Duplicate Method
Delete the now-redundant method from the calling service.

## Benefits

### Code Maintainability
- **Single Source of Truth:** Each query exists in one place
- **Easier Updates:** Change SQL in one location, all callers benefit
- **Clear Ownership:** Know exactly which service to check for table operations

### Code Quality
- **Type Safety:** Service methods have clear type signatures
- **Error Handling:** Centralized error handling in service layer
- **Testing:** Mock service methods instead of database calls

### Performance
- **Connection Pooling:** Consistent use of `get_pool_connection()`
- **Query Optimization:** Optimize in one place, benefits all callers
- **Caching Potential:** Add caching at service layer when needed

### Team Collaboration
- **Clear Boundaries:** Each package has defined responsibilities
- **Parallel Development:** Teams can work on different services independently
- **Reduced Conflicts:** Less chance of merge conflicts in SQL queries

## Database Access Standards

### Required Pattern Elements

1. **Import Required Modules**
   ```python
   from psycopg.rows import dict_row
   from noetl.core.db.pool import get_pool_connection
   ```

2. **Use Connection Pool**
   ```python
   async with get_pool_connection() as conn:
   ```

3. **Use Dict Row Factory**
   ```python
   async with conn.cursor(row_factory=dict_row) as cur:
   ```

4. **Named Parameters**
   ```python
   await cur.execute(
       "SELECT field FROM table WHERE id = %(id)s",
       {"id": value}
   )
   ```

5. **Dict Row Access**
   ```python
   row = await cur.fetchone()
   if row:
       value = row["field"]  # Not row[0]
   ```

### Anti-Patterns to Avoid

❌ **Direct Database Access from Multiple Services**
```python
# In queue/service.py - BAD
async with conn.cursor() as cur:
    await cur.execute("SELECT catalog_id FROM noetl.event ...")
```

❌ **Tuple-Based Row Access**
```python
# BAD - fragile if column order changes
value = row[0]

# GOOD - explicit field names
value = row["field_name"]
```

❌ **Using get_async_db_connection**
```python
# OLD - deprecated
from noetl.core.common import get_async_db_connection

# NEW - use connection pool
from noetl.core.db.pool import get_pool_connection
```

❌ **Positional Parameters**
```python
# BAD - unclear what %s represents
await cur.execute("SELECT * FROM table WHERE id = %s", (id,))

# GOOD - named parameters are self-documenting
await cur.execute("SELECT * FROM table WHERE id = %(id)s", {"id": id})
```

## Service Discovery

To find which service owns a table operation:

1. **Identify the table:** `noetl.catalog`, `noetl.event`, `noetl.queue`, etc.
2. **Map to service package:**
   - `noetl.catalog` → `catalog/service.py`
   - `noetl.event` → `broker/service.py`
   - `noetl.queue` → `queue/service.py`
   - `noetl.workflow` → `run/planner.py` or `run/service.py`
   - `noetl.transition` → `run/planner.py` or `run/service.py`
3. **Check service methods:** Look for existing methods or add new ones
4. **Import and use:** `from noetl.server.api.{package}.service import {Service}`

## Future Enhancements

### Potential Improvements
- Add caching layer to frequently-accessed service methods
- Implement service-level metrics and monitoring
- Add service method versioning for backward compatibility
- Create service interface contracts with abstract base classes
- Add request/response validation at service boundaries

### Expansion Areas
- Add services for other tables (`noetl.workflow`, `noetl.transition`, etc.)
- Create composite services for complex cross-table operations
- Implement service-level authorization and access control
- Add service health checks and circuit breakers

## Related Documentation

- [Database Schema](./database_schema.md) - Complete database table definitions
- [API Usage](./api_usage.md) - REST API endpoint documentation
- [Architecture Overview](./architecture_overview.md) - High-level system architecture
- [Development Guide](./development.md) - Development setup and guidelines
