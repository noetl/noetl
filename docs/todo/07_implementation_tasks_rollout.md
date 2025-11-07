# Implementation Tasks (Server, Worker, CLI) + Rollout

**Status:** Planning  
**Date:** November 6, 2025  
**Objective:** Define complete implementation roadmap for DSL v2 runtime, data model, APIs, and rollout strategy

---

## 7.1 Runtime Contracts (Recap → Code Targets)

### Authoring DSL Surface

**Step Keys (4-char canonical):**
- `step` - Unique identifier (required)
- `desc` - Human-readable description
- `when` - Gate condition (evaluated on call)
- `bind` - Extra context bindings
- `loop` - Iteration controller
- `tool` - Actionable unit
- `next` - Routing edges

---

### Engine Helpers (Jinja Globals)

**Status Query Functions:**
- `done(step_id)` - Step completed
- `ok(step_id)` - Step succeeded
- `fail(step_id)` - Step failed
- `running(step_id)` - Step executing
- `loop_done(step_id)` - Loop drained
- `all_done([ids])` - All steps done
- `any_done([ids])` - Any step done

**Implementation target:** `noetl/runtime/helpers.py`

---

### Engine Namespace (Read-Only)

**Status Structure:**
```python
context = {
    "step": {
        "<step_id>": {
            "status": {
                "running": bool,
                "done": bool,
                "ok": bool | None,
                "error": str | None,
                "total": int | None,      # Loop only
                "completed": int,         # Loop only
                "succeeded": int,         # Loop only
                "failed": int            # Loop only
            }
        }
    }
}
```

**Implementation target:** `noetl/server/api/execution/state.py`

---

### Result Pipeline

**Processing order:**
1. Tool returns `this` (raw result)
2. If `result.pick`: evaluate → `out`
3. If `result.as`: store `context[as] = out`
4. If `result.collect`: accumulate into `context[collect.into]`
5. For each `result.sink`: fan-out writes

**Implementation target:** `noetl/server/api/execution/result.py`

---

### Control Model (Petri-Net)

**Execution semantics:**
- Steps run **only when called** by predecessors via `next`
- `when` is a gate evaluated on each call
- Step executes **once** (idempotent)
- Parking: when `when=false`, step waits for re-evaluation
- Routing: after step completes, evaluate `next` edges

**Implementation target:** `noetl/server/api/execution/orchestrator.py`

---

## 7.2 Data Model / Queues (Server-Owned)

**Note:** If you already have event sourcing, reuse existing tables/streams. Below are minimal columns.

---

### Table: `execution`

**One row per workflow run**

```sql
CREATE TABLE execution (
    execution_id TEXT PRIMARY KEY,           -- Snowflake ID or UUID
    workflow_ref TEXT NOT NULL,              -- Path/name/version
    status TEXT NOT NULL                     -- enum: running|ok|fail|canceled
        CHECK (status IN ('running', 'ok', 'fail', 'canceled')),
    context JSONB NOT NULL DEFAULT '{}',     -- Mutable run-level context (excludes step.*.status)
    workload JSONB,                          -- Initial input payload
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMP
);

CREATE INDEX idx_execution_status ON execution(status);
CREATE INDEX idx_execution_created_at ON execution(created_at);
```

---

### Table: `step_state`

**Step execution status per execution**

```sql
CREATE TABLE step_state (
    execution_id TEXT NOT NULL REFERENCES execution(execution_id) ON DELETE CASCADE,
    step_id TEXT NOT NULL,
    status JSONB NOT NULL DEFAULT '{}',      -- Exactly step.<id>.status.*
    context_delta JSONB,                     -- Values saved via result.as / collect
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (execution_id, step_id)
);

CREATE INDEX idx_step_state_execution ON step_state(execution_id);
```

---

### Table: `task_queue`

**Server → Worker task dispatch**

```sql
CREATE TABLE task_queue (
    message_id TEXT PRIMARY KEY,             -- UUID
    execution_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    payload JSONB NOT NULL,                  -- Rendered tool block with args (per loop item if any)
    attempt INT NOT NULL DEFAULT 0,
    priority INT NOT NULL DEFAULT 0,
    not_before TIMESTAMP NOT NULL DEFAULT NOW(),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    lease_expires_at TIMESTAMP,              -- Visibility timeout
    worker_id TEXT                           -- Current lease holder
);

CREATE INDEX idx_task_queue_poll ON task_queue(priority DESC, not_before, lease_expires_at)
    WHERE lease_expires_at IS NULL OR lease_expires_at < NOW();
```

**Note:** Replace with broker (Redis/Kafka/SQS) if preferred, but keep same payload shapes.

---

### Table: `task_result`

**Worker → Server result reporting**

```sql
CREATE TABLE task_result (
    message_id TEXT PRIMARY KEY REFERENCES task_queue(message_id),
    execution_id TEXT NOT NULL,
    step_id TEXT NOT NULL,
    ok BOOLEAN NOT NULL,
    this JSONB,                              -- Raw plugin return
    logs TEXT,                               -- Optional execution logs
    error TEXT,                              -- Error details if failed
    stamp TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_task_result_execution ON task_result(execution_id, step_id);
```

---

## 7.3 Server — Orchestration Responsibilities

### S1. Parse & Validate Workflow (DSL v2)

**Responsibilities:**
- Enforce JSON Schema + lints from Portion 3
- Build internal graph representation

**Implementation:**

```python
# File: noetl/server/api/workflow/parser.py

from scripts.validate_dsl_v2 import validate_schema
from scripts.lint_dsl_v2 import lint_workflow

class WorkflowParser:
    def parse(self, yaml_content: str) -> WorkflowGraph:
        """Parse and validate DSL v2 workflow"""
        # Load YAML
        data = yaml.safe_load(yaml_content)
        
        # Validate schema
        validate_schema(data)
        
        # Lint semantics
        lint_workflow(data)
        
        # Build graph
        graph = WorkflowGraph()
        for step in data.get("workflow", []):
            node = StepNode(
                id=step["step"],
                defn=step,
                outgoing_edges=self._parse_edges(step.get("next", []))
            )
            graph.add_node(node)
        
        return graph
    
    def _parse_edges(self, next_list: list) -> list[Edge]:
        """Parse next edges"""
        edges = []
        for entry in next_list:
            edges.append(Edge(
                condition=entry.get("when"),
                target=entry["step"]
            ))
        return edges
```

**Graph structure:**

```python
@dataclass
class StepNode:
    id: str
    defn: dict  # Full step definition
    outgoing_edges: list[Edge]

@dataclass
class Edge:
    condition: str | None  # Jinja expression or None (else)
    target: str  # Target step ID

@dataclass
class WorkflowGraph:
    nodes: dict[str, StepNode]
    start_node: str  # "start" or first step
```

---

### S2. Initialize Execution

**Responsibilities:**
- Persist execution with initial context
- Inject empty `step.*.status` dicts
- Enqueue `start` step

**Implementation:**

```python
# File: noetl/server/api/execution/initializer.py

class ExecutionInitializer:
    def initialize(self, workflow_ref: str, workload: dict) -> str:
        """Initialize new execution"""
        execution_id = generate_snowflake_id()
        
        # Build initial context
        context = {
            "execution_id": execution_id,
            "workload": workload,
            "step": {}  # Will populate with status dicts
        }
        
        # Persist execution
        db.execute("""
            INSERT INTO execution (execution_id, workflow_ref, status, context, workload)
            VALUES (%(id)s, %(ref)s, 'running', %(ctx)s, %(wl)s)
        """, {"id": execution_id, "ref": workflow_ref, "ctx": context, "wl": workload})
        
        # Enqueue start step
        self._enqueue_call(execution_id, "start")
        
        return execution_id
    
    def _enqueue_call(self, execution_id: str, step_id: str):
        """Enqueue step call"""
        # Implementation in S3
        pass
```

---

### S3. "Call" Semantics & Gating

**Responsibilities:**
- Track pending calls per step
- Evaluate `when` condition before dispatch
- Park step if `when=false`
- Ensure idempotence (step runs once)

**Implementation:**

```python
# File: noetl/server/api/execution/orchestrator.py

class Orchestrator:
    def on_step_called(self, execution_id: str, step_id: str):
        """Handle step call (from predecessor or start)"""
        exec_state = self.load_execution(execution_id)
        step_state = self.get_step_state(execution_id, step_id)
        
        # Idempotence: already done
        if step_state.get("status", {}).get("done"):
            logger.info(f"Step {step_id} already done, ignoring call")
            return
        
        # Evaluate when condition
        step_defn = self.graph.nodes[step_id].defn
        when_expr = step_defn.get("when")
        
        if when_expr:
            # Build Jinja env with helpers
            env = self._create_jinja_env(exec_state.context)
            template = env.from_string(when_expr)
            result = template.render(**exec_state.context)
            
            if not self._is_truthy(result):
                logger.info(f"Step {step_id} parked (when=false)")
                self._park_call(execution_id, step_id)
                return
        
        # Dispatch step
        self._dispatch(execution_id, step_id)
    
    def _park_call(self, execution_id: str, step_id: str):
        """Park step for later re-evaluation"""
        # Store pending call count (in-memory or DB)
        self.pending_calls[execution_id][step_id] += 1
    
    def _dispatch(self, execution_id: str, step_id: str):
        """Dispatch step for execution"""
        # Implementation in S4
        pass
```

---

### S4. Loop Execution

**Responsibilities:**
- Render collection and iterate
- Dispatch items (sequential or parallel)
- Track loop completion counters
- Set `done=true` when loop drains

**Implementation:**

```python
# File: noetl/server/api/execution/dispatcher.py

class Dispatcher:
    def dispatch(self, execution_id: str, step_id: str):
        """Dispatch step (with or without loop)"""
        exec_state = self.load_execution(execution_id)
        step_defn = self.graph.nodes[step_id].defn
        
        # Mark step start
        self._mark_start(exec_state, step_id)
        
        # Check for loop
        loop_config = step_defn.get("loop")
        
        if loop_config:
            self._dispatch_loop(exec_state, step_id, loop_config)
        else:
            self._dispatch_single(exec_state, step_id)
    
    def _dispatch_loop(self, exec_state, step_id: str, loop_config: dict):
        """Dispatch loop items"""
        # Render collection
        collection_expr = loop_config["collection"]
        collection = self._render(exec_state.context, collection_expr)
        items = list(collection)
        
        # Mark total
        self._mark_start(exec_state.context, step_id, total=len(items))
        
        mode = loop_config.get("mode", "sequential")
        element_name = loop_config["element"]
        
        if mode == "parallel":
            # Dispatch all items
            for idx, item in enumerate(items):
                self._enqueue_task(exec_state, step_id, item, element_name, idx)
        
        elif mode == "sequential":
            # Dispatch first item only; on completion, dispatch next
            if items:
                self._enqueue_task(exec_state, step_id, items[0], element_name, 0)
                # Store remaining items in step_state
                self._store_pending_items(exec_state.execution_id, step_id, items[1:])
    
    def _dispatch_single(self, exec_state, step_id: str):
        """Dispatch single (non-loop) task"""
        payload = self._render_tool_payload(exec_state, step_id)
        self._enqueue_task_queue(exec_state.execution_id, step_id, payload)
    
    def _enqueue_task(self, exec_state, step_id: str, item, element_name: str, idx: int):
        """Enqueue single loop item task"""
        # Build context with loop element
        loop_context = exec_state.context.copy()
        loop_context[element_name] = item
        loop_context["_loop"] = {"index": idx, "item": item}
        
        # Render tool payload
        payload = self._render_tool_payload_with_context(loop_context, step_id)
        payload["loop_index"] = idx
        
        self._enqueue_task_queue(exec_state.execution_id, step_id, payload)
```

---

### S5. Result Handling (Server-Side)

**Responsibilities:**
- Receive `task_result` from worker
- Apply `result.pick` transformation
- Store via `result.as`
- Accumulate via `result.collect`
- Fan-out to `result.sink`

**Implementation:**

```python
# File: noetl/server/api/execution/result.py

class ResultHandler:
    def on_task_result(self, result: TaskResult):
        """Process task result from worker"""
        exec_state = self.load_execution(result.execution_id)
        step_defn = self.graph.nodes[result.step_id].defn
        result_config = step_defn.get("tool", {}).get("result", {})
        
        # 1. Get raw result
        raw = result.this
        
        # 2. Apply pick transformation
        if "pick" in result_config:
            pick_expr = result_config["pick"]
            context = exec_state.context.copy()
            context["this"] = raw
            out = self._render(context, pick_expr)
        else:
            out = raw
        
        # 3. Store via as
        if "as" in result_config:
            as_name = result_config["as"]
            exec_state.context[as_name] = out
        
        # 4. Accumulate via collect
        if "collect" in result_config:
            self._apply_collect(exec_state, result_config["collect"], out)
        
        # 5. Fan-out to sinks
        if "sink" in result_config:
            self._fanout_sinks(exec_state, result.step_id, out, result_config["sink"])
        
        # 6. Update loop counters
        self._update_counters(exec_state, result.step_id, ok=result.ok)
        
        # 7. Check if step done
        if self._is_step_done(exec_state, result.step_id):
            self._finalize_step(exec_state, result.step_id)
    
    def _apply_collect(self, exec_state, collect_config: dict, out):
        """Accumulate result into collection"""
        into = collect_config["into"]
        mode = collect_config.get("mode", "list")
        
        if mode == "list":
            exec_state.context.setdefault(into, []).append(out)
        
        elif mode == "map":
            key_expr = collect_config["key"]
            key = self._render({"out": out}, key_expr)
            exec_state.context.setdefault(into, {})[key] = out
```

---

### S6. Sink Fan-Out

**Responsibilities:**
- Execute or enqueue sink writes
- Choose server-side vs worker-side execution

**Implementation (Worker-Side Sinks - Recommended):**

```python
# File: noetl/server/api/execution/sinks.py

class SinkDispatcher:
    def fanout_sinks(self, exec_state, step_id: str, out, sinks: list):
        """Fan-out to all sinks"""
        for sink_entry in sinks:
            # Each entry is single-key map: {postgres: {...}}
            sink_type = list(sink_entry.keys())[0]
            sink_config = sink_entry[sink_type]
            
            # Enqueue sink task
            self._enqueue_sink_task(
                exec_state.execution_id,
                step_id,
                sink_type,
                sink_config,
                out
            )
    
    def _enqueue_sink_task(self, execution_id: str, step_id: str, 
                           sink_type: str, config: dict, data):
        """Enqueue sink write task to worker"""
        payload = {
            "kind": f"sink:{sink_type}",
            "config": config,
            "data": data,
            "execution_id": execution_id,
            "step_id": step_id
        }
        
        self.task_queue.enqueue(
            execution_id=execution_id,
            step_id=f"{step_id}:sink:{sink_type}",
            payload=payload
        )
```

**Alternative (Server-Side Sinks):**

```python
class SinkDispatcher:
    def fanout_sinks(self, exec_state, step_id: str, out, sinks: list):
        """Execute sinks synchronously on server"""
        for sink_entry in sinks:
            sink_type = list(sink_entry.keys())[0]
            sink_config = sink_entry[sink_type]
            
            # Execute sink writer
            writer = self.sink_registry[sink_type]
            writer.write(config=sink_config, data=out)
```

**Recommendation:** Worker-side for scalability and consistency.

---

### S7. Routing via `next`

**Responsibilities:**
- Evaluate `next` edges in order
- Choose first matching edge
- Call target step

**Implementation:**

```python
# File: noetl/server/api/execution/router.py

class Router:
    def route_next(self, exec_state, step_id: str):
        """Route to next steps"""
        step_node = self.graph.nodes[step_id]
        edges = step_node.outgoing_edges
        
        if not edges:
            logger.info(f"Step {step_id} is terminal")
            return
        
        # Evaluate edges in order
        for edge in edges:
            if edge.condition is None:
                # Else edge (no when)
                self._call_step(exec_state.execution_id, edge.target)
                return
            
            # Evaluate when condition
            env = self._create_jinja_env(exec_state.context)
            template = env.from_string(edge.condition)
            result = template.render(**exec_state.context)
            
            if self._is_truthy(result):
                self._call_step(exec_state.execution_id, edge.target)
                return
        
        logger.warning(f"No next edge matched for step {step_id}")
```

---

### S8. Idempotence / Replays

**Responsibilities:**
- Track `step_state.status.done` to refuse re-dispatch
- Re-evaluate `when` only for parked steps (never for done steps)

**Implementation:**

```python
class Orchestrator:
    def on_step_called(self, execution_id: str, step_id: str):
        """Handle step call with idempotence"""
        step_state = self.get_step_state(execution_id, step_id)
        
        # Idempotence: already done
        if step_state.get("status", {}).get("done"):
            logger.info(f"Step {step_id} already done, ignoring call")
            return
        
        # Re-evaluate when for parked steps
        if step_state.get("parked"):
            if not self._eval_when(execution_id, step_id):
                logger.info(f"Step {step_id} still parked")
                return
        
        # Dispatch
        self._dispatch(execution_id, step_id)
```

---

## 7.4 Worker — Execution Responsibilities

### W1. Poll `task_queue`

**Responsibilities:**
- Claim messages with lease/visibility timeout
- Deserialize payload

**Implementation:**

```python
# File: noetl/worker/poller.py

class TaskPoller:
    def poll(self, pool_name: str, worker_id: str) -> Task | None:
        """Poll for next task"""
        result = db.execute("""
            UPDATE task_queue
            SET lease_expires_at = NOW() + INTERVAL '5 minutes',
                worker_id = %(worker_id)s,
                attempt = attempt + 1
            WHERE message_id = (
                SELECT message_id
                FROM task_queue
                WHERE (lease_expires_at IS NULL OR lease_expires_at < NOW())
                  AND not_before <= NOW()
                ORDER BY priority DESC, created_at
                LIMIT 1
                FOR UPDATE SKIP LOCKED
            )
            RETURNING *
        """, {"worker_id": worker_id})
        
        if not result:
            return None
        
        row = result[0]
        return Task(
            message_id=row["message_id"],
            execution_id=row["execution_id"],
            step_id=row["step_id"],
            payload=row["payload"],
            attempt=row["attempt"]
        )
```

---

### W2. Execute Plugins

**Responsibilities:**
- Registry of plugin executors
- Execute plugin with spec/args/context
- Capture logs and errors
- Return result

**Implementation:**

```python
# File: noetl/worker/executor.py

class PluginExecutor:
    def __init__(self):
        self.registry = {
            "http": HttpPlugin(),
            "postgres": PostgresPlugin(),
            "python": PythonPlugin(),
            "duckdb": DuckDBPlugin(),
            "playbook": PlaybookPlugin(),
            "workbook": WorkbookPlugin(),
        }
    
    def execute(self, task: Task) -> TaskResult:
        """Execute plugin task"""
        payload = task.payload
        kind = payload["tool"]["kind"]
        spec = payload["tool"]["spec"]
        args = payload["tool"].get("args", {})
        
        try:
            # Get plugin
            plugin = self.registry[kind]
            
            # Execute
            result = plugin.run(spec=spec, args=args, context=payload.get("context", {}))
            
            return TaskResult(
                message_id=task.message_id,
                execution_id=task.execution_id,
                step_id=task.step_id,
                ok=True,
                this=result,
                logs=self._get_logs()
            )
        
        except Exception as e:
            logger.exception(f"Task failed: {e}")
            return TaskResult(
                message_id=task.message_id,
                execution_id=task.execution_id,
                step_id=task.step_id,
                ok=False,
                this=None,
                error=str(e),
                logs=self._get_logs()
            )
```

**Python plugin example:**

```python
# File: noetl/plugin/python/executor.py

class PythonPlugin:
    def run(self, spec: dict, args: dict, context: dict):
        """Execute Python code"""
        if "code" in spec:
            # Inline code
            code = spec["code"]
            local_vars = {}
            exec(code, {}, local_vars)
            main_fn = local_vars["main"]
        else:
            # Module + callable
            module = importlib.import_module(spec["module"])
            main_fn = getattr(module, spec["callable"])
        
        # Call main(context, results)
        result = main_fn(context, args)
        return result
```

---

### W3. Emit `task_result`

**Responsibilities:**
- Always return result to server
- Include ok, this, logs, error

**Implementation:**

```python
# File: noetl/worker/reporter.py

class ResultReporter:
    def report(self, result: TaskResult):
        """Report task result to server"""
        db.execute("""
            INSERT INTO task_result (message_id, execution_id, step_id, ok, this, logs, error)
            VALUES (%(msg)s, %(exec)s, %(step)s, %(ok)s, %(this)s, %(logs)s, %(err)s)
        """, {
            "msg": result.message_id,
            "exec": result.execution_id,
            "step": result.step_id,
            "ok": result.ok,
            "this": result.this,
            "logs": result.logs,
            "err": result.error
        })
        
        # Notify server (webhook, queue, or polling)
        self._notify_server(result.execution_id, result.step_id)
```

---

### W4. Sink Plugins (If Server Enqueues Sink Tasks)

**Responsibilities:**
- Execute idempotent writes
- Support multiple sink types

**Implementation:**

```python
# File: noetl/worker/sinks.py

class SinkExecutor:
    def __init__(self):
        self.registry = {
            "postgres": PostgresSink(),
            "s3": S3Sink(),
            "file": FileSink(),
            "duckdb": DuckDBSink(),
        }
    
    def execute_sink(self, task: Task) -> TaskResult:
        """Execute sink write"""
        payload = task.payload
        sink_type = payload["kind"].replace("sink:", "")
        config = payload["config"]
        data = payload["data"]
        
        try:
            sink = self.registry[sink_type]
            sink.write(config=config, data=data)
            
            return TaskResult(
                message_id=task.message_id,
                execution_id=task.execution_id,
                step_id=task.step_id,
                ok=True,
                this={"written": True}
            )
        
        except Exception as e:
            logger.exception(f"Sink failed: {e}")
            return TaskResult(
                message_id=task.message_id,
                execution_id=task.execution_id,
                step_id=task.step_id,
                ok=False,
                error=str(e)
            )
```

**Postgres sink example:**

```python
class PostgresSink:
    def write(self, config: dict, data):
        """Write to Postgres (idempotent upsert)"""
        table = config["table"]
        mode = config.get("mode", "insert")
        key = config.get("key")
        args = config.get("args", {})
        
        if mode == "upsert" and key:
            # Idempotent upsert
            self._upsert(table, key, args)
        else:
            self._insert(table, args)
    
    def _upsert(self, table: str, key: str, data: dict):
        """Upsert with conflict handling"""
        columns = ", ".join(data.keys())
        values = ", ".join([f"%({k})s" for k in data.keys()])
        updates = ", ".join([f"{k} = EXCLUDED.{k}" for k in data.keys() if k != key])
        
        query = f"""
            INSERT INTO {table} ({columns})
            VALUES ({values})
            ON CONFLICT ({key}) DO UPDATE SET {updates}
        """
        
        db.execute(query, data)
```

---

## 7.5 Jinja Helpers and Context Wiring

### Server-Side When/Edge Evaluation

**Implementation:**

```python
# File: noetl/server/api/execution/jinja_env.py

from scripts.jinja_helpers import install_helpers

class JinjaEnvBuilder:
    def create_env(self, context: dict) -> jinja2.Environment:
        """Create Jinja env with helpers"""
        env = jinja2.Environment()
        
        # Install helpers
        install_helpers(env, lambda: context)
        
        # Prohibit mutations to step namespace
        env.globals["step"] = ImmutableDict(context.get("step", {}))
        
        return env

class ImmutableDict(dict):
    """Read-only dict wrapper"""
    def __setitem__(self, key, value):
        raise RuntimeError("Cannot modify step namespace")
```

---

### Worker-Side Templating

**Approach:** Render `tool.spec`, `tool.args`, `result.pick` **server-side** before enqueue.

**Rationale:** Worker is pure executor; server unifies evaluation surface.

**Implementation:**

```python
# File: noetl/server/api/execution/renderer.py

class TemplateRenderer:
    def render_tool_payload(self, context: dict, step_id: str) -> dict:
        """Render tool payload for worker"""
        step_defn = self.graph.nodes[step_id].defn
        tool = step_defn["tool"]
        
        # Render spec
        spec_rendered = self._deep_render(context, tool["spec"])
        
        # Render args
        args_rendered = self._deep_render(context, tool.get("args", {}))
        
        return {
            "tool": {
                "kind": tool["kind"],
                "spec": spec_rendered,
                "args": args_rendered
            },
            "context": context  # Pass for plugin use
        }
    
    def _deep_render(self, context: dict, obj):
        """Recursively render Jinja templates"""
        if isinstance(obj, str):
            template = self.env.from_string(obj)
            return template.render(**context)
        elif isinstance(obj, dict):
            return {k: self._deep_render(context, v) for k, v in obj.items()}
        elif isinstance(obj, list):
            return [self._deep_render(context, item) for item in obj]
        else:
            return obj
```

---

## 7.6 Server APIs (Minimal)

**REST or gRPC. Keep them boring.**

---

### POST `/api/executions`

**Create new execution**

**Request:**
```json
{
  "workflow_ref": "playbooks/user_processor",
  "workload": {
    "users": [...],
    "config": {...}
  },
  "options": {
    "priority": 1,
    "tags": ["prod"]
  }
}
```

**Response:**
```json
{
  "execution_id": "484377543601029219",
  "status": "running",
  "created_at": "2025-11-06T12:00:00Z"
}
```

---

### GET `/api/executions/{id}`

**Get execution status**

**Response:**
```json
{
  "execution_id": "484377543601029219",
  "workflow_ref": "playbooks/user_processor",
  "status": "running",
  "context": {
    "workload": {...},
    "user_raw": {...}
  },
  "step_states": {
    "fetch_user": {
      "status": {"running": false, "done": true, "ok": true},
      "created_at": "2025-11-06T12:00:01Z",
      "updated_at": "2025-11-06T12:00:02Z"
    },
    "score_user": {
      "status": {"running": true, "done": false, "ok": null}
    }
  },
  "started_at": "2025-11-06T12:00:00Z",
  "finished_at": null
}
```

---

### POST `/api/executions/{id}/cancel`

**Cancel execution**

**Response:**
```json
{
  "execution_id": "484377543601029219",
  "status": "canceled",
  "canceled_at": "2025-11-06T12:05:00Z"
}
```

---

### GET `/api/executions/{id}/graph`

**Get execution graph visualization**

**Response:**
```json
{
  "execution_id": "484377543601029219",
  "nodes": [
    {
      "id": "start",
      "status": "done",
      "ok": true
    },
    {
      "id": "fetch_user",
      "status": "done",
      "ok": true
    },
    {
      "id": "score_user",
      "status": "running",
      "ok": null
    }
  ],
  "edges": [
    {"from": "start", "to": "fetch_user", "taken": true},
    {"from": "start", "to": "score_user", "taken": true},
    {"from": "fetch_user", "to": "join", "taken": false},
    {"from": "score_user", "to": "join", "taken": false}
  ]
}
```

---

### Optional: POST `/api/webhooks/sink-complete`

**Sink completion callback (if using async sinks)**

**Request:**
```json
{
  "execution_id": "484377543601029219",
  "step_id": "load_data",
  "sink_type": "s3",
  "ok": true
}
```

---

## 7.7 CLI (clictl.py) Targets

**Implementation:**

```python
# File: cli/clictl.py

import click
import requests
import json

SERVER_URL = "http://localhost:8083"

@click.group()
def cli():
    """NoETL CLI"""
    pass

# ===== Execution Management =====

@cli.group()
def exec():
    """Execution management"""
    pass

@exec.command("start")
@click.option("--workflow", required=True, help="Path to workflow YAML")
@click.option("--workload", required=True, help="Path to workload JSON")
def exec_start(workflow, workload):
    """Start new execution"""
    with open(workflow) as f:
        workflow_content = f.read()
    
    with open(workload) as f:
        workload_data = json.load(f)
    
    response = requests.post(f"{SERVER_URL}/api/executions", json={
        "workflow_ref": workflow,
        "workload": workload_data
    })
    
    result = response.json()
    click.echo(f"Execution started: {result['execution_id']}")

@exec.command("status")
@click.option("--id", required=True, help="Execution ID")
@click.option("--watch", is_flag=True, help="Watch status updates")
def exec_status(id, watch):
    """Get execution status"""
    if watch:
        import time
        while True:
            response = requests.get(f"{SERVER_URL}/api/executions/{id}")
            data = response.json()
            click.clear()
            click.echo(json.dumps(data, indent=2))
            
            if data["status"] in ["ok", "fail", "canceled"]:
                break
            
            time.sleep(2)
    else:
        response = requests.get(f"{SERVER_URL}/api/executions/{id}")
        click.echo(json.dumps(response.json(), indent=2))

@exec.command("cancel")
@click.option("--id", required=True, help="Execution ID")
def exec_cancel(id):
    """Cancel execution"""
    response = requests.post(f"{SERVER_URL}/api/executions/{id}/cancel")
    click.echo(json.dumps(response.json(), indent=2))

# ===== Worker Management =====

@cli.group()
def worker():
    """Worker management"""
    pass

@worker.command("start")
@click.option("--pool", default="default", help="Worker pool name")
@click.option("--concurrency", default=4, help="Number of concurrent tasks")
def worker_start(pool, concurrency):
    """Start worker (dev mode)"""
    from noetl.worker.main import WorkerPool
    
    worker_pool = WorkerPool(pool_name=pool, concurrency=concurrency)
    worker_pool.start()

@worker.command("drain")
@click.option("--pool", required=True, help="Worker pool name")
def worker_drain(pool):
    """Drain worker pool (wait for tasks to complete, then stop)"""
    # Signal workers to stop accepting new tasks
    # Wait for in-flight tasks to complete
    click.echo(f"Draining pool: {pool}")

# ===== Server Management =====

@cli.group()
def server():
    """Server management"""
    pass

@server.command("start")
def server_start():
    """Start server (dev mode)"""
    from noetl.server.main import app
    import uvicorn
    
    uvicorn.run(app, host="0.0.0.0", port=8083)

@server.command("health")
def server_health():
    """Check server health"""
    response = requests.get(f"{SERVER_URL}/health")
    click.echo(json.dumps(response.json(), indent=2))

if __name__ == "__main__":
    cli()
```

**Usage:**

```bash
# Start execution
python cli/clictl.py exec start --workflow playbooks/user_processor.yaml --workload payload.json

# Watch status
python cli/clictl.py exec status --id 484377543601029219 --watch

# Cancel execution
python cli/clictl.py exec cancel --id 484377543601029219

# Start worker
python cli/clictl.py worker start --pool default --concurrency 8

# Drain worker
python cli/clictl.py worker drain --pool default

# Start server (dev)
python cli/clictl.py server start

# Check health
python cli/clictl.py server health
```

---

## 7.8 Orchestrator Lifecycle (Pseudo-Code)

```python
# File: noetl/server/api/execution/orchestrator.py (complete)

def on_execution_start(exec):
    """Handle execution start"""
    enqueue_call(exec, step_id="start")

def on_step_called(exec, step_id):
    """Handle step call"""
    st = get_step_state(exec, step_id)
    
    # Idempotent: already done
    if st.status.done:
        return
    
    # Evaluate when gate
    if not eval_when(exec.context, step_id):
        park_call(exec, step_id)  # Remember pending call
        return
    
    # Dispatch
    dispatch(exec, step_id)

def dispatch(exec, step_id):
    """Dispatch step for execution"""
    step = graph[step_id]
    mark_start(exec.context, step_id, total=resolve_total(step.loop))
    
    if step.loop:
        # Loop execution
        for item in iter_collection(exec.context, step.loop):
            payload = render_tool_payload(exec.context, step.tool, element=item)
            enqueue_task(exec, step_id, payload)
    else:
        # Single execution
        payload = render_tool_payload(exec.context, step.tool)
        enqueue_task(exec, step_id, payload)

def on_task_result(res):
    """Handle task result from worker"""
    exec = load_execution(res.execution_id)
    
    # Integrate per-item or single result
    out = apply_pick(exec.context, res.step_id, res.this)
    apply_as_collect(exec.context, res.step_id, out)
    
    # Sink fan-out: enqueue sink tasks or server-side write
    enqueue_sinks(exec, res.step_id, out)
    
    # Loop accounting
    bump_counters(exec.context, res.step_id, ok=res.ok)
    
    # Check if step done
    if is_step_done(exec.context, res.step_id):
        finalize_step(exec, res.step_id)
        route_next(exec, res.step_id)

def finalize_step(exec, step_id):
    """Finalize step completion"""
    set_status(exec.context, step_id, done=True, ok=step_ok(exec.context, step_id))
    persist_step_state(exec)

def route_next(exec, step_id):
    """Route to next steps"""
    edges = graph[step_id].outgoing_edges
    
    for edge in edges:
        if edge.condition is None or eval_condition(exec.context, edge.condition):
            enqueue_call(exec, edge.target)
            break  # Take first matching edge
```

---

## 7.9 Concurrency & Parallel Loops

### Server Throttling

**Optional concurrency setting on loop:**

```yaml
loop:
  collection: "{{ items }}"
  element: item
  mode: parallel
  max_concurrency: 10  # Optional cap
```

**Implementation:**

```python
def _dispatch_loop(self, exec_state, step_id: str, loop_config: dict):
    """Dispatch loop items with throttling"""
    items = self._resolve_collection(exec_state.context, loop_config)
    max_concurrency = loop_config.get("max_concurrency")
    
    if max_concurrency:
        # Dispatch in batches
        for batch in chunks(items, max_concurrency):
            for item in batch:
                self._enqueue_task(exec_state, step_id, item)
            # Wait for batch to complete before next batch
    else:
        # Dispatch all
        for item in items:
            self._enqueue_task(exec_state, step_id, item)
```

---

### Worker Idempotency

**Sinks should be idempotent (e.g., UPSERT) to tolerate retries.**

**Example:**
```yaml
tool:
  result:
    sink:
      - postgres:
          table: results
          mode: upsert      # Idempotent
          key: id
          args:
            id: "{{ execution_id }}:{{ item.id }}"  # Unique key
```

---

### Visibility Timeouts

**If worker crashes, task returns to queue after timeout.**

**Implementation:**
```sql
-- Poll query returns tasks with expired leases
WHERE (lease_expires_at IS NULL OR lease_expires_at < NOW())
```

---

## 7.10 Backward Compatibility Switches

### Feature Flags

**Environment variables:**

```bash
# Allow legacy iteration aliases (iter, iterator, over, coll)
NOETL_ALLOW_LEGACY_ITER=true

# Execute sinks in worker (recommended) vs server-side
NOETL_EXECUTE_SINKS_IN_WORKER=true

# Strict validation (default: true)
NOETL_STRICT_DSL_VALIDATION=true
```

---

### Parser Compatibility

```python
class WorkflowParser:
    def parse(self, yaml_content: str, allow_legacy: bool = False) -> WorkflowGraph:
        """Parse workflow with optional legacy support"""
        data = yaml.safe_load(yaml_content)
        
        if allow_legacy:
            # Normalize legacy constructs
            data = self._normalize_legacy(data)
        
        # Validate DSL v2
        validate_schema(data)
        lint_workflow(data)
        
        return self._build_graph(data)
    
    def _normalize_legacy(self, data: dict) -> dict:
        """Convert legacy constructs to DSL v2"""
        for step in data.get("workflow", []):
            # iter/iterator/over/coll → loop
            for alias in ["iter", "iterator", "over", "coll"]:
                if alias in step:
                    step["loop"] = step.pop(alias)
            
            # save → tool.result.sink
            if "save" in step:
                step.setdefault("tool", {}).setdefault("result", {})["sink"] = [step.pop("save")]
        
        return data
```

---

### Rejection Policy

**Always reject `tool: iterator` (hard error):**

```python
def validate_no_iterator_tool(workflow: dict):
    """Ensure no tool: iterator anywhere"""
    for step in workflow.get("workflow", []):
        if step.get("tool") == "iterator":
            raise ValueError(f"Step '{step['step']}': tool: iterator is invalid in DSL v2. Use step.loop instead.")
```

---

## 7.11 Rollout Plan

### Phase 0 — Hidden Flags (Week 1-2)

**Goal:** Infrastructure preparation

**Actions:**
- [ ] Land validators, helpers, server/worker plumbing behind feature flags
- [ ] Add schema + lint checks to CI (non-blocking initially)
- [ ] Create migration documentation
- [ ] Train team on DSL v2

**Feature flags:**
```bash
NOETL_DSL_V2_ENABLED=false  # Default off
NOETL_STRICT_VALIDATION=false  # Warnings only
```

---

### Phase 1 — Examples + Tests (Week 3-4)

**Goal:** Internal validation

**Actions:**
- [ ] Convert `examples/` to DSL v2
- [ ] Convert test fixtures to DSL v2
- [ ] Add golden fixtures (valid) and negative fixtures (invalid)
- [ ] Turn CI blocking for examples/tests only
- [ ] Run end-to-end tests

**Feature flags:**
```bash
NOETL_DSL_V2_ENABLED=true  # For tests only
NOETL_STRICT_VALIDATION=true  # Fail on violations
```

---

### Phase 2 — Codemod Consumers (Week 5-6)

**Goal:** Migrate existing playbooks

**Actions:**
- [ ] Run codemod across repo playbooks
- [ ] Enable `--allow-legacy-iter` for two minor releases
- [ ] Monitor for issues
- [ ] Provide support channels

**Feature flags:**
```bash
NOETL_DSL_V2_ENABLED=true  # Production
NOETL_ALLOW_LEGACY_ITER=true  # Compatibility mode
```

**Communication:**
```
Subject: NoETL DSL v2 Migration - Action Required

We're migrating to DSL v2. Please:
1. Run: python scripts/codemod_dsl_v2.py your_playbook.yaml
2. Validate: make dsl.validate
3. Test: Run your workflows

Support: #noetl-migration
Docs: https://docs.noetl.io/migration
```

---

### Phase 3 — Default On (Week 7-8)

**Goal:** DSL v2 becomes standard

**Actions:**
- [ ] Make DSL v2 validator mandatory
- [ ] `--allow-legacy-iter` off by default (still available)
- [ ] Update documentation to show DSL v2 only
- [ ] Deprecation warnings for legacy constructs

**Feature flags:**
```bash
NOETL_DSL_V2_ENABLED=true
NOETL_ALLOW_LEGACY_ITER=false  # Default off, can override
NOETL_STRICT_VALIDATION=true
```

---

### Phase 4 — Deprecate Legacy (Week 9+)

**Goal:** Remove legacy support

**Actions:**
- [ ] Remove legacy aliases from parser
- [ ] Document migration EOL
- [ ] Final migration support window
- [ ] Remove compatibility code

**Timeline:**
- Announce deprecation: 3 months notice
- Final removal: Next major version

---

## 7.12 Acceptance Tests (End-to-End)

### Test 1: Fan-Out + Join

**Workflow:**
```yaml
- step: start
  next: [{ step: A }, { step: B }]

- step: A
  tool: { kind: python, spec: { code: "..." } }
  result: { as: a_result }
  next: [{ step: join }]

- step: B
  tool: { kind: python, spec: { code: "..." } }
  result: { as: b_result }
  next: [{ step: join }]

- step: join
  when: "{{ done('A') and ok('B') }}"
  tool: { kind: python, spec: { code: "..." } }
```

**Assertions:**
- [ ] A and B execute in parallel
- [ ] Join waits for both A and B to complete
- [ ] Join executes only if B succeeded
- [ ] Context contains `a_result` and `b_result`

---

### Test 2: Loop Parallel

**Workflow:**
```yaml
- step: proc_users
  loop: { collection: "{{ workload.users }}", element: user, mode: parallel }
  tool: { kind: playbook, spec: { path: "scorer" } }
  result:
    collect: { into: all_scores, mode: list }
  next: [{ step: summarize }]

- step: summarize
  when: "{{ loop_done('proc_users') }}"
  tool: { kind: workbook, spec: { name: summarize } }
```

**Assertions:**
- [ ] N users → N worker tasks
- [ ] All tasks execute in parallel
- [ ] `collect.into` list has length N
- [ ] Summarize step waits for `loop_done()`

---

### Test 3: Multi-Sink

**Workflow:**
```yaml
- step: process
  tool:
    kind: python
    spec: { code: "..." }
    result:
      sink:
        - postgres: { table: t1 }
        - s3: { bucket: b1 }
        - file: { path: "/tmp/out.json" }
```

**Assertions:**
- [ ] All three sinks receive data
- [ ] If one sink fails, step marked as failed
- [ ] Retry logic works for failed sinks

---

### Test 4: Idempotence

**Scenario:** Call same step twice

**Assertions:**
- [ ] Step executes once only
- [ ] Second call ignored (logged)
- [ ] Context not duplicated

---

### Test 5: Skip Gate

**Workflow:**
```yaml
- step: conditional
  when: "{{ false }}"
  tool: { kind: python, spec: { code: "..." } }
  next: [{ step: end }]
```

**Assertions:**
- [ ] Step never executes
- [ ] Step remains parked
- [ ] Can be re-evaluated later if `when` becomes true

---

## 7.13 Failure Policies (Choose & Document)

### Per-Step `ok` in Loop

**Option A: Strict (All or Nothing)**
```python
ok = (failed == 0)
```
- Step succeeds only if all loop items succeed
- Recommended for critical workflows

**Option B: Threshold-Based**
```yaml
loop:
  min_success_ratio: 0.8  # 80% must succeed
```
```python
ok = (succeeded / total >= min_success_ratio)
```
- Tolerates partial failures
- Add in future minor version

**Recommendation:** Start with Option A (strict). Add Option B later.

---

### Sinks

**Option A: Synchronous (Safer)**
- Step considered `done` only when all sinks complete
- Retries on sink failures
- Slower but guaranteed consistency

**Option B: Asynchronous (Faster)**
```yaml
result:
  sink:
    - postgres: { table: t, async: true }
```
- Sinks are best-effort
- Step routes immediately
- Sink failures logged but don't block

**Recommendation:** Start with Option A (synchronous). Add `async: true` flag later.

---

## 7.14 Security & Config

### Credential Resolution

**Pattern:**
```yaml
tool:
  kind: http
  spec:
    headers:
      Authorization: "{{ secrets.api_token }}"
```

**Implementation:**
```python
class SecretResolver:
    def resolve(self, context: dict) -> dict:
        """Resolve secrets in context"""
        # Fetch from secret manager
        secrets = self._fetch_secrets(context.get("workload", {}).get("secret_refs", []))
        context["secrets"] = secrets
        return context
    
    def mask_secrets(self, context: dict) -> dict:
        """Mask secrets in responses"""
        masked = context.copy()
        if "secrets" in masked:
            masked["secrets"] = {k: "***MASKED***" for k in masked["secrets"].keys()}
        return masked
```

---

### Security Rules

1. **Never surface secrets in `task_result` or persisted `context`**
2. **Mask known keys in API responses** (`/api/executions/{id}`)
3. **Evaluate secrets server-side only**
4. **Use separate secret store** (Vault, AWS Secrets Manager, Azure Key Vault)

---

## 7.15 Deliverables Checklist (To Close This Phase)

### Server

- [ ] Graph builder (parser → internal graph)
- [ ] Call/park/run orchestrator
- [ ] Loop dispatcher (sequential + parallel)
- [ ] Result integration (pick, as, collect)
- [ ] Routing engine (next edge evaluation)
- [ ] Jinja helpers wired
- [ ] APIs implemented (`POST /executions`, `GET /executions/{id}`, etc.)

### Worker

- [ ] Plugin registry
- [ ] Task execution
- [ ] Sink plugins
- [ ] Result emission
- [ ] Error handling and retries

### Schemas/Validators

- [ ] JSON Schema enforced at submit time
- [ ] Linter integrated into CI
- [ ] Legacy construct detection

### Helpers

- [ ] `done()`, `ok()`, `fail()`, `running()`, `loop_done()`
- [ ] `all_done()`, `any_done()`
- [ ] Wired into Jinja env for `when` and `next` evaluation

### APIs + CLI

- [ ] REST APIs documented
- [ ] CLI commands implemented
- [ ] API tests passing

### CI

- [ ] `make dsl.validate` in CI
- [ ] `make dsl.lint` in CI
- [ ] E2E tests green

### Docs

- [ ] README updated
- [ ] Examples reflect DSL v2
- [ ] Migration guide published
- [ ] Cheat sheet available

---

## Next Steps

This document provides the **complete implementation roadmap**. Recommended actions:

1. Review with engineering team
2. Estimate effort per deliverable
3. Create implementation tasks
4. Begin Phase 0 (hidden flags)
5. Parallel track: examples migration + testing

---

**Ready for implementation kickoff.**
