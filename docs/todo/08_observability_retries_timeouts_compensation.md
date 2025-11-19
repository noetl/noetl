# Observability, Retries/DLQ, Timeouts, Compensation

**Status:** Planning  
**Date:** November 6, 2025  
**Objective:** Define complete observability, resilience, and operational patterns for DSL v2 runtime

---

## 8.1 Metrics (Server & Worker)

**Format:** Prometheus-style metrics  
**Export:** `/metrics` endpoint on server; worker uses small HTTP exporter or pushes to gateway

---

### Server Metrics

**Execution Lifecycle:**
```prometheus
# Total executions started
noetl_executions_started_total{workflow}

# Total executions completed by status
noetl_executions_completed_total{workflow, status}
# status: ok|fail|canceled

# Times a step was called (may be parked)
noetl_step_calls_total{workflow, step}

# Times a step actually executed (idempotent)
noetl_step_runs_total{workflow, step}

# Step wall-clock duration (dispatch → done)
noetl_step_duration_seconds{workflow, step}
# Type: Histogram
# Buckets: 0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300
```

---

**Loop Execution:**
```prometheus
# Total planned loop items
noetl_loop_items_total{workflow, step}

# Completed loop items by outcome
noetl_loop_completed_total{workflow, step, ok}
# ok: true|false
```

---

**Queue & Tasks:**
```prometheus
# Gauge of enqueued minus acknowledged tasks
noetl_task_queue_inflight{pool}
# Type: Gauge
```

---

**Sinks:**
```prometheus
# Sink dispatches
noetl_sink_dispatch_total{sink, workflow, step}

# Sink duration
noetl_sink_duration_seconds{sink, workflow, step}
# Type: Histogram
# Buckets: 0.01, 0.05, 0.1, 0.2, 0.5, 1, 2
```

---

**Control Flow:**
```prometheus
# When condition evaluations
noetl_when_eval_total{workflow, step, outcome}
# outcome: true|false|error

# Edge evaluations (routing)
noetl_edge_eval_total{workflow, from, to, outcome}
# outcome: taken|skipped|error
```

---

### Worker Metrics

**Task Execution:**
```prometheus
# Tasks started
noetl_worker_tasks_started_total{kind, pool}

# Tasks completed
noetl_worker_tasks_completed_total{kind, pool, ok}
# ok: true|false

# Task duration
noetl_worker_task_duration_seconds{kind}
# Type: Histogram
# Buckets (by kind):
# - HTTP: 0.05, 0.1, 0.2, 0.5, 1, 2, 5
# - DB: 0.01, 0.05, 0.1, 0.2, 0.5, 1, 2
# - Python: 0.1, 0.5, 1, 2, 5, 10, 30
```

---

**Sinks:**
```prometheus
# Sink task completions
noetl_sink_tasks_completed_total{sink, ok}
# ok: true|false
```

---

**Errors:**
```prometheus
# Plugin errors by class
noetl_plugin_errors_total{kind, error_class}
# error_class: RetryableError|FatalError|TimeoutError|...
```

---

### Implementation Target

```python
# File: noetl/observability/metrics.py

from prometheus_client import Counter, Histogram, Gauge

# ===== Server Metrics =====

executions_started = Counter(
    'noetl_executions_started_total',
    'Total executions started',
    ['workflow']
)

executions_completed = Counter(
    'noetl_executions_completed_total',
    'Total executions completed',
    ['workflow', 'status']
)

step_calls = Counter(
    'noetl_step_calls_total',
    'Times a step was called',
    ['workflow', 'step']
)

step_runs = Counter(
    'noetl_step_runs_total',
    'Times a step actually executed',
    ['workflow', 'step']
)

step_duration = Histogram(
    'noetl_step_duration_seconds',
    'Step duration (dispatch to done)',
    ['workflow', 'step'],
    buckets=[0.1, 0.5, 1, 2, 5, 10, 30, 60, 120, 300]
)

loop_items = Counter(
    'noetl_loop_items_total',
    'Total planned loop items',
    ['workflow', 'step']
)

loop_completed = Counter(
    'noetl_loop_completed_total',
    'Completed loop items by outcome',
    ['workflow', 'step', 'ok']
)

task_queue_inflight = Gauge(
    'noetl_task_queue_inflight',
    'Enqueued minus acknowledged tasks',
    ['pool']
)

sink_dispatch = Counter(
    'noetl_sink_dispatch_total',
    'Sink dispatches',
    ['sink', 'workflow', 'step']
)

sink_duration = Histogram(
    'noetl_sink_duration_seconds',
    'Sink duration',
    ['sink', 'workflow', 'step'],
    buckets=[0.01, 0.05, 0.1, 0.2, 0.5, 1, 2]
)

when_eval = Counter(
    'noetl_when_eval_total',
    'When condition evaluations',
    ['workflow', 'step', 'outcome']
)

edge_eval = Counter(
    'noetl_edge_eval_total',
    'Edge evaluations',
    ['workflow', 'from', 'to', 'outcome']
)

# ===== Worker Metrics =====

worker_tasks_started = Counter(
    'noetl_worker_tasks_started_total',
    'Tasks started',
    ['kind', 'pool']
)

worker_tasks_completed = Counter(
    'noetl_worker_tasks_completed_total',
    'Tasks completed',
    ['kind', 'pool', 'ok']
)

worker_task_duration = Histogram(
    'noetl_worker_task_duration_seconds',
    'Task duration',
    ['kind'],
    buckets=[0.01, 0.05, 0.1, 0.2, 0.5, 1, 2, 5, 10, 30]
)

sink_tasks_completed = Counter(
    'noetl_sink_tasks_completed_total',
    'Sink task completions',
    ['sink', 'ok']
)

plugin_errors = Counter(
    'noetl_plugin_errors_total',
    'Plugin errors by class',
    ['kind', 'error_class']
)
```

---

## 8.2 Structured Logging (Context-Rich)

**Format:** JSON Lines  
**Auto-inject:** Use logger adapter for execution/step/message context

---

### Common Fields (Server & Worker)

```json
{
  "ts": "2025-11-06T12:00:00.123Z",
  "level": "INFO",
  "logger": "noetl.server.orchestrator",
  "msg": "Step dispatched",
  "execution_id": "484377543601029219",
  "workflow_ref": "playbooks/user_processor",
  "step_id": "fetch_user",
  "call_id": "uuid",
  "loop_index": 0,
  "loop_key": "user_123",
  "tool_kind": "http",
  "sink_id": "postgres:results",
  "attempt": 1,
  "max_attempts": 6,
  "backoff_ms": 200,
  "duration_ms": 1234,
  "ok": true,
  "error_class": "RetryableError",
  "error": "Connection timeout"
}
```

---

### Server Log Events

**`step_called`** - Step called by predecessor
```json
{
  "event": "step_called",
  "step_id": "process_user",
  "reason": "predecessor:fetch_user",
  "edge_index": 0
}
```

---

**`step_parked`** - Step parked (when=false)
```json
{
  "event": "step_parked",
  "step_id": "conditional_step",
  "when_expr": "{{ done('upstream') }}",
  "when_result": false
}
```

---

**`step_dispatch`** - Step dispatched for execution
```json
{
  "event": "step_dispatch",
  "step_id": "process_users",
  "loop_plan": {
    "total": 100,
    "mode": "parallel"
  }
}
```

---

**`task_enqueue`** - Task enqueued to worker
```json
{
  "event": "task_enqueue",
  "message_id": "uuid",
  "step_id": "fetch_user",
  "tool_kind": "http",
  "priority": 0,
  "not_before": "2025-11-06T12:00:00Z"
}
```

---

**`result_integrate`** - Result integrated into context
```json
{
  "event": "result_integrate",
  "step_id": "fetch_user",
  "as": "user_data",
  "collect": {
    "into": "all_users",
    "mode": "list"
  }
}
```

---

**`sink_dispatch`** - Sink dispatched
```json
{
  "event": "sink_dispatch",
  "step_id": "process_user",
  "sink_id": "postgres:results",
  "sink_type": "postgres"
}
```

---

**`step_done`** - Step completed
```json
{
  "event": "step_done",
  "step_id": "process_users",
  "ok": true,
  "done": true,
  "counters": {
    "total": 100,
    "completed": 100,
    "succeeded": 98,
    "failed": 2
  }
}
```

---

**`route_edge_selected`** - Routing edge selected
```json
{
  "event": "route_edge_selected",
  "from_step": "process_user",
  "edge_index": 0,
  "target_step": "summarize",
  "condition": "{{ ok('process_user') }}"
}
```

---

### Worker Log Events

**`task_claimed`** - Task claimed from queue
```json
{
  "event": "task_claimed",
  "message_id": "uuid",
  "step_id": "fetch_user",
  "tool_kind": "http",
  "attempt": 1,
  "worker_id": "worker-01"
}
```

---

**`plugin_start`** - Plugin execution started
```json
{
  "event": "plugin_start",
  "tool_kind": "http",
  "spec_signature": "GET https://api.example.com/users/{id}"
}
```

---

**`plugin_done`** - Plugin execution completed
```json
{
  "event": "plugin_done",
  "tool_kind": "http",
  "duration_ms": 1234,
  "ok": true
}
```

---

**`sink_start`** - Sink write started
```json
{
  "event": "sink_start",
  "sink_id": "postgres:results",
  "sink_type": "postgres"
}
```

---

**`sink_done`** - Sink write completed
```json
{
  "event": "sink_done",
  "sink_id": "postgres:results",
  "duration_ms": 234,
  "ok": true
}
```

---

**`task_ack`** - Task acknowledged (result reported)
```json
{
  "event": "task_ack",
  "message_id": "uuid",
  "ok": true,
  "duration_ms": 1500
}
```

---

**`task_retry`** - Task will be retried
```json
{
  "event": "task_retry",
  "message_id": "uuid",
  "attempt": 2,
  "next_delay_ms": 400,
  "error_class": "RetryableError"
}
```

---

**`task_dlq`** - Task moved to DLQ (final failure)
```json
{
  "event": "task_dlq",
  "message_id": "uuid",
  "attempt": 6,
  "error_class": "FatalError",
  "error": "Schema validation failed"
}
```

---

### Implementation Target

```python
# File: noetl/observability/logging.py

import logging
import json
from typing import Any

class ContextAdapter(logging.LoggerAdapter):
    """Logger adapter with auto-injected context"""
    
    def process(self, msg, kwargs):
        # Merge extra context
        extra = kwargs.get('extra', {})
        extra.update(self.extra)
        kwargs['extra'] = extra
        return msg, kwargs

class StructuredLogger:
    """JSON-formatted structured logger"""
    
    def __init__(self, name: str, context: dict = None):
        self.logger = logging.getLogger(name)
        self.context = context or {}
        self.adapter = ContextAdapter(self.logger, self.context)
    
    def event(self, event_name: str, **kwargs):
        """Log structured event"""
        data = {
            "event": event_name,
            **self.context,
            **kwargs
        }
        self.adapter.info(json.dumps(data))
    
    def with_context(self, **kwargs) -> 'StructuredLogger':
        """Create new logger with added context"""
        new_context = {**self.context, **kwargs}
        return StructuredLogger(self.logger.name, new_context)

# Usage example
logger = StructuredLogger("noetl.server")
logger = logger.with_context(
    execution_id="484377543601029219",
    workflow_ref="playbooks/user_processor"
)

logger.event("step_dispatch", 
    step_id="fetch_user",
    loop_plan={"total": 100, "mode": "parallel"}
)
```

---

## 8.3 Tracing (OpenTelemetry)

---

### Trace Model

**Root Span: `server.execution`**
- Attributes: `execution_id`, `workflow_ref`, `workload_size`

**Span: `server.dispatch`**
- Parent: `server.execution`
- Attributes: `execution_id`, `step_id`, `loop_index`, `tool_kind`

**Child Span: `worker.plugin.<kind>`**
- Parent: `server.dispatch`
- Attributes: 
  - `spec_signature` (redacted, e.g., "GET https://api.example.com/users/{id}")
  - `args_signature` (redacted keys)
  - `attempt`

**Child Spans: `worker.sink.<sink_id>`**
- Parent: `server.dispatch`
- Attributes: `sink_type`, `table`, `mode`, `rows_written`

**Span: `server.route`**
- Parent: `server.execution`
- Attributes: `from_step`, `edge_index`, `target_step`, `condition`

**Span: `server.when_eval`**
- Parent: `server.dispatch`
- Attributes: `step_id`, `when_expr`, `outcome` (true|false|error)

---

### Baggage/Links

**Propagation:**
- Carry `execution_id`, `step_id`, `message_id` via:
  - HTTP headers: `traceparent`, `tracestate`
  - Queue message attributes: `trace_context`

**HTTP Plugin:**
- If using HTTP plugin, propagate `traceparent` downstream
- Capture remote spans as linked spans

---

### Sampling

**Default:** 5–10% sample rate

**Force sampling:**
- Executions tagged with `workload.trace=true`
- CLI flag: `clictl exec start --trace`
- Duration > P99 (tail-based sampling)

---

### Implementation Target

```python
# File: noetl/observability/tracing.py

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

tracer = trace.get_tracer("noetl")

class TracingContext:
    """Tracing utilities"""
    
    @staticmethod
    def start_execution(execution_id: str, workflow_ref: str):
        """Start root execution span"""
        span = tracer.start_span(
            "server.execution",
            attributes={
                "execution_id": execution_id,
                "workflow_ref": workflow_ref
            }
        )
        return span
    
    @staticmethod
    def start_dispatch(execution_id: str, step_id: str, tool_kind: str, loop_index: int = None):
        """Start dispatch span"""
        attributes = {
            "execution_id": execution_id,
            "step_id": step_id,
            "tool_kind": tool_kind
        }
        if loop_index is not None:
            attributes["loop_index"] = loop_index
        
        span = tracer.start_span("server.dispatch", attributes=attributes)
        return span
    
    @staticmethod
    def start_plugin(kind: str, spec_signature: str, attempt: int):
        """Start plugin execution span"""
        span = tracer.start_span(
            f"worker.plugin.{kind}",
            attributes={
                "spec_signature": spec_signature,
                "attempt": attempt
            }
        )
        return span
    
    @staticmethod
    def start_sink(sink_id: str, sink_type: str):
        """Start sink write span"""
        span = tracer.start_span(
            f"worker.sink.{sink_id}",
            attributes={
                "sink_type": sink_type,
                "sink_id": sink_id
            }
        )
        return span

# Usage
with TracingContext.start_execution(exec_id, workflow) as exec_span:
    with TracingContext.start_dispatch(exec_id, step_id, "http") as dispatch_span:
        # Dispatch work
        pass
```

---

## 8.4 Retries, Backoff, and Idempotency

---

### Retry Taxonomy

**Plugin Retry (Worker, Transient Errors):**
- Config: `retries.plugin.max_attempts`, `retries.plugin.base_ms`, `retries.plugin.max_ms`
- Jitter: enabled

**Sink Retry (Worker, Write Failures):**
- Config: `retries.sink.max_attempts`, `retries.sink.base_ms`, `retries.sink.max_ms`
- Jitter: enabled

**Dispatch Retry (Server, Queue Delivery):**
- Config: `retries.dispatch.max_attempts`

---

### Backoff Strategy

**Exponential with Jitter:**

```python
delay_ms = min(base * 2**attempt, max) * (0.5 + random())
```

**Example Defaults:**
- `base_ms`: 200
- `max_ms`: 30000 (30 seconds)
- `max_attempts`: 6
- **Worst case:** ~30–60 seconds total

**Implementation:**

```python
# File: noetl/worker/retry.py

import random
import time

class RetryPolicy:
    def __init__(self, max_attempts: int = 6, base_ms: int = 200, max_ms: int = 30000):
        self.max_attempts = max_attempts
        self.base_ms = base_ms
        self.max_ms = max_ms
    
    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay in seconds with exponential backoff and jitter"""
        delay_ms = min(self.base_ms * (2 ** attempt), self.max_ms)
        jitter = 0.5 + random.random()
        return (delay_ms * jitter) / 1000.0
    
    def should_retry(self, attempt: int, error: Exception) -> bool:
        """Determine if error is retryable"""
        if attempt >= self.max_attempts:
            return False
        
        if isinstance(error, (RetryableError, TimeoutError)):
            return True
        
        if isinstance(error, FatalError):
            return False
        
        # Default: retry transient errors
        return self._is_retryable(error)
    
    def _is_retryable(self, error: Exception) -> bool:
        """Check if error class is retryable"""
        error_name = error.__class__.__name__
        return error_name in [
            'ConnectionError',
            'Timeout',
            'HTTPError',  # Check status code separately
            'SerializationError',
            'DeadlockError'
        ]
```

---

### Idempotency Keys

**Tasks:**
```
{execution_id}:{step_id}[:{loop_key|loop_index}]
```

**Sinks:**
```
{execution_id}:{step_id}:{loop_key|loop_index}:{sink_id}
```

**Usage:**
- UPSERT keys in database writes
- Dedupe tables
- S3/GCS object metadata headers
- HTTP `Idempotency-Key` header

**Example:**

```python
# Server-side idempotency key generation
def generate_idempotency_key(execution_id: str, step_id: str, 
                              loop_key: str = None, sink_id: str = None) -> str:
    """Generate idempotency key"""
    parts = [execution_id, step_id]
    
    if loop_key is not None:
        parts.append(str(loop_key))
    
    if sink_id is not None:
        parts.append(sink_id)
    
    return ":".join(parts)

# Worker-side usage in sink
def write_to_postgres(config: dict, data: dict, idempotency_key: str):
    """Write with idempotency"""
    query = f"""
        INSERT INTO {config['table']} (idempotency_key, data)
        VALUES (%(key)s, %(data)s)
        ON CONFLICT (idempotency_key) DO UPDATE SET data = EXCLUDED.data
    """
    db.execute(query, {"key": idempotency_key, "data": data})
```

---

### When to Retry

**HTTP:**
- Status codes: 408, 429, 5xx
- Network errors (connection timeout, DNS failure)

**Database:**
- Serialization failures
- Deadlocks
- Connection reset

**Python:**
- Explicit `RetryableError` raised by plugin

**Don't Retry:**
- 4xx (except 429) - Client errors
- Schema validation errors
- `FatalError` class
- **Action:** Mark `ok=false` immediately

---

### Implementation Target

```python
# File: noetl/worker/executor.py

class TaskExecutor:
    def __init__(self, retry_policy: RetryPolicy):
        self.retry_policy = retry_policy
    
    def execute_with_retry(self, task: Task) -> TaskResult:
        """Execute task with retry logic"""
        attempt = 0
        last_error = None
        
        while attempt < self.retry_policy.max_attempts:
            try:
                # Execute plugin
                result = self._execute_plugin(task)
                return TaskResult(ok=True, this=result)
            
            except Exception as e:
                last_error = e
                
                if not self.retry_policy.should_retry(attempt, e):
                    # Non-retryable error
                    logger.event("task_dlq", 
                        message_id=task.message_id,
                        attempt=attempt,
                        error_class=e.__class__.__name__,
                        error=str(e)
                    )
                    return TaskResult(ok=False, error=str(e))
                
                # Calculate backoff
                delay = self.retry_policy.calculate_delay(attempt)
                
                logger.event("task_retry",
                    message_id=task.message_id,
                    attempt=attempt + 1,
                    next_delay_ms=int(delay * 1000),
                    error_class=e.__class__.__name__
                )
                
                time.sleep(delay)
                attempt += 1
        
        # Max attempts exceeded
        logger.event("task_dlq",
            message_id=task.message_id,
            attempt=attempt,
            error="Max retry attempts exceeded",
            last_error=str(last_error)
        )
        return TaskResult(ok=False, error=str(last_error))
```

---

## 8.5 Timeouts & Cancellation

---

### Timeout Knobs

**Tool-level timeout:**
```yaml
tool:
  kind: http
  spec: { url: "..." }
  timeout_ms: 5000  # Optional, overrides default
```

**Sink-level timeout:**
```yaml
result:
  sink:
    - postgres:
        table: results
        timeout_ms: 3000  # Optional
```

**Loop timeouts:**
```yaml
loop:
  collection: "{{ items }}"
  element: item
  item_timeout_ms: 10000     # Per item
  total_timeout_ms: 300000   # Whole step budget
```

---

### Cancellation Flow

**Server:**
1. Marks `execution.status = canceled`
2. Stops dispatching new tasks
3. Sends cancel signal to in-flight tasks (best-effort)

**Worker:**
1. Receives cancel token per task
2. Plugin checks cancel token between operations
3. Sinks respect cancel by checking between batches

**Implementation:**

```python
# File: noetl/server/api/execution/cancellation.py

class ExecutionCanceller:
    def cancel(self, execution_id: str):
        """Cancel execution"""
        # Mark execution as canceled
        db.execute("""
            UPDATE execution
            SET status = 'canceled', finished_at = NOW()
            WHERE execution_id = %(id)s
        """, {"id": execution_id})
        
        # Signal workers (via cancel tokens or message)
        self._signal_workers(execution_id)
        
        logger.event("execution_canceled", execution_id=execution_id)
    
    def _signal_workers(self, execution_id: str):
        """Signal in-flight workers to cancel"""
        # Option 1: Update cancel tokens in DB
        db.execute("""
            UPDATE task_queue
            SET cancel_requested = true
            WHERE execution_id = %(id)s AND lease_expires_at > NOW()
        """, {"id": execution_id})
        
        # Option 2: Publish to cancel channel (Redis/Kafka)
        # pubsub.publish("cancel", execution_id)

# File: noetl/worker/cancellation.py

class CancelToken:
    def __init__(self, message_id: str):
        self.message_id = message_id
        self._canceled = False
    
    def check(self):
        """Check if task should be canceled"""
        if self._canceled:
            raise CancelError("Task canceled")
        
        # Query DB or cache for cancel status
        result = db.execute("""
            SELECT cancel_requested FROM task_queue
            WHERE message_id = %(id)s
        """, {"id": self.message_id})
        
        if result and result[0]["cancel_requested"]:
            self._canceled = True
            raise CancelError("Task canceled")

# Plugin usage
def execute_plugin(spec: dict, cancel_token: CancelToken):
    """Execute with cancel checks"""
    for batch in large_operation():
        cancel_token.check()  # Cooperative cancellation
        process_batch(batch)
```

---

### Heartbeat

**Worker heartbeats keep leases alive:**

```python
class TaskLeaseManager:
    def __init__(self, message_id: str, heartbeat_interval_ms: int = 10000):
        self.message_id = message_id
        self.heartbeat_interval = heartbeat_interval_ms / 1000.0
        self._stop = False
    
    def start_heartbeat(self):
        """Start heartbeat thread"""
        def heartbeat_loop():
            while not self._stop:
                self._heartbeat()
                time.sleep(self.heartbeat_interval)
        
        thread = threading.Thread(target=heartbeat_loop, daemon=True)
        thread.start()
    
    def _heartbeat(self):
        """Extend lease"""
        db.execute("""
            UPDATE task_queue
            SET lease_expires_at = NOW() + INTERVAL '5 minutes'
            WHERE message_id = %(id)s
        """, {"id": self.message_id})
    
    def stop(self):
        """Stop heartbeat"""
        self._stop = True
```

**Server reclaims expired leases:**

```python
class LeaseReclaimer:
    def reclaim_expired_leases(self):
        """Reclaim and retry expired tasks"""
        result = db.execute("""
            UPDATE task_queue
            SET lease_expires_at = NULL, worker_id = NULL
            WHERE lease_expires_at < NOW()
            RETURNING message_id, execution_id, step_id
        """)
        
        for row in result:
            logger.event("lease_reclaimed",
                message_id=row["message_id"],
                execution_id=row["execution_id"],
                step_id=row["step_id"]
            )
```

---

## 8.6 DLQ (Dead-Letter Queue)

---

### When to DLQ

1. **Max attempts exceeded** (plugin or sink)
2. **Non-retryable error class** (FatalError, schema validation)
3. **Poison message** (deserialize error)

---

### DLQ Payload

```python
@dataclass
class DLQEntry:
    message_id: str
    execution_id: str
    step_id: str
    loop_index: int | None
    loop_key: str | None
    tool_kind: str | None
    sink_id: str | None
    attempts: int
    last_error: str
    last_stack: str
    first_seen: datetime
    last_seen: datetime
    payload: dict  # Redacted
    context_excerpt: str  # Last 2KB
```

**Storage:**

```sql
CREATE TABLE dlq (
    message_id TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    loop_index INT,
    loop_key TEXT,
    tool_kind TEXT,
    sink_id TEXT,
    attempts INT NOT NULL,
    last_error TEXT,
    last_stack TEXT,
    first_seen TIMESTAMP NOT NULL,
    last_seen TIMESTAMP NOT NULL,
    payload JSONB,  -- Redacted
    context_excerpt TEXT,
    status TEXT DEFAULT 'pending'  -- pending|replayed|discarded
);

CREATE INDEX idx_dlq_execution ON dlq(execution_id);
CREATE INDEX idx_dlq_status ON dlq(status);
CREATE INDEX idx_dlq_tool_kind ON dlq(tool_kind);
```

---

### Handling DLQ

**CLI Commands:**

```bash
# List DLQ entries
clictl dlq list --status pending --limit 100

# Show single entry
clictl dlq show <message_id>

# Replay entry (re-enqueue)
clictl dlq replay <message_id> [--patch spec.url=https://new-url.com]

# Discard entry
clictl dlq discard <message_id> --reason "Invalid input data"
```

---

**Implementation:**

```python
# File: cli/clictl_dlq.py

@cli.group()
def dlq():
    """DLQ management"""
    pass

@dlq.command("list")
@click.option("--status", default="pending", help="Filter by status")
@click.option("--limit", default=100, help="Max entries")
def dlq_list(status, limit):
    """List DLQ entries"""
    result = db.execute("""
        SELECT message_id, execution_id, step_id, tool_kind, last_error, attempts
        FROM dlq
        WHERE status = %(status)s
        ORDER BY last_seen DESC
        LIMIT %(limit)s
    """, {"status": status, "limit": limit})
    
    for row in result:
        click.echo(f"{row['message_id']} | {row['tool_kind']} | {row['attempts']} attempts | {row['last_error'][:50]}")

@dlq.command("show")
@click.argument("message_id")
def dlq_show(message_id):
    """Show DLQ entry details"""
    result = db.execute("SELECT * FROM dlq WHERE message_id = %(id)s", {"id": message_id})
    if result:
        click.echo(json.dumps(dict(result[0]), indent=2, default=str))
    else:
        click.echo("Entry not found")

@dlq.command("replay")
@click.argument("message_id")
@click.option("--patch", multiple=True, help="Patch spec/args (key=value)")
def dlq_replay(message_id, patch):
    """Replay DLQ entry"""
    # Fetch entry
    entry = db.execute("SELECT * FROM dlq WHERE message_id = %(id)s", {"id": message_id})[0]
    
    # Apply patches
    payload = entry["payload"]
    for patch_expr in patch:
        key, value = patch_expr.split("=", 1)
        keys = key.split(".")
        target = payload
        for k in keys[:-1]:
            target = target[k]
        target[keys[-1]] = value
    
    # Re-enqueue
    db.execute("""
        INSERT INTO task_queue (message_id, execution_id, step_id, payload, attempt)
        VALUES (%(msg)s, %(exec)s, %(step)s, %(payload)s, 0)
    """, {
        "msg": f"{message_id}-replay",
        "exec": entry["execution_id"],
        "step": entry["step_id"],
        "payload": payload
    })
    
    # Mark replayed
    db.execute("UPDATE dlq SET status = 'replayed' WHERE message_id = %(id)s", {"id": message_id})
    
    click.echo(f"Replayed: {message_id}")

@dlq.command("discard")
@click.argument("message_id")
@click.option("--reason", required=True, help="Reason for discard")
def dlq_discard(message_id, reason):
    """Discard DLQ entry"""
    db.execute("""
        UPDATE dlq
        SET status = 'discarded', context_excerpt = %(reason)s
        WHERE message_id = %(id)s
    """, {"id": message_id, "reason": reason})
    
    click.echo(f"Discarded: {message_id}")
```

---

### Metrics

```prometheus
# Total DLQ entries
noetl_dlq_total{kind}

# Total DLQ entries by sink
noetl_dlq_total{sink}
```

---

## 8.7 Compensation & Rollback Patterns

---

### Pattern A — Explicit Compensating Steps

**Description:** For any side-effecting step, add corresponding `undo:<step_id>` tool.

**Example:**

```yaml
- step: reserve_slot
  tool:
    kind: postgres
    spec:
      query: "INSERT INTO slots (id, user_id) VALUES (%(id)s, %(user)s)"
    args:
      id: "{{ gen_uuid() }}"
      user: "{{ workload.user_id }}"
  result:
    as: slot
  next:
    - step: charge_card
    - when: "{{ fail('charge_card') }}"
      step: undo_reserve

- step: charge_card
  tool:
    kind: http
    spec:
      url: "https://payment-api.com/charge"
      method: POST
    args:
      amount: "{{ workload.amount }}"
      slot: "{{ slot.id }}"
  next:
    - step: confirm

- step: undo_reserve
  tool:
    kind: postgres
    spec:
      query: "DELETE FROM slots WHERE id = %(id)s"
    args:
      id: "{{ slot.id }}"
  next:
    - step: end

- step: confirm
  tool:
    kind: postgres
    spec:
      query: "UPDATE slots SET confirmed = true WHERE id = %(id)s"
    args:
      id: "{{ slot.id }}"
```

---

### Pattern B — SAGA (Backward Recovery)

**Description:** Top-level policy triggers automatic backward walk on failure.

**Configuration:**

```yaml
policy:
  rollback: on_fail  # Engine option

workflow:
  - step: reserve_slot
    tool: { ... }
    compensate: undo_reserve  # Reference to compensating step
  
  - step: charge_card
    tool: { ... }
    compensate: refund_card
```

**Implementation:**

```python
class SagaOrchestrator:
    def on_step_failed(self, execution_id: str, failed_step_id: str):
        """Trigger compensation on failure"""
        # Walk back taken path
        taken_steps = self._get_taken_steps(execution_id)
        
        for step_id in reversed(taken_steps):
            compensate_step = self._get_compensate_step(step_id)
            if compensate_step:
                self._dispatch(execution_id, compensate_step)
```

---

### Pattern C — Idempotent Upserts/Overwrites

**Description:** Prefer idempotent writes so reruns don't require compensation.

**Example:**

```yaml
tool:
  result:
    sink:
      - postgres:
          table: results
          mode: upsert  # Idempotent
          key: execution_id
          args:
            execution_id: "{{ execution_id }}"
            status: ok
```

**Benefits:**
- No compensation needed
- Safe to retry
- Simplifies error handling

---

### Pattern D — Outbox

**Description:** For cross-system effects (Kafka + Postgres), use outbox table.

**Example:**

```yaml
- step: process_order
  tool:
    kind: python
    spec: { code: "..." }
  result:
    sink:
      - postgres:
          table: orders
          mode: insert
      - postgres:
          table: outbox  # Transactional outbox
          mode: insert
          args:
            topic: order_events
            payload: "{{ this }}"
```

**Separate Worker:**
- Polls `outbox` table
- Publishes to Kafka
- Marks as delivered
- Enables guaranteed delivery or compensable retries

---

## 8.8 Failure Classification & Policies

---

### Error Classes

```python
# File: noetl/worker/errors.py

class RetryableError(Exception):
    """Transient error (network, 5xx)"""
    pass

class FatalError(Exception):
    """Non-retryable error (validation, 4xx except 429)"""
    pass

class SinkError(Exception):
    """Sink write failed"""
    pass

class CancelError(Exception):
    """User canceled execution"""
    pass

class TimeoutError(Exception):
    """Exceeded timeout budget"""
    pass
```

---

### Policies (Server Config)

```yaml
policies:
  on_step_fail: halt  # Options: continue|halt|route_edge:<label>
  on_sink_fail: retry  # Options: retry|max_attempts→fail_step|async_ignore
  on_when_error: treat_as_false  # Options: treat_as_false|fail_step
```

**`on_step_fail`:**
- `continue` - Mark step as failed, continue routing
- `halt` (default) - Stop execution, mark `execution.status=fail`
- `route_edge:<label>` - Route to specific error handler step

**`on_sink_fail`:**
- `retry` (default) - Retry with backoff, fail step if max attempts
- `max_attempts→fail_step` - Fail step after max retries
- `async_ignore` - Log error, don't fail step (best-effort)

**`on_when_error`:**
- `treat_as_false` (default) - Park step, don't fail
- `fail_step` - Treat evaluation error as step failure

---

### Implementation

```python
# File: noetl/server/api/execution/policies.py

class PolicyEngine:
    def __init__(self, config: dict):
        self.on_step_fail = config.get("on_step_fail", "halt")
        self.on_sink_fail = config.get("on_sink_fail", "retry")
        self.on_when_error = config.get("on_when_error", "treat_as_false")
    
    def handle_step_failure(self, exec_state, step_id: str):
        """Handle step failure per policy"""
        if self.on_step_fail == "halt":
            self._halt_execution(exec_state)
        
        elif self.on_step_fail == "continue":
            self._mark_step_failed(exec_state, step_id)
            self._route_next(exec_state, step_id)
        
        elif self.on_step_fail.startswith("route_edge:"):
            label = self.on_step_fail.split(":", 1)[1]
            self._route_to_label(exec_state, step_id, label)
    
    def handle_when_error(self, exec_state, step_id: str, error: Exception):
        """Handle when evaluation error"""
        if self.on_when_error == "treat_as_false":
            logger.event("when_eval_error", 
                step_id=step_id, 
                error=str(error),
                action="park"
            )
            self._park_step(exec_state, step_id)
        
        elif self.on_when_error == "fail_step":
            logger.event("when_eval_error",
                step_id=step_id,
                error=str(error),
                action="fail"
            )
            self._mark_step_failed(exec_state, step_id)
```

---

## 8.9 Redaction & PII Safety

---

### Redaction Rules

**Redact known keys in logs/traces:**
- `password`
- `token`
- `authorization`
- `secret`
- `key`
- `auth`
- `api_key`
- `bearer`

---

### Implementation

```python
# File: noetl/observability/redaction.py

import re

REDACT_KEYS = {
    "password", "token", "authorization", "secret", 
    "key", "auth", "api_key", "bearer", "credential"
}

def redact_dict(data: dict) -> dict:
    """Recursively redact sensitive keys"""
    redacted = {}
    for k, v in data.items():
        if k.lower() in REDACT_KEYS:
            redacted[k] = "***REDACTED***"
        elif isinstance(v, dict):
            redacted[k] = redact_dict(v)
        elif isinstance(v, list):
            redacted[k] = [redact_dict(item) if isinstance(item, dict) else item for item in v]
        else:
            redacted[k] = v
    return redacted

def signature_of(data: dict) -> str:
    """Generate shape summary (no values)"""
    def shape(obj):
        if isinstance(obj, dict):
            return {k: shape(v) for k in obj.keys()}
        elif isinstance(obj, list):
            return [shape(obj[0])] if obj else []
        else:
            return type(obj).__name__
    
    return str(shape(data))

# Usage in tracing
span.set_attribute("spec_signature", signature_of(spec))
span.set_attribute("args_signature", signature_of(args))
```

---

### API Masking

```python
# File: noetl/server/api/execution/responses.py

class ExecutionResponse:
    @staticmethod
    def mask_context(context: dict) -> dict:
        """Mask secrets in context for API response"""
        masked = context.copy()
        
        # Mask secrets namespace
        if "secrets" in masked:
            masked["secrets"] = {k: "***MASKED***" for k in masked["secrets"].keys()}
        
        # Redact sensitive keys
        masked = redact_dict(masked)
        
        return masked
```

---

### Sink Safety

**Don't log raw payloads; log checksums or counts:**

```python
def log_sink_write(sink_id: str, data: dict):
    """Log sink write without exposing data"""
    import hashlib
    checksum = hashlib.sha256(json.dumps(data).encode()).hexdigest()[:16]
    
    logger.event("sink_write",
        sink_id=sink_id,
        checksum=checksum,
        size_bytes=len(json.dumps(data))
    )
```

---

## 8.10 Dashboards (Starter Panels)

---

### Execution Overview

**Executions Started/Completed (Stacked by Status)**
```promql
rate(noetl_executions_completed_total[5m]) by (status)
```

**In-Flight Executions by Age**
```promql
count(noetl_executions_started_total - noetl_executions_completed_total) by (workflow)
```

**Step Duration Heatmap (by step_id)**
```promql
histogram_quantile(0.95, rate(noetl_step_duration_seconds_bucket[5m])) by (step)
```

**Top Failing Steps (Count, Last 24h)**
```promql
topk(10, increase(noetl_step_runs_total{ok="false"}[24h]))
```

---

### Worker Health

**Tasks Started/Completed per Pool**
```promql
rate(noetl_worker_tasks_completed_total[5m]) by (pool, ok)
```

**Running Tasks by Kind**
```promql
noetl_worker_tasks_started_total - noetl_worker_tasks_completed_total by (kind)
```

**Average Task Duration by Kind**
```promql
rate(noetl_worker_task_duration_seconds_sum[5m]) / rate(noetl_worker_task_duration_seconds_count[5m]) by (kind)
```

**DLQ Inflow Rate & Size**
```promql
rate(noetl_dlq_total[5m])
count(dlq_entries{status="pending"})
```

---

### Sinks

**Sink Duration and Error Rate by sink_id**
```promql
rate(noetl_sink_tasks_completed_total{ok="false"}[5m]) by (sink)
histogram_quantile(0.95, rate(noetl_sink_duration_seconds_bucket[5m])) by (sink)
```

**Upsert vs Insert Ratios** (if measured)
```promql
rate(noetl_sink_mode_total{mode="upsert"}[5m]) / rate(noetl_sink_mode_total[5m])
```

**Retries per Sink**
```promql
rate(noetl_sink_retry_total[5m]) by (sink)
```

---

### Guards

**When Outcome Distribution**
```promql
rate(noetl_when_eval_total[5m]) by (outcome)
```

**Parked Steps Over Time**
```promql
count(parked_steps_gauge) by (workflow)
```

---

## 8.11 Alerting (Sane Defaults)

---

### Alert Rules

**High DLQ Growth**
```yaml
alert: HighDLQGrowth
expr: rate(noetl_dlq_total[5m]) > 10
for: 5m
annotations:
  summary: "DLQ growing rapidly"
  description: "DLQ receiving {{ $value }} entries/sec"
```

---

**Step Failure Rate**
```yaml
alert: StepFailureRateHigh
expr: |
  rate(noetl_step_runs_total{ok="false"}[10m]) 
  / rate(noetl_step_runs_total[10m]) > 0.1
for: 10m
annotations:
  summary: "Step {{ $labels.step }} failing frequently"
  description: "Failure rate: {{ $value | humanizePercentage }}"
```

---

**Worker Stalled**
```yaml
alert: WorkerStalled
expr: |
  time() - max(noetl_worker_heartbeat_timestamp) by (worker_id) > 60
for: 1m
annotations:
  summary: "Worker {{ $labels.worker_id }} stalled"
  description: "No heartbeat for >1 minute"
```

---

**Sink Error Rate**
```yaml
alert: SinkErrorRateHigh
expr: |
  rate(noetl_sink_tasks_completed_total{ok="false"}[10m])
  / rate(noetl_sink_tasks_completed_total[10m]) > 0.05
for: 10m
annotations:
  summary: "Sink {{ $labels.sink }} error rate high"
  description: "Error rate: {{ $value | humanizePercentage }}"
```

---

**Execution Exceeding SLA**
```yaml
alert: ExecutionSLAExceeded
expr: |
  histogram_quantile(0.95, rate(noetl_step_duration_seconds_bucket[10m])) 
  > 300  # 5 minutes P95 + margin
for: 5m
annotations:
  summary: "Execution SLA exceeded"
  description: "P95 duration: {{ $value }}s"
```

---

### Alert Payload Requirements

**Must include:**
- `execution_id`
- `workflow_ref`
- `step_id`
- Last error class
- Link to `/api/executions/{id}`

**Example payload:**
```json
{
  "alert": "StepFailureRateHigh",
  "execution_id": "484377543601029219",
  "workflow_ref": "playbooks/user_processor",
  "step_id": "fetch_user",
  "error_class": "RetryableError",
  "error_rate": 0.15,
  "link": "https://noetl.example.com/api/executions/484377543601029219"
}
```

---

## 8.12 Config Knobs (YAML/Env)

```yaml
# File: config/noetl.yaml

orchestrator:
  evaluate_when_timeout_ms: 100
  route_after_all_sinks: true  # Wait for all sinks before routing
  render_args_server_side: true  # Server renders args before dispatch

retries:
  plugin:
    max_attempts: 6
    base_ms: 200
    max_ms: 30000
  sink:
    max_attempts: 8
    base_ms: 200
    max_ms: 60000

timeouts:
  tool_default_ms: 30000  # 30 seconds
  sink_default_ms: 30000
  loop_item_ms: 30000

dlq:
  enabled: true
  topic: "noetl-dlq"
  retention_days: 30

tracing:
  enabled: true
  sample_rate: 0.1  # 10%
  force_sample_on_error: true
  exporter: "otlp"
  endpoint: "http://jaeger:4318"

metrics:
  enabled: true
  port: 9090
  path: "/metrics"

logging:
  level: "INFO"
  format: "json"
  redact_keys:
    - password
    - token
    - authorization
    - secret
    - key
    - auth

policies:
  on_step_fail: halt  # halt|continue|route_edge:<label>
  on_sink_fail: retry  # retry|max_attempts→fail_step|async_ignore
  on_when_error: treat_as_false  # treat_as_false|fail_step
```

**Environment variables:**

```bash
# Orchestrator
NOETL_ORCHESTRATOR_EVALUATE_WHEN_TIMEOUT_MS=100
NOETL_ORCHESTRATOR_ROUTE_AFTER_ALL_SINKS=true

# Retries
NOETL_RETRIES_PLUGIN_MAX_ATTEMPTS=6
NOETL_RETRIES_PLUGIN_BASE_MS=200
NOETL_RETRIES_PLUGIN_MAX_MS=30000

# Timeouts
NOETL_TIMEOUTS_TOOL_DEFAULT_MS=30000
NOETL_TIMEOUTS_SINK_DEFAULT_MS=30000

# DLQ
NOETL_DLQ_ENABLED=true
NOETL_DLQ_TOPIC=noetl-dlq

# Tracing
NOETL_TRACING_ENABLED=true
NOETL_TRACING_SAMPLE_RATE=0.1
NOETL_TRACING_EXPORTER=otlp
NOETL_TRACING_ENDPOINT=http://jaeger:4318

# Metrics
NOETL_METRICS_ENABLED=true
NOETL_METRICS_PORT=9090

# Logging
NOETL_LOGGING_LEVEL=INFO
NOETL_LOGGING_FORMAT=json

# Policies
NOETL_POLICIES_ON_STEP_FAIL=halt
NOETL_POLICIES_ON_SINK_FAIL=retry
NOETL_POLICIES_ON_WHEN_ERROR=treat_as_false
```

---

## 8.13 Operational Runbooks (Short)

---

### A) Spike in DLQ

**Symptoms:**
- Alert: `HighDLQGrowth`
- Dashboard shows DLQ inflow rate spiking

**Actions:**

1. **Check dashboards**: Which kind/sink failing?
   ```bash
   # Query Prometheus
   topk(10, rate(noetl_dlq_total[5m])) by (kind, sink)
   ```

2. **Inspect sample DLQ entry**
   ```bash
   clictl dlq list --status pending --limit 10
   clictl dlq show <message_id>
   ```

3. **If transient (5xx, network errors):**
   - Raise retries/backoff temporarily
   - Replay messages
   ```bash
   # Temporarily increase retries (config change + restart)
   NOETL_RETRIES_PLUGIN_MAX_ATTEMPTS=10
   
   # Replay DLQ entries
   clictl dlq replay <message_id>
   ```

4. **If schema/4xx errors:**
   - Patch workflow or add guard
   - Replay specific messages with patch
   ```bash
   clictl dlq replay <message_id> --patch spec.url=https://new-url.com
   ```

5. **If poison message:**
   - Discard after root cause documented
   ```bash
   clictl dlq discard <message_id> --reason "Invalid payload format"
   ```

---

### B) Stuck Execution (Parked Step)

**Symptoms:**
- Execution shows `status=running` for long time
- Dashboard shows parked steps count increasing

**Actions:**

1. **View execution state**
   ```bash
   clictl exec status --id <execution_id>
   # Or via API
   curl http://noetl-server:8083/api/executions/<execution_id>
   ```

2. **Check step statuses**
   - Look for steps with `done=false`, `running=false` (parked)
   - Check `when` expression and predecessor statuses

3. **If logic issue:**
   - Patch workflow and re-run
   - Or manually mark step as done (admin API)
   ```bash
   curl -X POST http://noetl-server:8083/api/admin/executions/<execution_id>/steps/<step_id>/force-complete
   ```

4. **Document issue and fix workflow**

---

### C) Runaway Parallelism

**Symptoms:**
- Worker pool saturated
- Task queue inflight count very high
- System resources (CPU, memory) maxed out

**Actions:**

1. **Throttle worker concurrency**
   ```bash
   # Reduce worker concurrency (requires worker restart)
   NOETL_WORKER_CONCURRENCY=4
   
   # Or drain some workers
   clictl worker drain --pool default
   ```

2. **Set loop mode to sequential**
   ```yaml
   loop:
     collection: "{{ items }}"
     element: item
     mode: sequential  # Changed from parallel
   ```

3. **Add loop concurrency limit** (future feature)
   ```yaml
   loop:
     collection: "{{ items }}"
     element: item
     mode: parallel
     max_concurrency: 10  # Cap parallel tasks
   ```

4. **Enable queue priorities for critical steps**
   ```yaml
   tool:
     priority: 10  # Higher priority
   ```

---

## 8.14 Acceptance Criteria (Observability & Resilience)

**Metrics:**
- [ ] Metrics exposed and scraped via `/metrics` endpoint
- [ ] Basic dashboards live (execution overview, worker health, sinks, guards)
- [ ] All server and worker metrics implemented

**Tracing:**
- [ ] Traces visible end-to-end for sampled runs
- [ ] OpenTelemetry integration working
- [ ] Trace context propagated across server → worker → HTTP plugin
- [ ] Sampling rates configurable

**Retries:**
- [ ] Retries with jitter working for plugin and sink failures
- [ ] DLQ receives terminal failures
- [ ] Max attempts configurable
- [ ] Backoff exponential with jitter

**Timeouts:**
- [ ] Timeouts honored at tool, sink, and loop levels
- [ ] Cancellations propagate to workers
- [ ] Heartbeats keep leases alive
- [ ] Expired leases reclaimed by server

**Sinks:**
- [ ] Sinks retried on failure
- [ ] Idempotent writes (UPSERT) working
- [ ] Fan-out doesn't duplicate results
- [ ] Sink failures reported correctly

**Redaction:**
- [ ] Redaction rules verified (no secrets in logs/traces)
- [ ] API responses mask secrets
- [ ] Trace signatures used instead of full payloads

**Runbooks:**
- [ ] Runbooks documented for common issues
- [ ] CLI commands tested (DLQ list/show/replay/discard)
- [ ] Admin APIs working (force-complete, cancel)

**Alerting:**
- [ ] Alert rules configured in Prometheus/Alertmanager
- [ ] Alert payloads include required fields (execution_id, workflow_ref, step_id, error_class, link)
- [ ] Alerts tested with simulated failures

**Config:**
- [ ] Config knobs documented
- [ ] Environment variables working
- [ ] Default values sane
- [ ] Config validation on startup

---

## Next Steps

This document provides the **complete observability and resilience strategy** for DSL v2. Recommended actions:

1. **Implement metrics** (Prometheus client libraries in server/worker)
2. **Set up structured logging** (JSON formatter with context adapters)
3. **Integrate OpenTelemetry** (server and worker instrumentation)
4. **Build retry/DLQ** infrastructure (worker-side retry logic, DLQ table, CLI commands)
5. **Configure timeouts** and cancellation (cancel tokens, heartbeats, lease reclaim)
6. **Create dashboards** (Grafana panels for metrics)
7. **Define alerts** (Prometheus rules with sane thresholds)
8. **Write runbooks** (operational procedures for common issues)
9. **Test acceptance criteria** (end-to-end validation)

---

**Ready for observability implementation kickoff.**
