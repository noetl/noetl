---
sidebar_position: 5
title: DSL v2 Implementation Plan
description: Detailed implementation plan for NoETL DSL v2 refactoring
---

# DSL v2 Implementation Plan

This document outlines the implementation plan for refactoring NoETL to support the DSL v2 specification.

---

## 1. Current Architecture Overview

### 1.1 Key Components

```
┌─────────────────────────────────────────────────────────────────┐
│                          Server                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │   API       │  │ Orchestrator│  │  Event Store (Postgres) │ │
│  │  Endpoints  │  │             │  │  - execution            │ │
│  │             │  │  - routing  │  │  - command              │ │
│  └─────────────┘  │  - command  │  │  - event                │ │
│                   │    dispatch │  │  - context              │ │
│                   └─────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
                              │
                              │ NATS JetStream
                              │ (commands, events)
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                          Worker                                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────┐ │
│  │ Command     │  │ Case        │  │  Tool Executors         │ │
│  │ Processor   │  │ Evaluator   │  │  - python               │ │
│  │             │  │             │  │  - postgres             │ │
│  │ - claim     │  │ - when      │  │  - http                 │ │
│  │ - execute   │  │ - then      │  │  - shell                │ │
│  │ - complete  │  │ - next      │  │  - sink                 │ │
│  └─────────────┘  └─────────────┘  └─────────────────────────┘ │
└─────────────────────────────────────────────────────────────────┘
```

### 1.2 Current Flow

1. API receives execution request → creates `execution` record
2. Orchestrator generates `command` for first step
3. Worker claims command via NATS → executes tool → evaluates case → requests next
4. Server receives routing request → commits transition → generates next command
5. Repeat until workflow complete

### 1.3 Current Issues

1. **Case evaluation is not exclusive by default** - all matching conditions fire
2. **`next` doesn't act as break** - multiple branches can route
3. **No event sourcing** - limited audit trail
4. **Retry is at wrong level** - step vs tool
5. **Sessions in Postgres** - no TTL, no versioning

---

## 2. Implementation Phases

### Phase 1: Case Evaluation Refactoring (Week 1-2)

**Goal**: Implement proper exclusive/inclusive case modes with deterministic execution.

#### 2.1.1 Files to Modify

```
noetl/worker/
├── case_evaluator.py      # NEW: Dedicated case evaluation module
├── step_runtime.py        # NEW: Step execution coordinator
├── v2_worker_nats.py      # Modify: Use new case evaluator
└── executors/
    └── sink.py            # Modify: Support named tasks
```

#### 2.1.2 New `CaseEvaluator` Class

```python
@dataclass
class CaseEvaluation:
    """Result of case evaluation."""
    matched_branches: List[str]      # Branch IDs that matched
    execution_order: List[str]       # Order to execute
    case_mode: str                   # exclusive | inclusive
    trigger_event: str               # Event that triggered evaluation

@dataclass
class BranchResult:
    """Result of executing a branch."""
    branch_id: str
    actions_executed: List[str]
    routing_intent: Optional[RoutingIntent]
    suppressed: bool
    error: Optional[str]

class CaseEvaluator:
    """Evaluates case conditions according to spec."""

    def __init__(self, spec: StepSpec):
        self.case_mode = spec.case_mode  # exclusive | inclusive
        self.eval_mode = spec.eval_mode  # on_entry | on_event
        self.next_policy = spec.next_policy  # end_step | break_chain | defer
        self.branch_order = spec.branch_order  # source | priority

    async def evaluate(
        self,
        case_blocks: List[CaseBlock],
        context: Dict[str, Any],
        event: Event
    ) -> CaseEvaluation:
        """Evaluate all case conditions and return matched branches."""
        matched = []

        for i, case_block in enumerate(case_blocks):
            condition = case_block.when
            result = await self._eval_condition(condition, context, event)

            if result:
                matched.append(f"case_{i}")

                # Exclusive mode: stop at first match
                if self.case_mode == "exclusive":
                    break

        # Determine execution order
        if self.branch_order == "priority":
            order = self._sort_by_priority(matched, case_blocks)
        else:
            order = matched  # Source order

        return CaseEvaluation(
            matched_branches=matched,
            execution_order=order,
            case_mode=self.case_mode,
            trigger_event=event.name
        )

    async def execute_branches(
        self,
        evaluation: CaseEvaluation,
        case_blocks: List[CaseBlock],
        context: Dict[str, Any],
        executor: ToolExecutor
    ) -> List[BranchResult]:
        """Execute matched branches in order, respecting next_policy."""
        results = []
        routing_intent = None

        for branch_id in evaluation.execution_order:
            # Check if we should stop (end_step policy with prior routing)
            if routing_intent and self.next_policy == "end_step":
                results.append(BranchResult(
                    branch_id=branch_id,
                    actions_executed=[],
                    routing_intent=None,
                    suppressed=True,
                    error=None
                ))
                continue

            # Execute the branch
            result = await self._execute_branch(
                branch_id, case_blocks, context, executor
            )
            results.append(result)

            # Capture first routing intent
            if result.routing_intent and not routing_intent:
                routing_intent = result.routing_intent

        return results
```

#### 2.1.3 New `StepRuntime` Class

```python
class StepRuntime:
    """Manages the lifecycle of a step execution."""

    def __init__(
        self,
        step_run_id: str,
        step_config: StepConfig,
        context: Dict[str, Any]
    ):
        self.step_run_id = step_run_id
        self.config = step_config
        self.context = context
        self.spec = StepSpec.from_config(step_config.get("spec", {}))
        self.case_evaluator = CaseEvaluator(self.spec)
        self.events: List[Event] = []

    async def run(self, entry_event: Event) -> StepResult:
        """Run the step to completion."""

        # Emit step.started
        await self._emit_event("step.started", {
            "step_name": self.config.name,
            "spec": asdict(self.spec)
        })

        # Execute entry tool if present
        if self.config.tool:
            tool_result = await self._execute_entry_tool()
            self.context["result"] = tool_result

        # Evaluate case conditions
        if self.config.case:
            evaluation = await self.case_evaluator.evaluate(
                self.config.case,
                self.context,
                entry_event
            )

            # Emit case.evaluated
            await self._emit_event("case.evaluated", {
                "matched": evaluation.matched_branches,
                "order": evaluation.execution_order,
                "case_mode": evaluation.case_mode
            })

            # Execute branches
            branch_results = await self.case_evaluator.execute_branches(
                evaluation,
                self.config.case,
                self.context,
                self.tool_executor
            )

            # Find routing intent
            routing = self._find_routing(branch_results)

            if routing:
                # Emit next.evaluated
                await self._emit_event("next.evaluated", {
                    "selected": routing.targets,
                    "policy": self.spec.next_policy,
                    "winner_branch": routing.source_branch,
                    "suppressed_branches": [
                        r.branch_id for r in branch_results if r.suppressed
                    ]
                })

        # Emit step.finished
        await self._emit_event("step.finished", {
            "status": "completed",
            "routing": routing
        })

        return StepResult(routing=routing, events=self.events)
```

### Phase 2: Event Sourcing (Week 2-3)

**Goal**: Implement comprehensive event logging for audit and replay.

#### 2.2.1 New Event Schema

```python
@dataclass
class EventEnvelope:
    """Standard event envelope for all events."""
    event_id: str
    event_type: str
    timestamp: datetime

    # Correlation IDs
    execution_id: str
    workflow_run_id: str
    step_run_id: Optional[str]
    tool_run_id: Optional[str]

    # Entity info
    entity_type: str  # workflow | step | tool | case | next
    entity_id: str
    parent_id: Optional[str]

    # Action tracking
    action_id: Optional[str]  # Stable idempotency key
    attempt: int = 1
    iteration: int = 0
    page: int = 0

    # Payload
    payload: Dict[str, Any] = field(default_factory=dict)
```

#### 2.2.2 Event Store Interface

```python
class EventStore(Protocol):
    """Interface for event persistence."""

    async def append(self, event: EventEnvelope) -> None:
        """Append event to store."""
        ...

    async def get_by_execution(
        self,
        execution_id: str,
        event_types: Optional[List[str]] = None
    ) -> List[EventEnvelope]:
        """Get all events for an execution."""
        ...

    async def get_by_step(
        self,
        step_run_id: str,
        event_types: Optional[List[str]] = None
    ) -> List[EventEnvelope]:
        """Get all events for a step run."""
        ...
```

#### 2.2.3 Event Types

```python
class EventTypes:
    # Workflow layer
    PLAYBOOK_EXECUTION_REQUESTED = "playbook.execution.requested"
    PLAYBOOK_REQUEST_EVALUATED = "playbook.request.evaluated"
    PLAYBOOK_STARTED = "playbook.started"
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_FINISHED = "workflow.finished"
    PLAYBOOK_PROCESSED = "playbook.processed"

    # Step layer
    STEP_STARTED = "step.started"
    STEP_PAUSED = "step.paused"
    STEP_RESUMED = "step.resumed"
    STEP_FINISHED = "step.finished"

    # Tool layer
    TOOL_STARTED = "tool.started"
    TOOL_PROCESSED = "tool.processed"

    # Control layer
    CASE_STARTED = "case.started"
    CASE_EVALUATED = "case.evaluated"
    NEXT_EVALUATED = "next.evaluated"
    LOOP_STARTED = "loop.started"
    LOOP_ITERATION_STARTED = "loop.iteration.started"
    LOOP_ITERATION_FINISHED = "loop.iteration.finished"
    LOOP_FINISHED = "loop.finished"
    RETRY_STARTED = "retry.started"
    RETRY_PROCESSED = "retry.processed"
    SINK_STARTED = "sink.started"
    SINK_PROCESSED = "sink.processed"
```

### Phase 3: NATS K/V Session Store (Week 3)

**Goal**: Replace PostgreSQL sessions with NATS K/V for TTL and performance.

#### 2.3.1 Session Store Interface

```python
@dataclass
class Session:
    """Session data structure."""
    session_id: int
    session_token: str
    user_id: int
    email: str
    display_name: str
    roles: List[str]
    created_at: datetime
    expires_at: datetime
    last_activity_at: datetime
    client_ip: str
    auth0_id: str
    revision: int = 0  # NATS K/V revision for optimistic locking

class NatsSessionStore:
    """Session store using NATS K/V."""

    BUCKET_NAME = "noetl_sessions"
    KEY_PREFIX = "session."

    def __init__(self, nats_client: Client, ttl_seconds: int = 86400):
        self.nc = nats_client
        self.ttl = ttl_seconds
        self.kv: Optional[KeyValue] = None

    async def initialize(self):
        """Create or get the K/V bucket."""
        js = self.nc.jetstream()
        try:
            self.kv = await js.key_value(self.BUCKET_NAME)
        except Exception:
            self.kv = await js.create_key_value(
                bucket=self.BUCKET_NAME,
                ttl=self.ttl,
                history=5,  # Keep 5 versions for audit
                storage="memory"  # Fast access
            )

    async def create(self, session: Session) -> Session:
        """Create a new session."""
        key = f"{self.KEY_PREFIX}{session.session_token}"
        value = json.dumps(asdict(session), default=str)

        entry = await self.kv.put(key, value.encode())
        session.revision = entry.revision
        return session

    async def get(self, session_token: str) -> Optional[Session]:
        """Get session by token."""
        key = f"{self.KEY_PREFIX}{session_token}"
        try:
            entry = await self.kv.get(key)
            if entry and entry.value:
                data = json.loads(entry.value.decode())
                data["revision"] = entry.revision
                return Session(**data)
        except KeyNotFoundError:
            return None
        return None

    async def update_activity(self, session_token: str) -> bool:
        """Update last activity timestamp (touch TTL)."""
        key = f"{self.KEY_PREFIX}{session_token}"
        try:
            entry = await self.kv.get(key)
            if not entry:
                return False

            data = json.loads(entry.value.decode())
            data["last_activity_at"] = datetime.utcnow().isoformat()

            await self.kv.update(
                key,
                json.dumps(data, default=str).encode(),
                entry.revision
            )
            return True
        except Exception:
            return False

    async def delete(self, session_token: str) -> bool:
        """Delete/invalidate session."""
        key = f"{self.KEY_PREFIX}{session_token}"
        try:
            await self.kv.delete(key)
            return True
        except Exception:
            return False

    async def get_history(self, session_token: str) -> List[Session]:
        """Get session history (all versions)."""
        key = f"{self.KEY_PREFIX}{session_token}"
        history = await self.kv.history(key)
        sessions = []
        for entry in history:
            if entry.value:
                data = json.loads(entry.value.decode())
                data["revision"] = entry.revision
                sessions.append(Session(**data))
        return sessions
```

### Phase 4: Retry Refactoring (Week 4)

**Goal**: Move retry to tool level with proper inheritance.

#### 2.4.1 Retry Policy

```python
@dataclass
class RetryPolicy:
    """Retry configuration."""
    scope: str = "tool"  # tool | chain
    max_attempts: int = 3
    backoff: BackoffConfig = field(default_factory=BackoffConfig)
    on: List[str] = field(default_factory=lambda: ["error"])  # error | status_code | exception

@dataclass
class BackoffConfig:
    """Backoff configuration."""
    type: str = "exponential"  # exponential | linear | fixed
    delay_seconds: float = 1.0
    max_delay_seconds: float = 60.0
    jitter: bool = True

class RetryExecutor:
    """Wraps tool execution with retry logic."""

    def __init__(self, policy: RetryPolicy, tool_executor: ToolExecutor):
        self.policy = policy
        self.tool_executor = tool_executor

    async def execute(
        self,
        tool_config: Dict[str, Any],
        context: Dict[str, Any],
        action_id: str
    ) -> ToolResult:
        """Execute tool with retry."""
        last_error = None

        for attempt in range(1, self.policy.max_attempts + 1):
            # Emit retry.started if not first attempt
            if attempt > 1:
                await self._emit_event("retry.started", {
                    "action_id": action_id,
                    "attempt": attempt,
                    "reason": str(last_error)
                })

            try:
                # Emit tool.started
                await self._emit_event("tool.started", {
                    "action_id": action_id,
                    "attempt": attempt,
                    "tool_kind": tool_config.get("kind")
                })

                result = await self.tool_executor.execute(tool_config, context)

                # Emit tool.processed
                await self._emit_event("tool.processed", {
                    "action_id": action_id,
                    "attempt": attempt,
                    "status": "success"
                })

                return result

            except Exception as e:
                last_error = e

                # Emit tool.processed with error
                await self._emit_event("tool.processed", {
                    "action_id": action_id,
                    "attempt": attempt,
                    "status": "error",
                    "error": str(e)
                })

                # Check if we should retry
                if attempt < self.policy.max_attempts:
                    delay = self._calculate_delay(attempt)
                    await asyncio.sleep(delay)
                else:
                    # Emit retry.processed (exhausted)
                    await self._emit_event("retry.processed", {
                        "action_id": action_id,
                        "total_attempts": attempt,
                        "status": "exhausted",
                        "final_error": str(e)
                    })
                    raise

        raise last_error
```

---

## 3. Database Schema Changes

### 3.1 New Tables

```sql
-- Event store table (append-only)
CREATE TABLE noetl.event_log (
    event_id BIGINT PRIMARY KEY,
    event_type VARCHAR(100) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Correlation IDs
    execution_id BIGINT NOT NULL,
    workflow_run_id VARCHAR(50),
    step_run_id VARCHAR(50),
    tool_run_id VARCHAR(50),

    -- Entity info
    entity_type VARCHAR(50) NOT NULL,
    entity_id VARCHAR(100) NOT NULL,
    parent_id VARCHAR(100),

    -- Action tracking
    action_id VARCHAR(100),
    attempt INT DEFAULT 1,
    iteration INT DEFAULT 0,
    page INT DEFAULT 0,

    -- Payload (JSONB for efficient querying)
    payload JSONB NOT NULL DEFAULT '{}',

    -- Indexes
    CONSTRAINT fk_execution FOREIGN KEY (execution_id)
        REFERENCES noetl.execution(execution_id)
);

CREATE INDEX idx_event_log_execution ON noetl.event_log(execution_id);
CREATE INDEX idx_event_log_step ON noetl.event_log(step_run_id);
CREATE INDEX idx_event_log_type ON noetl.event_log(event_type);
CREATE INDEX idx_event_log_timestamp ON noetl.event_log(timestamp);
```

### 3.2 Tables to Deprecate

```sql
-- These tables will be replaced by event_log + NATS K/V
-- auth.sessions -> NATS K/V (noetl_sessions bucket)
-- noetl.command (partial) -> events drive command generation
```

---

## 4. API Changes

### 4.1 New Endpoints

```
GET  /api/executions/{execution_id}/events
     Query params: event_type, step_run_id, from_timestamp, limit

GET  /api/executions/{execution_id}/steps/{step_run_id}/events
     Get all events for a specific step run

GET  /api/sessions/{session_token}/history
     Get session version history from NATS K/V
```

### 4.2 Modified Endpoints

```
POST /api/executions
     Response now includes workflow_run_id

GET  /api/executions/{execution_id}
     Response includes event summary and step_run_ids
```

---

## 5. Testing Strategy

### 5.1 Unit Tests

- `test_case_evaluator.py` - Case mode, branch ordering
- `test_step_runtime.py` - Step lifecycle, event emission
- `test_retry_executor.py` - Retry logic, backoff
- `test_nats_session_store.py` - NATS K/V operations

### 5.2 Integration Tests

- `test_exclusive_case_mode.py` - Only first match fires
- `test_inclusive_case_mode.py` - All matches fire, next stops
- `test_event_sourcing.py` - Events emitted correctly
- `test_session_ttl.py` - Session expiration

### 5.3 Playbook Tests

Update all auth playbooks to use new DSL:
- `auth0_login.yaml`
- `auth0_validate_session.yaml`
- `check_playbook_access.yaml`

---

## 6. Migration Plan

### 6.1 Backward Compatibility

- Keep old `next:` syntax working (translate to `next: { to: [...] }`)
- Keep `sink:` as alias for named task
- Default `case_mode: exclusive` matches current behavior... mostly

### 6.2 Phased Rollout

1. **Week 1-2**: Deploy case evaluator changes (feature flagged)
2. **Week 3**: Deploy event sourcing (append-only, non-breaking)
3. **Week 3**: Deploy NATS K/V session store (parallel write)
4. **Week 4**: Deploy retry refactoring
5. **Week 5**: Cut over sessions to NATS K/V only
6. **Week 6**: Remove deprecated code paths

---

## 7. Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Case mode change breaks existing playbooks | High | Default to exclusive, test all playbooks |
| Event volume overwhelms storage | Medium | Add event pruning, use partitioning |
| NATS K/V unavailable | High | Fallback to Postgres sessions |
| Retry loops | Medium | Hard limit on max_attempts, circuit breaker |

---

## 8. Success Metrics

- All auth playbooks work correctly with new case evaluator
- Event log captures complete workflow audit trail
- Session validation < 5ms (NATS K/V)
- No duplicate callbacks from inclusive mode
- Retry logic executes exactly N times as configured
