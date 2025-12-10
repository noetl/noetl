# NoETL DSL v2 Integration Guide

## Quick Start

This guide shows how to integrate NoETL DSL v2 into your NoETL deployment.

## Prerequisites

- NoETL codebase
- PostgreSQL database with noetl schema
- Python 3.9+
- Dependencies: pydantic, jinja2, yaml, httpx

## Step 1: Install v2 Components

The v2 components are already in the codebase:

```
noetl/core/dsl/v2/          # v2 DSL implementation
noetl/server/api/events_v2.py   # Event API
noetl/worker/executor_v2.py     # Worker executor
```

## Step 2: Database Schema

Create queue table if not exists:

```sql
CREATE TABLE IF NOT EXISTS noetl.queue (
    queue_id BIGSERIAL PRIMARY KEY,
    execution_id VARCHAR(64) NOT NULL,
    step VARCHAR(255) NOT NULL,
    tool_kind VARCHAR(50) NOT NULL,
    tool_config JSONB,
    args JSONB,
    context JSONB,
    attempt INTEGER DEFAULT 1,
    priority INTEGER DEFAULT 0,
    status VARCHAR(20) DEFAULT 'pending',
    assigned_worker_id VARCHAR(64),
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE INDEX idx_queue_status_priority ON noetl.queue(status, priority DESC, created_at ASC);
CREATE INDEX idx_queue_execution ON noetl.queue(execution_id);
CREATE INDEX idx_queue_worker ON noetl.queue(assigned_worker_id);
```

## Step 3: Register v2 API Routes

Add to your FastAPI server (`noetl/server/app.py`):

```python
from fastapi import FastAPI
from noetl.server.api.events_v2 import router as events_v2_router

app = FastAPI()

# Register v2 event API
app.include_router(events_v2_router)

# Your existing routes...
```

## Step 4: Start Server

```bash
# Start server with v2 API
python -m noetl.server.app
```

Server will expose:
- `POST /api/v2/events` - Event submission
- `GET /api/v2/health` - Health check
- `POST /api/v2/engine/register-playbook` - Playbook registration

## Step 5: Configure Worker

Create worker with v2 executor:

```python
import asyncio
from noetl.worker.executor_v2 import WorkerExecutorV2, QueuePollerV2

async def main():
    worker_id = "worker-001"
    server_url = "http://localhost:8000"
    
    # Create executor
    executor = WorkerExecutorV2(
        worker_id=worker_id,
        server_url=server_url
    )
    
    # Create poller
    poller = QueuePollerV2(
        worker_id=worker_id,
        server_url=server_url,
        executor=executor,
        poll_interval=1.0
    )
    
    # Start polling
    await poller.start()

if __name__ == "__main__":
    asyncio.run(main())
```

## Step 6: Register Playbook

```python
import httpx
from pathlib import Path

# Read playbook
playbook_yaml = Path("weather_loop_v2.yaml").read_text()

# Register via API
response = httpx.post(
    "http://localhost:8000/api/v2/engine/register-playbook",
    json={"playbook_yaml": playbook_yaml}
)

print(response.json())
# {"status": "registered", "name": "weather_loop_v2", "path": "examples/weather_loop_v2"}
```

## Step 7: Start Execution

Submit workflow start event:

```python
import httpx

event = {
    "execution_id": "exec-123",
    "name": "workflow.start",
    "payload": {}
}

response = httpx.post(
    "http://localhost:8000/api/v2/events",
    json=event
)

print(response.json())
# {"status": "processed", "commands_generated": 1, ...}
```

## Architecture Flow

```
1. Client submits workflow.start event
2. Server receives event at /api/v2/events
3. Engine evaluates DSL, generates command for 'start' step
4. Server inserts command into queue table
5. Worker polls queue, leases command
6. Worker executes command (HTTP/SQL/Python)
7. Worker emits call.done event back to server
8. Server evaluates case rules, generates next command(s)
9. Repeat until workflow completes
```

## Example: Pagination Flow

### Playbook

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: pagination_example
  path: examples/pagination
workflow:
  - step: start
    tool:
      kind: http
      method: GET
      endpoint: https://api.example.com/data
      params:
        page: 1
    case:
      - when: "{{ event.name == 'step.enter' }}"
        then:
          set:
            ctx:
              pages: []
      
      - when: >-
          {{ event.name == 'call.done'
             and response.data.hasMore }}
        then:
          collect:
            from: response.data.items
            into: pages
            mode: extend
          call:
            params:
              page: "{{ (response.data.page | int) + 1 }}"
      
      - when: >-
          {{ event.name == 'call.done'
             and not response.data.hasMore }}
        then:
          collect:
            from: response.data.items
            into: pages
            mode: extend
          result:
            from: pages
```

### Event Flow

1. **workflow.start** → Engine generates command for 'start' step
2. Worker executes HTTP GET page=1
3. Worker emits **step.enter** → Engine sets ctx.pages = []
4. Worker emits **call.done** with response.data.hasMore = true
5. Engine evaluates case, collects data, generates new command with page=2
6. Worker executes HTTP GET page=2
7. Worker emits **call.done** with response.data.hasMore = false
8. Engine collects final data, sets result, workflow completes

## Testing v2 Playbooks

```bash
# Validate playbook syntax
python -c "
from noetl.core.dsl.v2.parser import validate_playbook_file
validate_playbook_file('weather_loop_v2.yaml')
"

# Run unit tests
pytest tests/unit/dsl/v2/

# Test specific functionality
pytest tests/unit/dsl/v2/test_engine.py::TestControlFlowEngine::test_pagination_collect
```

## Debugging

### Enable Debug Logging

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

### Inspect Events

Query event log:

```sql
SELECT 
    event_id,
    execution_id,
    event_type,
    node_name,
    status,
    created_at
FROM noetl.event
WHERE execution_id = 'exec-123'
ORDER BY created_at;
```

### Inspect Queue

```sql
SELECT 
    queue_id,
    execution_id,
    step,
    tool_kind,
    status,
    attempt,
    created_at
FROM noetl.queue
WHERE execution_id = 'exec-123'
ORDER BY created_at;
```

### Check Engine State

```python
from noetl.core.dsl.v2.engine import state_store

state = state_store.get_state("exec-123")
print(f"Current step: {state.current_step}")
print(f"Step results: {state.step_results}")
print(f"Context: {state.context}")
print(f"Workflow status: {state.workflow_status}")
```

## Common Issues

### Issue: Events not processed

**Symptom:** Events submitted but no commands generated

**Solution:**
1. Check playbook is registered: `playbook_repo._playbooks`
2. Verify event format matches Event model
3. Check engine logs for errors
4. Ensure execution_id has state in state_store

### Issue: Workers not executing commands

**Symptom:** Commands in queue but workers idle

**Solution:**
1. Verify worker polling is running
2. Check queue table has pending commands
3. Ensure worker can connect to server
4. Check worker logs for errors

### Issue: Case rules not matching

**Symptom:** Expected transitions not happening

**Solution:**
1. Check `when` condition syntax
2. Verify Jinja2 context has expected variables
3. Test condition in isolation
4. Enable debug logging to see context

### Issue: Infinite pagination loop

**Symptom:** Pagination never stops

**Solution:**
1. Add `max_iterations` check in context
2. Verify response.data.hasMore condition
3. Check API response format matches template
4. Add timeout/iteration counter

## Performance Tuning

### Engine Performance

- State store can be Redis instead of in-memory
- Playbook repo can cache compiled Jinja2 templates
- Use connection pooling for database operations

### Worker Performance

- Run multiple workers (horizontal scaling)
- Adjust poll_interval based on workload
- Use connection pooling for HTTP clients
- Consider async/parallel execution for loops

### Queue Performance

- Add indexes on queue table (status, priority, execution_id)
- Use SKIP LOCKED for concurrent worker access
- Archive completed queue records periodically
- Use partitioning for large queue tables

## Migration from v1

### Automated Migration Tool

```python
from noetl.core.dsl.v2.migration import migrate_v1_to_v2

# Read v1 playbook
with open("old_playbook.yaml") as f:
    v1_yaml = f.read()

# Migrate to v2
v2_yaml = migrate_v1_to_v2(v1_yaml)

# Save v2 playbook
with open("new_playbook_v2.yaml", "w") as f:
    f.write(v2_yaml)
```

*Note: Migration tool is a placeholder - manual migration recommended for complex playbooks*

### Manual Migration Checklist

- [ ] Change `type:` to `tool.kind:`
- [ ] Move tool config under `tool:`
- [ ] Convert `next.when/then/else` to `case[].when/then`
- [ ] Replace `with:` with `args:` for cross-step data
- [ ] Update event references (e.g., `{{ event.name == 'call.done' }}`)
- [ ] Test playbook with v2 parser
- [ ] Validate with unit tests

## Production Deployment

### Deployment Checklist

- [ ] v2 API routes registered
- [ ] Queue table created with indexes
- [ ] Workers configured with executor_v2
- [ ] Playbooks migrated to v2 format
- [ ] State store configured (Redis recommended)
- [ ] Monitoring/alerting setup
- [ ] Load testing completed
- [ ] Rollback plan documented

### Monitoring

Key metrics to track:
- Event processing latency
- Command generation rate
- Queue depth
- Worker utilization
- Case match rate
- Retry/failure rate

### Rollback Strategy

If issues occur:
1. Stop accepting new v2 workflows
2. Complete in-flight v2 executions
3. Revert to v1 endpoints
4. Analyze v2 logs/metrics
5. Fix issues and redeploy

## Resources

- **Documentation:** `docs/dsl_v2_specification.md`
- **Examples:** `tests/fixtures/playbooks/examples/`
- **Unit Tests:** `tests/unit/dsl/v2/`
- **API Reference:** `http://localhost:8000/docs` (when server running)

## Support

For issues or questions:
1. Check documentation and examples
2. Review unit tests for patterns
3. Enable debug logging
4. Query event/queue tables
5. File issue with reproduction steps
