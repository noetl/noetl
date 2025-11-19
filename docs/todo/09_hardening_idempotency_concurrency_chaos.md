# Hardening: Idempotency, Exactly-Once, Concurrency, Chaos, Backpressure, Canary

**Status:** Planning  
**Date:** November 6, 2025  
**Objective:** Define complete hardening strategy for production-grade DSL v2 runtime with exactly-once guarantees, concurrency controls, and chaos resilience

---

## 9.1 Idempotency Keys (Tasks & Sinks)

---

### Task Key (Per Unit of Work)

**Format:**
```python
task_key = f"{execution_id}:{step_id}:{loop_key or loop_index or '_'}"
```

**Examples:**
- Non-loop: `484377543601029219:fetch_user:_`
- Loop by index: `484377543601029219:process_users:0`
- Loop by key: `484377543601029219:process_users:user_123`

---

**Storage:**

Add `task_key` column to `task_queue`:

```sql
ALTER TABLE task_queue ADD COLUMN task_key TEXT NOT NULL;
CREATE INDEX idx_task_queue_task_key ON task_queue(task_key);
```

---

**Worker Deduplication:**

Worker must tolerate duplicate deliveries (at-least-once queues).

**Keep short-lived dedupe cache:**
- LRU cache
- TTL: ~10 minutes
- Keyed by `task_key`

---

### Sink Key (Per Side-Effect)

**Format:**
```python
sink_key = f"{task_key}:{sink_id}"
```

**Example:**
```
484377543601029219:process_users:user_123:postgres:results
```

---

**Usage:**

Pass to sink plugins; use as:
- **UPSERT key** (Postgres, DuckDB)
- **Object name suffix** (S3, GCS)
- **Message key** (Kafka)
- **Idempotency-Key header** (HTTP)

---

**Object Store Strategy:**

Put metadata header:
```
x-noetl-idempotency-key: {sink_key}
```

Write with:
- **PUT with if-none-match** (create-only)
- **Overwrite with same ETag** (idempotent)

---

**Kafka Strategy:**

Use `sink_key` as message key:
- Dedupe at consumer
- Or use compacted topic (last write wins)

---

### Implementation Target

```python
# File: noetl/server/api/execution/idempotency.py

class IdempotencyKeyGenerator:
    @staticmethod
    def task_key(execution_id: str, step_id: str, 
                 loop_key: str = None, loop_index: int = None) -> str:
        """Generate task idempotency key"""
        suffix = loop_key or (str(loop_index) if loop_index is not None else '_')
        return f"{execution_id}:{step_id}:{suffix}"
    
    @staticmethod
    def sink_key(task_key: str, sink_id: str) -> str:
        """Generate sink idempotency key"""
        return f"{task_key}:{sink_id}"

# Usage in dispatcher
task_key = IdempotencyKeyGenerator.task_key(
    execution_id=exec_id,
    step_id=step_id,
    loop_index=0
)

sink_key = IdempotencyKeyGenerator.sink_key(
    task_key=task_key,
    sink_id="postgres:results"
)
```

---

## 9.2 Exactly-Once Write Patterns (Per Sink)

---

### Postgres — Use Upsert Ledger

**Ledger Table:**

```sql
CREATE TABLE IF NOT EXISTS noetl_sink_ledger (
    sink_key TEXT PRIMARY KEY,
    execution_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sink_ledger_execution ON noetl_sink_ledger(execution_id);
CREATE INDEX idx_sink_ledger_step ON noetl_sink_ledger(execution_id, step_id);
```

---

**Transaction Pattern:**

```python
# File: noetl/worker/sinks/postgres.py

def write_exactly_once(conn, table: str, data: dict, sink_key: str, 
                       execution_id: str, step_id: str):
    """Write with exactly-once guarantee"""
    with conn.transaction():
        # 1. Upsert business row
        columns = ", ".join(data.keys())
        values = ", ".join([f"${i+1}" for i in range(len(data))])
        update_cols = ", ".join([f"{k} = EXCLUDED.{k}" for k in data.keys()])
        
        query = f"""
            INSERT INTO {table} ({columns})
            VALUES ({values})
            ON CONFLICT (id) DO UPDATE SET {update_cols}
        """
        conn.execute(query, *data.values())
        
        # 2. Insert ledger entry (idempotence gate)
        ledger_query = """
            INSERT INTO noetl_sink_ledger (sink_key, execution_id, step_id)
            VALUES ($1, $2, $3)
            ON CONFLICT (sink_key) DO NOTHING
        """
        result = conn.execute(ledger_query, sink_key, execution_id, step_id)
        
        # If ledger insert conflicts, treat as already-done
        if result.rowcount == 0:
            logger.info("Sink already completed (ledger conflict)", 
                       sink_key=sink_key)
            return {"status": "already_done"}
        
        return {"status": "written"}
```

---

### DuckDB — Emulate with DELETE + INSERT

**Strategy:**

Single connection session (DuckDB doesn't have full txn isolation):

```python
def write_exactly_once_duckdb(conn, table: str, data: dict, sink_key: str):
    """Emulate exactly-once in DuckDB"""
    # 1. Check ledger (shadow table)
    ledger_table = "noetl_sink_ledger"
    check = conn.execute(
        f"SELECT 1 FROM {ledger_table} WHERE sink_key = ?",
        [sink_key]
    ).fetchone()
    
    if check:
        logger.info("Sink already completed (ledger)", sink_key=sink_key)
        return {"status": "already_done"}
    
    # 2. Delete existing (if any)
    conn.execute(f"DELETE FROM {table} WHERE id = ?", [data["id"]])
    
    # 3. Insert new
    columns = ", ".join(data.keys())
    placeholders = ", ".join(["?" for _ in data])
    conn.execute(
        f"INSERT INTO {table} ({columns}) VALUES ({placeholders})",
        list(data.values())
    )
    
    # 4. Record in ledger
    conn.execute(
        f"INSERT INTO {ledger_table} (sink_key, execution_id, step_id, at) VALUES (?, ?, ?, NOW())",
        [sink_key, execution_id, step_id]
    )
    
    return {"status": "written"}
```

---

### S3/GCS — Object Naming Strategy

**Path Determinism:**

```
s3://bucket/noetl/{execution_id}/{step_id}/{loop_key}/{sink_id}.json
```

**Idempotence:**
- Deterministic path = overwrite-safe
- Re-writes are idempotent (last write wins)

**Optional Ledger:**

Add sidecar ledger in Postgres for exactly-once guarantees beyond overwrite:

```python
def write_to_s3_exactly_once(s3_client, bucket: str, key: str, data: bytes,
                              sink_key: str, pg_conn):
    """Write to S3 with Postgres ledger"""
    # 1. Check ledger
    ledger_check = pg_conn.execute(
        "SELECT 1 FROM noetl_sink_ledger WHERE sink_key = $1",
        [sink_key]
    ).fetchone()
    
    if ledger_check:
        logger.info("S3 write already done (ledger)", sink_key=sink_key)
        return {"status": "already_done"}
    
    # 2. Write to S3 with metadata
    s3_client.put_object(
        Bucket=bucket,
        Key=key,
        Body=data,
        Metadata={
            "x-noetl-idempotency-key": sink_key
        }
    )
    
    # 3. Record in ledger
    pg_conn.execute(
        """
        INSERT INTO noetl_sink_ledger (sink_key, execution_id, step_id)
        VALUES ($1, $2, $3)
        ON CONFLICT (sink_key) DO NOTHING
        """,
        [sink_key, execution_id, step_id]
    )
    
    return {"status": "written"}
```

---

### HTTP — Idempotency-Key Header

**Strategy:**

Only call idempotent endpoints (PUT/DELETE) or supply `Idempotency-Key` header.

```python
def call_http_idempotent(url: str, method: str, data: dict, sink_key: str):
    """HTTP call with idempotency key"""
    headers = {
        "Idempotency-Key": sink_key,
        "Content-Type": "application/json"
    }
    
    response = requests.request(
        method=method,
        url=url,
        json=data,
        headers=headers
    )
    
    # 409 Conflict = already processed
    if response.status_code == 409:
        logger.info("HTTP request already processed", sink_key=sink_key)
        return {"status": "already_done"}
    
    response.raise_for_status()
    return {"status": "written", "response": response.json()}
```

**Fallback:**

If endpoint doesn't support `Idempotency-Key`, wrap via your server with outbox table:

```python
# Server-side outbox
def enqueue_http_via_outbox(sink_key: str, url: str, data: dict):
    """Wrap HTTP in outbox pattern"""
    db.execute("""
        INSERT INTO http_outbox (sink_key, url, payload, status)
        VALUES ($1, $2, $3, 'pending')
        ON CONFLICT (sink_key) DO NOTHING
    """, [sink_key, url, json.dumps(data)])
    
    # Separate worker polls outbox and delivers
```

---

### Kafka — Idempotent Producer + Compacted Topics

**Strategy 1: Message Key**

```python
def write_to_kafka(producer, topic: str, data: dict, sink_key: str):
    """Write with sink_key as message key"""
    producer.send(
        topic=topic,
        key=sink_key.encode('utf-8'),  # Dedupe key
        value=json.dumps(data).encode('utf-8')
    )
    producer.flush()
```

**Consumer must be idempotent** or use compacted topic (last value per key).

---

**Strategy 2: Idempotent Producer**

```python
# Enable idempotent producer (Kafka 0.11+)
producer = KafkaProducer(
    bootstrap_servers=['localhost:9092'],
    enable_idempotence=True,
    acks='all',
    retries=5
)
```

---

## 9.3 Concurrency Controls

---

### Server-Side

**Loop Budget (Concurrency Cap):**

```yaml
loop:
  collection: "{{ items }}"
  element: item
  mode: parallel
  concurrency: 10  # NEW: Cap in-flight items
```

**Implementation:**

```python
# File: noetl/server/api/execution/loop_dispatcher.py

class ConcurrencyThrottle:
    def __init__(self, max_concurrency: int):
        self.max_concurrency = max_concurrency
        self.in_flight = 0
        self.pending_items = []
    
    def can_dispatch(self) -> bool:
        """Check if can dispatch more items"""
        return self.in_flight < self.max_concurrency
    
    def dispatch(self, item):
        """Dispatch item and increment counter"""
        self.in_flight += 1
        self._enqueue_task(item)
    
    def on_complete(self):
        """Decrement counter and dispatch next pending"""
        self.in_flight -= 1
        if self.pending_items and self.can_dispatch():
            next_item = self.pending_items.pop(0)
            self.dispatch(next_item)

# Usage in loop dispatcher
throttle = ConcurrencyThrottle(max_concurrency=loop_config.get("concurrency", float('inf')))

for item in items:
    if throttle.can_dispatch():
        throttle.dispatch(item)
    else:
        throttle.pending_items.append(item)
```

---

**Per-Step Rate Limit:**

```yaml
- step: api_call
  tool:
    kind: http
    spec: { url: "..." }
  rate_per_sec: 10.0  # Token bucket rate limit
```

**Implementation:**

```python
# File: noetl/server/api/execution/rate_limiter.py

import time
from threading import Lock

class TokenBucket:
    def __init__(self, rate: float, capacity: float = None):
        self.rate = rate
        self.capacity = capacity or rate
        self.tokens = self.capacity
        self.last_refill = time.time()
        self.lock = Lock()
    
    def acquire(self, tokens: int = 1) -> bool:
        """Try to acquire tokens; blocks if needed"""
        with self.lock:
            now = time.time()
            elapsed = now - self.last_refill
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last_refill = now
            
            if self.tokens >= tokens:
                self.tokens -= tokens
                return True
            
            # Wait for refill
            wait_time = (tokens - self.tokens) / self.rate
            time.sleep(wait_time)
            self.tokens = 0
            return True

# Usage
rate_limiter = TokenBucket(rate=10.0)  # 10 req/sec
rate_limiter.acquire(1)  # Blocks if needed
dispatch_task()
```

---

**Per-Plugin Pool Limits:**

```yaml
limits:
  per_kind_caps:
    http: 64
    postgres: 16
    python: 8
    duckdb: 4
```

**Implementation:**

Track in-flight tasks per kind globally:

```python
# File: noetl/server/api/execution/pool_limits.py

class PluginPoolLimiter:
    def __init__(self, caps: dict[str, int]):
        self.caps = caps
        self.in_flight = {kind: 0 for kind in caps}
        self.lock = Lock()
    
    def can_dispatch(self, kind: str) -> bool:
        """Check if can dispatch task of kind"""
        with self.lock:
            return self.in_flight.get(kind, 0) < self.caps.get(kind, float('inf'))
    
    def dispatch(self, kind: str):
        """Increment counter"""
        with self.lock:
            self.in_flight[kind] = self.in_flight.get(kind, 0) + 1
    
    def complete(self, kind: str):
        """Decrement counter"""
        with self.lock:
            self.in_flight[kind] -= 1
```

---

### Worker-Side

**Pool-Wide Concurrency:**

```bash
clictl worker start --concurrency 8 --cap http=64,postgres=16,python=8,duckdb=4
```

**Implementation:**

```python
# File: noetl/worker/pool.py

class WorkerPool:
    def __init__(self, concurrency: int, per_kind_caps: dict[str, int] = None):
        self.concurrency = concurrency
        self.per_kind_caps = per_kind_caps or {}
        self.in_flight = {kind: 0 for kind in self.per_kind_caps}
        self.executor = ThreadPoolExecutor(max_workers=concurrency)
    
    def can_execute(self, kind: str) -> bool:
        """Check if can execute task of kind"""
        cap = self.per_kind_caps.get(kind, self.concurrency)
        return self.in_flight.get(kind, 0) < cap
    
    def submit(self, task: Task):
        """Submit task if capacity available"""
        if self.can_execute(task.kind):
            self.in_flight[task.kind] = self.in_flight.get(task.kind, 0) + 1
            future = self.executor.submit(self._execute_task, task)
            future.add_done_callback(lambda f: self._on_complete(task.kind))
        else:
            # Requeue or wait
            logger.info("Worker at capacity", kind=task.kind)
    
    def _on_complete(self, kind: str):
        """Decrement counter"""
        self.in_flight[kind] -= 1
```

---

**Fairness (Weighted Fair Queue):**

Rotate kinds to avoid starvation:

```python
class FairQueue:
    def __init__(self):
        self.queues = {}  # kind -> deque
        self.round_robin_idx = 0
    
    def enqueue(self, kind: str, task: Task):
        """Add task to kind queue"""
        if kind not in self.queues:
            self.queues[kind] = deque()
        self.queues[kind].append(task)
    
    def dequeue(self) -> Task | None:
        """Dequeue next task (fair rotation)"""
        kinds = list(self.queues.keys())
        if not kinds:
            return None
        
        # Round-robin
        for _ in range(len(kinds)):
            idx = self.round_robin_idx % len(kinds)
            kind = kinds[idx]
            self.round_robin_idx += 1
            
            if self.queues[kind]:
                return self.queues[kind].popleft()
        
        return None
```

---

### Backpressure Signals

**Task Queue Depth Thresholds:**

```yaml
backpressure:
  wm_hi_queue_depth: 20000  # High watermark
  wm_lo_queue_depth: 5000   # Low watermark
```

**Implementation:**

```python
class BackpressureController:
    def __init__(self, wm_hi: int, wm_lo: int):
        self.wm_hi = wm_hi
        self.wm_lo = wm_lo
        self.throttled = False
    
    def check_depth(self, current_depth: int):
        """Check queue depth and adjust throttle"""
        if current_depth > self.wm_hi and not self.throttled:
            logger.warning("Backpressure activated", depth=current_depth)
            self.throttled = True
        elif current_depth < self.wm_lo and self.throttled:
            logger.info("Backpressure released", depth=current_depth)
            self.throttled = False
    
    def should_dispatch(self) -> bool:
        """Check if should dispatch new tasks"""
        return not self.throttled
```

---

**Worker Busy Gauge:**

Server reduces enqueue rate based on worker utilization:

```python
worker_busy_ratio = metrics["noetl_worker_tasks_running"] / metrics["noetl_worker_capacity"]

if worker_busy_ratio > 0.9:
    # Linear backoff
    dispatch_delay = 100 * (worker_busy_ratio - 0.9) / 0.1  # 0-100ms
    time.sleep(dispatch_delay / 1000)
```

---

**Sinks Taking Too Long:**

Prefer server routes only after all sinks complete:

```yaml
orchestrator:
  route_after_all_sinks: true  # Wait for sinks before routing
```

---

## 9.4 Chaos & Failure Injection (Plan)

---

### Fault Classes to Inject

1. **Queue delays / visibility timeouts**
2. **Worker crash mid-task**
3. **Plugin transient errors** (HTTP 5xx, DB serialization failures)
4. **Plugin fatal errors** (HTTP 4xx other than 429)
5. **Sink timeouts and partial failures**
6. **Slow when evaluation** (simulate context lock)

---

### How to Inject

**Feature-Flaggable Fault Injector in Worker:**

```bash
NOETL_FAULTS="http:0.05:5xx,postgres:0.02:deadlock,sink:0.03:timeout"
```

**Implementation:**

```python
# File: noetl/worker/chaos.py

import random
import os

class FaultInjector:
    def __init__(self):
        self.faults = self._parse_faults(os.getenv("NOETL_FAULTS", ""))
    
    def _parse_faults(self, spec: str) -> dict:
        """Parse fault spec: kind:probability:error_type"""
        faults = {}
        if not spec:
            return faults
        
        for entry in spec.split(","):
            parts = entry.split(":")
            if len(parts) == 3:
                kind, prob, error_type = parts
                faults[kind] = (float(prob), error_type)
        
        return faults
    
    def should_inject(self, kind: str) -> tuple[bool, str | None]:
        """Check if should inject fault"""
        if kind not in self.faults:
            return False, None
        
        prob, error_type = self.faults[kind]
        if random.random() < prob:
            return True, error_type
        
        return False, None
    
    def inject(self, kind: str):
        """Inject fault if configured"""
        should_inject, error_type = self.should_inject(kind)
        
        if should_inject:
            logger.warning("Injecting chaos fault", kind=kind, error_type=error_type)
            
            if error_type == "5xx":
                raise RetryableError(f"Chaos: HTTP 500")
            elif error_type == "4xx":
                raise FatalError(f"Chaos: HTTP 400")
            elif error_type == "deadlock":
                raise RetryableError(f"Chaos: DB deadlock")
            elif error_type == "timeout":
                raise TimeoutError(f"Chaos: Timeout")
            elif error_type == "crash":
                os._exit(1)  # Simulate crash

# Usage in worker
fault_injector = FaultInjector()

def execute_plugin(task: Task):
    fault_injector.inject(task.kind)  # May raise
    # ... normal execution
```

---

**Server Dispatcher Chaos:**

Randomly defer enqueue (1–3s) for X% of items:

```python
class DispatcherChaos:
    def __init__(self, delay_prob: float = 0.0):
        self.delay_prob = delay_prob
    
    def maybe_delay(self):
        """Randomly inject dispatch delay"""
        if random.random() < self.delay_prob:
            delay = random.uniform(1, 3)
            logger.info("Chaos: Delaying dispatch", delay_sec=delay)
            time.sleep(delay)
```

---

**Sink Chaos:**

Add retryable and fatal error modes via env toggles:

```python
class SinkChaos:
    def __init__(self):
        self.failure_rate = float(os.getenv("NOETL_SINK_CHAOS_RATE", "0.0"))
    
    def maybe_fail(self):
        """Randomly fail sink write"""
        if random.random() < self.failure_rate:
            if random.random() < 0.7:
                raise RetryableError("Chaos: Sink retryable error")
            else:
                raise FatalError("Chaos: Sink fatal error")
```

---

### Test Matrix (Must-Pass Scenarios)

**1. Duplicate Deliveries → Exactly-Once Sinks**

```python
# Worker receives same task_key twice
# Expected: Second execution skips (dedupe cache)
# Expected: Sink ledger prevents double write
```

---

**2. Worker Crash After Effect But Before ACK**

```python
# Worker performs sink write → crashes before ACK
# Server retries task (visibility timeout expires)
# Expected: Sink ledger prevents double write
```

---

**3. Server Restart During Long Loop**

```python
# Server dispatches 50/100 items → crashes
# Server restarts, rebuilds state from step_state table
# Expected: Remaining 50 items dispatched
# Expected: loop_done() gate works correctly
```

---

**4. DLQ Receives Terminal Failures and Replay Works**

```python
# Task fails 6 times → DLQ
# Operator patches spec
# Replay succeeds
# Expected: DLQ entry marked as replayed
```

---

## 9.5 Backpressure & Flow Control

---

### Queue-Centric

**Watermarks:**

```yaml
backpressure:
  wm_hi_queue_depth: 20000  # Pause new loop dispatches
  wm_lo_queue_depth: 5000   # Resume normal
```

**Behavior:**
- **WM_HI exceeded**: Pause new loop dispatches; only route one successor at a time
- **WM_LO reached**: Resume normal dispatch

**Implementation:**

```python
class QueueWatermarkController:
    def __init__(self, wm_hi: int, wm_lo: int):
        self.wm_hi = wm_hi
        self.wm_lo = wm_lo
        self.paused = False
    
    def update(self, queue_depth: int):
        """Update backpressure state based on queue depth"""
        if queue_depth > self.wm_hi:
            if not self.paused:
                logger.warning("Queue depth exceeded WM_HI, pausing dispatch",
                              depth=queue_depth, wm_hi=self.wm_hi)
                self.paused = True
        elif queue_depth < self.wm_lo:
            if self.paused:
                logger.info("Queue depth below WM_LO, resuming dispatch",
                           depth=queue_depth, wm_lo=self.wm_lo)
                self.paused = False
    
    def can_dispatch_loop(self) -> bool:
        """Check if can dispatch new loop items"""
        return not self.paused
    
    def can_dispatch_successor(self) -> bool:
        """Always allow one successor (critical path)"""
        return True  # Even when paused
```

---

**Priority Queues:**

Critical control tasks (reducers, joins) on higher priority:

```yaml
- step: join_results
  tool:
    kind: workbook
    name: join
  priority: 10  # Higher priority
```

**Implementation:**

```sql
-- Task queue with priority
CREATE INDEX idx_task_queue_priority ON task_queue(priority DESC, created_at);

-- Poll query
SELECT * FROM task_queue
WHERE lease_expires_at IS NULL OR lease_expires_at < NOW()
ORDER BY priority DESC, created_at
LIMIT 1
FOR UPDATE SKIP LOCKED
```

---

**Batched ACKs:**

Worker ACKs every N tasks or T seconds to amortize cost:

```python
class BatchedAcker:
    def __init__(self, batch_size: int = 10, flush_interval_sec: float = 5.0):
        self.batch_size = batch_size
        self.flush_interval = flush_interval_sec
        self.pending = []
        self.last_flush = time.time()
    
    def ack(self, message_id: str):
        """Queue ACK"""
        self.pending.append(message_id)
        
        if len(self.pending) >= self.batch_size or \
           time.time() - self.last_flush > self.flush_interval:
            self.flush()
    
    def flush(self):
        """Flush pending ACKs"""
        if not self.pending:
            return
        
        db.execute("""
            DELETE FROM task_queue
            WHERE message_id = ANY($1)
        """, [self.pending])
        
        logger.info("Batched ACK", count=len(self.pending))
        self.pending.clear()
        self.last_flush = time.time()
```

---

### Context Lock / Contention

**Server serializes context mutation per execution** (single writer):

```python
class ContextLock:
    def __init__(self):
        self.locks = {}  # execution_id -> Lock
    
    def acquire(self, execution_id: str) -> Lock:
        """Get lock for execution"""
        if execution_id not in self.locks:
            self.locks[execution_id] = threading.Lock()
        return self.locks[execution_id]

# Usage
with context_lock.acquire(execution_id):
    # Mutate context safely
    exec_state.context["result"] = new_value
    persist_context(exec_state)
```

**Result handling should be idempotent** so replays are safe.

---

### Admission Control

**Reject/queue new executions when system at capacity:**

```yaml
limits:
  max_executions: 200
  max_inflight_tasks: 5000
```

**Implementation:**

```python
class AdmissionController:
    def __init__(self, max_executions: int, max_inflight_tasks: int):
        self.max_executions = max_executions
        self.max_inflight_tasks = max_inflight_tasks
    
    def can_admit(self) -> bool:
        """Check if can admit new execution"""
        running_execs = self._count_running_executions()
        inflight_tasks = self._count_inflight_tasks()
        
        if running_execs >= self.max_executions:
            logger.warning("Execution limit reached", 
                          running=running_execs, 
                          max=self.max_executions)
            return False
        
        if inflight_tasks >= self.max_inflight_tasks:
            logger.warning("Task queue limit reached",
                          inflight=inflight_tasks,
                          max=self.max_inflight_tasks)
            return False
        
        return True
    
    def _count_running_executions(self) -> int:
        """Count running executions"""
        return db.execute(
            "SELECT COUNT(*) FROM execution WHERE status = 'running'"
        ).scalar()
    
    def _count_inflight_tasks(self) -> int:
        """Count inflight tasks"""
        return db.execute(
            "SELECT COUNT(*) FROM task_queue WHERE lease_expires_at > NOW()"
        ).scalar()

# Usage in API
@app.post("/api/executions")
def create_execution(request: ExecutionRequest):
    if not admission_controller.can_admit():
        raise HTTPException(503, "System at capacity, try again later")
    
    # ... create execution
```

---

**CLI Control:**

```bash
clictl server set --max-executions 200 --max-inflight-tasks 5000
```

---

## 9.6 Canary Rollout Recipe

---

### Stage 0 — Dark-Launch

**Actions:**
- Enable validators, helpers, and sink ledgers behind flags
- Run both old & new validators in CI; new one non-blocking

**Feature Flags:**
```yaml
engine:
  dsl_v2_enabled: false
  validate_v2_shadow: true  # Run v2 validator but don't block
```

**CI Configuration:**
```yaml
# .github/workflows/ci.yml
- name: Validate DSL v2 (shadow)
  run: |
    make dsl.validate-v2 || echo "V2 validation failed (shadow)"
  continue-on-error: true
```

---

### Stage 1 — Sample Executions

**Goal:** Route 5% of new executions to v2 engine

**Feature Gate:**
```python
def choose_engine(execution_id: str) -> str:
    """Choose execution engine"""
    canary_rate = float(os.getenv("NOETL_V2_CANARY_RATE", "0.0"))
    
    # Hash-based routing (stable per execution)
    hash_val = int(hashlib.sha256(execution_id.encode()).hexdigest(), 16)
    if (hash_val % 100) < (canary_rate * 100):
        return "v2"
    return "v1"
```

**Comparison Metrics:**

Track side-by-side:
```python
# Step path parity
v1_steps = set(v1_execution["step_states"].keys())
v2_steps = set(v2_execution["step_states"].keys())
assert v1_steps == v2_steps, "Step paths differ"

# Context final snapshot checksum (redacted)
v1_checksum = hashlib.sha256(json.dumps(redact_dict(v1_context), sort_keys=True).encode()).hexdigest()
v2_checksum = hashlib.sha256(json.dumps(redact_dict(v2_context), sort_keys=True).encode()).hexdigest()
assert v1_checksum == v2_checksum, "Context mismatch"

# Sinks count and target parity
v1_sinks = count_sinks(v1_execution)
v2_sinks = count_sinks(v2_execution)
assert v1_sinks == v2_sinks, "Sink counts differ"
```

---

### Stage 2 — Per-Workflow Opt-In

**Goal:** Roll forward critical workflows only after parity verified

**Metadata Label:**
```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: user_processor
  engine: v2  # Explicit opt-in
```

**Routing:**
```python
def choose_engine(workflow_ref: str, execution_id: str) -> str:
    """Choose engine based on workflow metadata"""
    metadata = load_workflow_metadata(workflow_ref)
    
    if metadata.get("engine") == "v2":
        return "v2"
    
    # Fallback to canary
    return choose_engine_canary(execution_id)
```

---

### Stage 3 — Raise Traffic

**Goal:** 25% → 50% → 100% with health SLOs

**SLOs:**
- Step failure rate < 1%
- Mean step latency within P95 + 20%

**Incremental Rollout:**

```bash
# Week 1: 25%
export NOETL_V2_CANARY_RATE=0.25

# Week 2: 50% (if SLOs met)
export NOETL_V2_CANARY_RATE=0.50

# Week 3: 100% (if SLOs met)
export NOETL_V2_CANARY_RATE=1.0
```

**SLO Monitoring:**

```promql
# Step failure rate
rate(noetl_step_runs_total{ok="false"}[1h]) / rate(noetl_step_runs_total[1h]) < 0.01

# Mean step latency check
rate(noetl_step_duration_seconds_sum[1h]) / rate(noetl_step_duration_seconds_count[1h]) 
< 
histogram_quantile(0.95, rate(noetl_step_duration_seconds_bucket{engine="v1"}[7d])) * 1.2
```

---

### Stage 4 — Decommission Legacy

**Actions:**
- Disable legacy parser and `--allow-legacy-iter`
- Keep rollback switch for one minor release

**Rollback Switch:**

```bash
# Per-execution override via API
curl -X POST http://server/api/executions \
  -d '{"workflow_ref": "...", "workload": {...}, "engine": "v1"}'
```

**Implementation:**
```python
@app.post("/api/executions")
def create_execution(request: ExecutionRequest):
    # Allow override
    engine = request.engine or "v2"  # Default v2
    
    if engine not in ["v1", "v2"]:
        raise ValueError(f"Invalid engine: {engine}")
    
    # Use specified engine
    execution_id = initialize_execution(request.workflow_ref, request.workload, engine)
    return {"execution_id": execution_id}
```

**Timeline:**
- Keep `engine=v1` option for **one minor release** (e.g., v2.1)
- Remove completely in v2.2

---

## 9.7 Policy Toggles (Operational Safety)

```yaml
# File: config/noetl.yaml

engine:
  exactly_once_sinks: true  # Enable sink ledgers and idempotency
  route_after_all_sinks: true  # Wait for all sinks before routing
  render_args_server_side: true  # Server renders args before dispatch

limits:
  max_parallel_items_per_step: 250  # Cap loop concurrency
  max_inflight_tasks: 5000  # Global task queue limit
  per_kind_caps:
    http: 128
    postgres: 32
    python: 16
    duckdb: 8

backpressure:
  wm_hi_queue_depth: 20000  # High watermark
  wm_lo_queue_depth: 5000   # Low watermark
  slow_sink_threshold_ms: 5000  # Sink considered slow if >5s

retries:
  plugin:
    max_attempts: 6
    base_ms: 200
    max_ms: 30000
  sink:
    max_attempts: 8
    base_ms: 200
    max_ms: 60000

admission:
  max_executions: 200  # Max concurrent executions
  max_inflight_tasks: 5000  # Max in-flight tasks
  reject_when_at_capacity: true  # 503 vs queue
```

---

## 9.8 Worker Idempotency Helpers (Code Sketch)

```python
# File: noetl/worker/idempotency.py

import time
from collections import OrderedDict
from threading import Lock

class DedupeCache:
    """LRU cache with TTL for task deduplication"""
    
    def __init__(self, maxsize: int = 10000, ttl: int = 600):
        """
        Args:
            maxsize: Maximum cache entries
            ttl: Time-to-live in seconds (default 10 minutes)
        """
        self.maxsize = maxsize
        self.ttl = ttl
        self._data = OrderedDict()
        self._lock = Lock()
    
    def seen(self, key: str) -> bool:
        """
        Check if key was seen recently.
        
        Returns:
            True if key exists (duplicate), False if new
        """
        with self._lock:
            now = time.time()
            
            # Purge expired entries
            expired = [k for k, (ts, _) in self._data.items() if now - ts > self.ttl]
            for k in expired:
                self._data.pop(k, None)
            
            # Check if seen
            if key in self._data:
                # Move to end (LRU)
                self._data.move_to_end(key)
                return True
            
            # Mark as seen
            self._data[key] = (now, True)
            
            # Evict oldest if over capacity
            if len(self._data) > self.maxsize:
                self._data.popitem(last=False)  # Remove oldest (LRU)
            
            return False
    
    def clear(self):
        """Clear all entries"""
        with self._lock:
            self._data.clear()
    
    def size(self) -> int:
        """Get current cache size"""
        with self._lock:
            return len(self._data)
```

---

**Usage in Worker:**

```python
# File: noetl/worker/executor.py

# Initialize dedupe cache
dedupe_cache = DedupeCache(maxsize=10000, ttl=600)

def execute_task(task: Task) -> TaskResult:
    """Execute task with deduplication"""
    task_key = task.payload["task_key"]
    
    # Check dedupe cache
    if dedupe_cache.seen(task_key):
        logger.info("Duplicate task detected, short-circuit",
                   task_key=task_key,
                   message_id=task.message_id)
        
        # ACK without executing
        return TaskResult(
            message_id=task.message_id,
            execution_id=task.execution_id,
            step_id=task.step_id,
            ok=True,
            this={"status": "duplicate_skipped"}
        )
    
    # Execute normally
    try:
        result = plugin_executor.execute(task)
        return result
    except Exception as e:
        logger.exception("Task execution failed", task_key=task_key)
        raise
```

---

## 9.9 End-to-End Invariants (What Must Always Hold)

---

### 1. Step Runs At Most Once Per Execution

**Invariant:**
```python
step.<id>.status.done flips once (false → true, never back)
```

**Enforcement:**
- Server checks `step_state.status.done` before dispatch
- Idempotent dispatch (multiple calls → single execution)

---

### 2. Each Sink Entry Applied At Most Once Per Step Item

**Invariant:**
```python
For each (execution_id, step_id, loop_key, sink_id):
  sink write occurs exactly once
```

**Enforcement:**
- `sink_key` uniqueness in `noetl_sink_ledger`
- UPSERT pattern with conflict handling
- Overwrite-safe paths in object stores

---

### 3. Loop Done Gate Correctness

**Invariant:**
```python
loop_done(step) == true  ⟺  (completed == total) OR (done == true)
```

**Enforcement:**
- Server increments `completed` counter atomically per item result
- `loop_done()` helper reads counter from context
- Gate evaluation is read-only

---

### 4. When/Edge Guards Are Side-Effect-Free

**Invariant:**
```python
Evaluating when/next conditions:
  - No mutations to context
  - Bounded execution time (timeouts)
  - Deterministic given same context snapshot
```

**Enforcement:**
- Jinja env uses `ImmutableDict` for `step` namespace
- Evaluation timeout (default 100ms)
- Helpers are pure functions (read-only)

---

### 5. Replay Does Not Change Final Results

**Invariant:**
```python
Running same workflow with same workload → same sink writes
```

**Enforcement:**
- All sinks are idempotent (UPSERT, overwrite, ledger)
- Deterministic task keys (execution_id + step_id + loop_key)
- No side effects in guards or helpers

---

## 9.10 Chaos Test Suite (Runnable Recipe)

---

### Test 1: Worker Crash After Effect

**File:** `tests/chaos/test_exactly_once.py`

```python
import pytest
from noetl.testing import ServerFixture, WorkerFixture, PostgresFixture

def test_worker_crash_after_effect(server: ServerFixture, 
                                    worker: WorkerFixture,
                                    postgres: PostgresFixture):
    """
    Test: Worker crashes after sink write but before ACK.
    Expected: Sink write happens exactly once (ledger prevents double).
    """
    # Arrange: Workflow with postgres sink (upsert) + ledger
    workflow = """
    - step: write_user
      tool:
        kind: postgres
        spec:
          query: "INSERT INTO users (id, name) VALUES (%(id)s, %(name)s)"
        result:
          sink:
            - postgres:
                table: users
                mode: upsert
                key: id
      next: [{ step: end }]
    - step: end
      desc: End
    """
    
    # Inject fault: crash after sink write
    worker.inject_fault("crash_after_sink", probability=1.0)
    
    # Act: Start execution
    exec_id = server.start_execution(workflow, workload={"id": 1, "name": "Alice"})
    
    # Worker will crash, task will retry (visibility timeout)
    # New worker picks up task
    worker2 = WorkerFixture()
    worker2.start()
    
    server.wait_for_completion(exec_id, timeout=30)
    
    # Assert: Row count == 1 (no duplicates)
    rows = postgres.query("SELECT COUNT(*) FROM users WHERE id = 1")
    assert rows[0][0] == 1, "Expected exactly one row"
    
    # Assert: Ledger has exactly 1 entry
    ledger_rows = postgres.query(
        "SELECT COUNT(*) FROM noetl_sink_ledger WHERE execution_id = $1",
        [exec_id]
    )
    assert ledger_rows[0][0] == 1, "Expected exactly one ledger entry"
```

---

### Test 2: Duplicate Delivery

**File:** `tests/chaos/test_dup_delivery.py`

```python
def test_duplicate_delivery_no_double_sink(server: ServerFixture,
                                             worker: WorkerFixture,
                                             postgres: PostgresFixture):
    """
    Test: Task delivered multiple times (duplicate messages).
    Expected: Sink write happens exactly once (dedupe cache + ledger).
    """
    workflow = """
    - step: write_user
      tool:
        kind: postgres
        spec:
          query: "INSERT INTO users (id, name) VALUES (%(id)s, %(name)s)"
        result:
          sink:
            - postgres:
                table: users
                mode: upsert
                key: id
    """
    
    # Inject fault: suppress ACK first 2 times (causes redelivery)
    worker.inject_fault("dup_delivery", times=2)
    
    exec_id = server.start_execution(workflow, workload={"id": 2, "name": "Bob"})
    server.wait_for_completion(exec_id)
    
    # Assert: Row count == 1
    rows = postgres.query("SELECT COUNT(*) FROM users WHERE id = 2")
    assert rows[0][0] == 1
    
    # Assert: Ledger count == 1
    ledger_rows = postgres.query(
        "SELECT COUNT(*) FROM noetl_sink_ledger WHERE execution_id = $1",
        [exec_id]
    )
    assert ledger_rows[0][0] == 1
```

---

### Test 3: Backpressure Throttles

**File:** `tests/chaos/test_backpressure.py`

```python
def test_backpressure_throttles(server: ServerFixture,
                                 worker: WorkerFixture):
    """
    Test: Backpressure limits in-flight tasks.
    Expected: In-flight task count never exceeds limit.
    """
    # Configure limits
    server.set_limits(max_inflight_tasks=10)
    
    # Workflow with large loop
    workflow = """
    - step: process_items
      loop:
        collection: "{{ range(100) }}"
        element: item
        mode: parallel
      tool:
        kind: python
        spec:
          code: |
            import time
            def main(context, results):
                time.sleep(1)  # Slow task
                return context
    """
    
    exec_id = server.start_execution(workflow, workload={})
    
    # Monitor metrics
    time.sleep(2)  # Let some tasks dispatch
    
    metrics = server.get_metrics()
    inflight = metrics["noetl_task_queue_inflight"]
    
    assert inflight <= 10, f"In-flight tasks ({inflight}) exceeded limit (10)"
    
    server.wait_for_completion(exec_id)
```

---

### Test 4: Server Restart During Loop

**File:** `tests/chaos/test_server_restart.py`

```python
def test_server_restart_during_loop(server: ServerFixture,
                                     worker: WorkerFixture,
                                     postgres: PostgresFixture):
    """
    Test: Server restarts during long loop execution.
    Expected: Loop resumes and completes correctly.
    """
    workflow = """
    - step: process_users
      loop:
        collection: "{{ range(100) }}"
        element: user_id
        mode: sequential
      tool:
        kind: postgres
        spec:
          query: "INSERT INTO processed (id) VALUES (%(id)s)"
        args:
          id: "{{ user_id }}"
      next: [{ step: end }]
    - step: end
      when: "{{ loop_done('process_users') }}"
      desc: End
    """
    
    exec_id = server.start_execution(workflow, workload={})
    
    # Wait for 50 items
    time.sleep(5)
    
    # Crash server
    server.stop()
    
    # Restart server
    server.start()
    
    # Wait for completion
    server.wait_for_completion(exec_id, timeout=120)
    
    # Assert: All 100 items processed
    rows = postgres.query("SELECT COUNT(*) FROM processed")
    assert rows[0][0] == 100
    
    # Assert: loop_done gate triggered
    exec_state = server.get_execution(exec_id)
    assert exec_state["step_states"]["process_users"]["status"]["done"]
    assert exec_state["step_states"]["end"]["status"]["done"]
```

---

### Test 5: DLQ and Replay

**File:** `tests/chaos/test_dlq_replay.py`

```python
def test_dlq_receives_terminal_failures_and_replay_works(server: ServerFixture,
                                                          worker: WorkerFixture):
    """
    Test: Task fails max attempts → DLQ, then replay succeeds.
    Expected: DLQ entry created, replay fixes issue.
    """
    workflow = """
    - step: call_api
      tool:
        kind: http
        spec:
          url: "https://bad-url.invalid/users"
          method: GET
    """
    
    # Configure low max_attempts for faster test
    worker.set_retry_policy(max_attempts=3)
    
    exec_id = server.start_execution(workflow, workload={})
    server.wait_for_completion(exec_id, timeout=30)
    
    # Assert: Execution failed
    exec_state = server.get_execution(exec_id)
    assert exec_state["status"] == "fail"
    
    # Assert: DLQ has entry
    dlq_entries = server.list_dlq(execution_id=exec_id)
    assert len(dlq_entries) == 1
    message_id = dlq_entries[0]["message_id"]
    
    # Patch and replay
    server.replay_dlq(
        message_id=message_id,
        patch={"spec.url": "https://httpbin.org/get"}
    )
    
    # Wait for replay completion
    time.sleep(5)
    
    # Assert: Replay succeeded
    exec_state = server.get_execution(exec_id)
    assert exec_state["status"] == "ok"
    
    # Assert: DLQ entry marked as replayed
    dlq_entry = server.get_dlq(message_id)
    assert dlq_entry["status"] == "replayed"
```

---

## 9.11 Final Hardening Checklist

**Idempotency:**
- [ ] Task & sink idempotency keys wired in server dispatcher
- [ ] Worker dedupe cache enabled (LRU, 10-minute TTL)
- [ ] `task_key` and `sink_key` attached to all messages

**Exactly-Once Sinks:**
- [ ] Postgres sink ledger table created (`noetl_sink_ledger`)
- [ ] Postgres upsert + ledger pattern implemented
- [ ] DuckDB DELETE + INSERT pattern implemented
- [ ] S3/GCS deterministic paths with metadata headers
- [ ] HTTP Idempotency-Key header support
- [ ] Kafka idempotent producer or message key strategy

**Concurrency Controls:**
- [ ] Loop `concurrency` knob implemented and enforced
- [ ] Per-step `rate_per_sec` token bucket limiter
- [ ] Per-kind concurrency caps respected (server + worker)
- [ ] Fair queue rotation to avoid starvation

**Backpressure:**
- [ ] Queue watermarks enforced (WM_HI, WM_LO)
- [ ] Worker busy gauge monitored
- [ ] Admission control rejects at capacity (503)
- [ ] `route_after_all_sinks` policy option

**Chaos Suite:**
- [ ] Test: Worker crash after effect → exactly-once
- [ ] Test: Duplicate delivery → no double sink
- [ ] Test: Server restart during loop → resumes correctly
- [ ] Test: Backpressure throttles in-flight tasks
- [ ] Test: DLQ receives terminal failures
- [ ] Test: DLQ replay succeeds

**Canary Rollout:**
- [ ] Stage 0: Dark-launch (shadow validation)
- [ ] Stage 1: 5% sample executions with parity checks
- [ ] Stage 2: Per-workflow opt-in via metadata
- [ ] Stage 3: 25% → 50% → 100% with SLOs met
- [ ] Stage 4: Legacy decommissioned, rollback switch available

**Policy Toggles:**
- [ ] `exactly_once_sinks` flag documented
- [ ] `route_after_all_sinks` flag documented
- [ ] Concurrency limits configurable via YAML/env
- [ ] Backpressure watermarks configurable
- [ ] Admission control limits configurable

**Documentation:**
- [ ] Rollback switch documented (`EXECUTION_ENGINE=v1|v2`)
- [ ] Retention: Keep for one minor release
- [ ] End-to-end invariants documented
- [ ] Chaos test suite runnable via `pytest tests/chaos/`

---

## Next Steps

This document provides the **complete hardening strategy** for production DSL v2. Recommended actions:

1. **Implement idempotency keys** (server dispatcher + worker dedupe cache)
2. **Build exactly-once sinks** (ledger tables, UPSERT patterns, S3 paths)
3. **Add concurrency controls** (loop caps, rate limiters, per-kind limits)
4. **Set up backpressure** (watermarks, admission control, fair queues)
5. **Write chaos tests** (worker crash, duplicate delivery, backpressure, server restart, DLQ)
6. **Execute canary rollout** (dark-launch → 5% → 25% → 50% → 100%)
7. **Monitor SLOs** (failure rate < 1%, latency within P95 + 20%)
8. **Document rollback** (keep `engine=v1` option for one minor release)
9. **Validate invariants** (step runs once, sinks exactly-once, loop gates correct)

---

**Ready for hardening implementation kickoff.**
