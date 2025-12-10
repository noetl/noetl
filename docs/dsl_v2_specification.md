# NoETL DSL v2 - Event-Driven Execution Model

**Version:** 2.0  
**Status:** Clean implementation, NO backward compatibility with v1

## Overview

NoETL DSL v2 is a complete redesign with clean event-driven architecture:

- **Step-level control:** `loop` and `case` belong to the step, not the tool
- **Tool config:** All execution fields live under `tool.kind`
- **Event-driven engine:** Server evaluates DSL and writes to queue; workers only execute and emit events

## Architecture

```
┌─────────────┐
│   Worker    │──── execute command ────▶ emit events ────┐
└─────────────┘                                            │
                                                           ▼
┌─────────────────────────────────────────────────────────────┐
│                         Server                              │
│  ┌──────────────┐    ┌────────────────┐    ┌───────────┐ │
│  │ Event API    │───▶│ Control Flow   │───▶│   Queue   │ │
│  │ /api/v2/     │    │ Engine         │    │   Table   │ │
│  │ events       │    │ (handle_event) │    │  (write)  │ │
│  └──────────────┘    └────────────────┘    └───────────┘ │
└─────────────────────────────────────────────────────────────┘
                                   │
                                   ▼
                           ┌─────────────┐
                           │   Worker    │──── polls queue
                           └─────────────┘
```

**Key Principles:**
- Server is the ONLY writer to queue table
- Workers NEVER directly update queue
- All control flow decisions happen in the engine via events

## DSL Structure

### Complete Playbook Schema

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: playbook_name
  path: catalog/path
  version: "2.0"

workload:                   # Global variables (optional)
  variable: value

workbook:                   # Named reusable tasks (optional)
  - name: task_name
    tool:
      kind: python
      code: |
        def main(input_data):
            return result

workflow:                   # Required, must have 'start' step
  - step: start             # Required entry point
    desc: description       # Optional
    args:                   # Optional input arguments
      key: "{{ value }}"
    loop:                   # Optional step-level loop
      in: "{{ collection }}"
      iterator: item
    tool:                   # Required: tool configuration
      kind: http|postgres|python|workbook|...
      # kind-specific fields
    case:                   # Optional conditional rules
      - when: "{{ condition }}"
        then:
          # action block
    next: next_step         # Optional unconditional next step(s)
```

## Tool Configuration

Every step MUST have `tool.kind` that identifies the tool type.

### HTTP Tool

```yaml
tool:
  kind: http
  method: GET|POST|PUT|DELETE
  endpoint: https://api.example.com/data
  headers:
    X-API-Key: "{{ secret.api_key }}"
  params:
    page: 1
    limit: 100
  data:                     # Request body for POST/PUT
    field: value
```

### Postgres Tool

```yaml
tool:
  kind: postgres
  auth: "{{ workload.pg_auth }}"
  command: |
    INSERT INTO table (col1, col2)
    VALUES ({{ value }}, '{{ text }}');
```

### Python Tool

```yaml
tool:
  kind: python
  code: |
    def main(city, threshold):
        temp = city.get("temperature", 0)
        alert = temp > threshold
        return {"city": city["name"], "alert": alert}
```

### Workbook Tool

```yaml
tool:
  kind: workbook
  task: evaluate_weather_directly  # References workbook task
  with:
    city: "{{ args.city }}"
    threshold: "{{ args.threshold }}"
```

## Step-Level Loop

Loop controls "how many times this node runs":

```yaml
- step: fetch_all_cities
  loop:
    in: "{{ workload.cities }}"
    iterator: city
  tool:
    kind: http
    method: GET
    endpoint: "{{ workload.api_url }}/weather/{{ city.id }}"
```

The engine maintains loop state (current item, index) in execution context.

## Case/When/Then - Event-Based Rules

Replace old conditional logic with event-driven rules:

### Events

The engine emits events during execution:
- `step.enter` - Before step starts
- `call.done` - After tool call completes
- `step.exit` - When step is done

### Case Structure

```yaml
case:
  - when: "{{ jinja2_expression }}"
    then:
      # actions to execute
```

### Available Actions in `then:`

#### 1. call - Re-invoke tool with overrides

```yaml
then:
  call:
    params:
      page: "{{ (response.data.page | int) + 1 }}"
```

#### 2. retry - Retry failed calls

```yaml
then:
  retry:
    max_attempts: 3
    backoff_multiplier: 2.0
    initial_delay: 0.5
```

#### 3. collect - Aggregate data

```yaml
then:
  collect:
    from: response.data.items
    into: pages
    mode: append|extend|replace
```

#### 4. set - Mutate context

```yaml
then:
  set:
    ctx:
      counter: "{{ ctx.counter + 1 }}"
    flags:
      has_error: true
```

#### 5. result - Set step result

```yaml
then:
  result:
    from: pages
```

#### 6. next - Conditional transitions

```yaml
then:
  next:
    - step: validate_results
      args:
        pages: "{{ pages }}"
        total: "{{ ctx.total_records }}"
```

#### 7. sink - Write to external storage

```yaml
then:
  sink:
    tool:
      kind: postgres
      auth: "{{ workload.pg_auth }}"
      command: |
        INSERT INTO events (data) VALUES ($json${{ result | tojson }}$json$::jsonb);
    args:
      value: "{{ result.value }}"
```

#### 8. fail / skip - Control flow

```yaml
then:
  fail:
    message: "Validation failed"
    fail_workflow: true

then:
  skip:
    reason: "Data already processed"
```

## Common Patterns

### Pattern 1: HTTP Pagination

```yaml
- step: fetch_all_pages
  tool:
    kind: http
    method: GET
    endpoint: https://api.example.com/data
    params:
      page: 1
      pageSize: 100
  case:
    # Initialize collection
    - when: "{{ event.name == 'step.enter' }}"
      then:
        set:
          ctx:
            pages: []
    
    # Retry on server errors
    - when: >-
        {{ event.name == 'call.done'
           and error is defined
           and error.status in [500, 502, 503] }}
      then:
        retry:
          max_attempts: 3
          backoff_multiplier: 2.0
          initial_delay: 0.5
    
    # Paginate if more data available
    - when: >-
        {{ event.name == 'call.done'
           and response is defined
           and response.data.paging.hasMore }}
      then:
        collect:
          from: response.data.data
          into: pages
          mode: append
        call:
          params:
            page: "{{ (response.data.paging.page | int) + 1 }}"
    
    # Final page
    - when: >-
        {{ event.name == 'call.done'
           and response is defined
           and not response.data.paging.hasMore }}
      then:
        collect:
          from: response.data.data
          into: pages
          mode: append
        result:
          from: pages
        next:
          - step: process_data
            args:
              pages: "{{ pages }}"
```

### Pattern 2: Loop with Conditional Actions

```yaml
- step: process_cities
  loop:
    in: "{{ workload.cities }}"
    iterator: city
  tool:
    kind: http
    method: GET
    endpoint: "{{ workload.api_url }}/weather/{{ city.id }}"
  case:
    # Alert if temperature exceeds threshold
    - when: >-
        {{ event.name == 'call.done'
           and response.data.temperature > workload.threshold }}
      then:
        collect:
          from: response.data
          into: alerts
          mode: append
        next:
          - step: send_alert
            args:
              city: "{{ city.name }}"
              temp: "{{ response.data.temperature }}"
    
    # Just collect if below threshold
    - when: >-
        {{ event.name == 'call.done'
           and response.data.temperature <= workload.threshold }}
      then:
        collect:
          from: response.data
          into: normal_readings
          mode: append
```

### Pattern 3: Retry with Exponential Backoff

```yaml
- step: fetch_with_retry
  tool:
    kind: http
    method: GET
    endpoint: https://unreliable-api.example.com/data
  case:
    - when: >-
        {{ event.name == 'call.done'
           and error is defined
           and error.status in [429, 500, 502, 503, 504] }}
      then:
        retry:
          max_attempts: 5
          backoff_multiplier: 2.0
          initial_delay: 1.0
```

## Step Next vs Next Action

### Structural Next (Unconditional)

```yaml
- step: step_a
  tool:
    kind: python
    code: "def main(): return {}"
  next: step_b              # Simple unconditional transition
  
# OR multiple next steps
  next:
    - step_b
    - step_c
```

### Conditional Next (via case)

```yaml
- step: step_a
  tool:
    kind: python
    code: "def main(flag): return {'flag': flag}"
  case:
    - when: "{{ event.name == 'step.exit' and result.flag }}"
      then:
        next:
          - step: path_true
            args:
              from: step_a
    
    - when: "{{ event.name == 'step.exit' and not result.flag }}"
      then:
        next:
          - step: path_false
            args:
              from: step_a
```

**Rules:**
- Structural `next` is unconditional and simple
- Conditional transitions use `case.then.next`
- Use `args` (NOT `with`) for cross-step data passing

## Jinja2 Context

Templates have access to:

- `{{ workload.field }}` - Global workflow variables
- `{{ args.field }}` - Step input arguments
- `{{ step_name.field }}` - Previous step results (auto-normalized by server)
- `{{ ctx.variable }}` - User-defined context variables
- `{{ loop.iterator }}` - Loop state
- `{{ event.name }}` - Current event name
- `{{ response.* }}` - HTTP/tool response (in call.done)
- `{{ error.* }}` - Error object (in call.done on failure)
- `{{ result.* }}` - Step result (in step.exit)
- `{{ execution_id }}` - Current execution identifier

## Migration from v1

### Step Type → Tool Kind

**v1:**
```yaml
- step: fetch_data
  type: http
  method: GET
  endpoint: https://api.example.com
```

**v2:**
```yaml
- step: fetch_data
  tool:
    kind: http
    method: GET
    endpoint: https://api.example.com
```

### Next When/Then → Case

**v1:**
```yaml
next:
  - when: "{{ flag }}"
    then:
      - step: path_a
  - else:
      - step: path_b
```

**v2:**
```yaml
case:
  - when: "{{ event.name == 'step.exit' and result.flag }}"
    then:
      next:
        - step: path_a
  - when: "{{ event.name == 'step.exit' and not result.flag }}"
    then:
      next:
        - step: path_b
```

### Cross-Step With → Args

**v1:**
```yaml
next:
  - step: next_step
    with:
      value: "{{ result.value }}"
```

**v2:**
```yaml
case:
  - when: "{{ event.name == 'step.exit' }}"
    then:
      next:
        - step: next_step
          args:
            value: "{{ result.value }}"
```

## Implementation Details

### Server-Side

1. **Event API** (`/api/v2/events`): Receives events from workers
2. **Control Flow Engine**: Evaluates DSL rules and generates commands
3. **Queue Table Writer**: ONLY place where queue is written

### Worker-Side

1. **Queue Poller**: Polls for available commands
2. **Command Executor**: Executes based on `tool.kind`
3. **Event Emitter**: Sends events back to server

**Workers NEVER:**
- Directly update queue table
- Make control flow decisions
- Evaluate case/when/then logic

## Examples

See `tests/fixtures/playbooks/examples/`:
- `amadeus_ai_api_v2.yaml` - Complex API integration with OAuth
- `http_pagination_v2.yaml` - HTTP pagination with retry
- `weather_loop_v2.yaml` - Loop with conditional actions and workbook

## Testing

```bash
# Run v2 unit tests
pytest tests/unit/dsl/v2/

# Test parser
pytest tests/unit/dsl/v2/test_models_parser.py

# Test engine
pytest tests/unit/dsl/v2/test_engine.py
```

## API Usage

```python
# Parse playbook
from noetl.core.dsl.v2.parser import parse_playbook_file

playbook = parse_playbook_file("path/to/playbook.yaml")

# Create engine
from noetl.core.dsl.v2.engine import (
    ControlFlowEngine, PlaybookRepo, StateStore
)

repo = PlaybookRepo()
store = StateStore()
engine = ControlFlowEngine(repo, store)

repo.register(playbook)

# Handle events
from noetl.core.dsl.v2.models import Event, EventName

event = Event(
    execution_id="exec-123",
    name=EventName.WORKFLOW_START.value,
    payload={}
)

commands = engine.handle_event(event)
# Insert commands into queue table
```

## Code Structure

```
noetl/core/dsl/v2/
├── __init__.py          # Exports
├── models.py            # Pydantic models (Playbook, Step, Event, Command)
├── parser.py            # YAML parser
└── engine.py            # Control flow engine

noetl/server/api/
└── events_v2.py         # Event API endpoints

noetl/worker/
└── executor_v2.py       # Worker command executor

tests/
├── unit/dsl/v2/
│   ├── test_models_parser.py
│   └── test_engine.py
└── fixtures/playbooks/examples/
    ├── amadeus_ai_api_v2.yaml
    ├── http_pagination_v2.yaml
    └── weather_loop_v2.yaml
```

## Design Decisions

1. **NO Backward Compatibility**: Clean break from v1 for better architecture
2. **Event-Driven**: All control flow decisions based on events
3. **Server-Centric**: Server owns queue table and orchestration logic
4. **Step-Level Control**: Loop and case belong to steps, not tools
5. **Explicit Tool Config**: `tool.kind` with kind-specific fields under `tool`
6. **Unified Actions**: Single `then` vocabulary (call, retry, collect, etc.)

## Future Enhancements

- [ ] Loop modes: sequential, async, parallel
- [ ] Advanced retry strategies: circuit breaker, jitter
- [ ] Conditional breakpoints for debugging
- [ ] Step timeouts and deadlines
- [ ] Dynamic priority adjustment
- [ ] Workflow composition (sub-playbooks)
