# Unified Retry, Sink, and Loop Design

> **Status**: Design finalized with when/then pattern (not on_error/on_success)  
> **Decision**: Unified when/then list format for consistency with next: routing  
> **Evaluation**: First-match (short-circuit) semantics  
> **Implementation**: See `unified_retry_sink_implementation_plan.md`

## Problem Statement

Current design has three fundamental issues:

1. **Loop Result Reporting**: Loop handler reports step results for each element, creating noise and unclear final state. Instead, should accumulate results using `retry[].then.collect` and emit single aggregated result after loop completes.
2. **Sink Placement**: Need consistent sink behavior at step/tool level and retry policy level (`retry[].then.sink`)
3. **Retry Conditionals**: Using `on_error`/`on_success` creates two different conditional systems when we already have `when`/`then` pattern used in `next` attribute

## Current Architecture Understanding

### Step vs Tool
- **`step`**: Transition wrapper containing metadata (step name, desc, next routing)
- **`tool`**: Actual action type (http, postgres, python, etc.) - same level as step attributes
- Example:
  ```yaml
  - step: fetch_data      # Wrapper with routing
    tool: http            # Action type (same level as step)
    url: "{{ api_url }}"
  ```

### Loop Attribute
- **`loop: {}`**: Attribute that says "execute this `tool` for each element in collection OR while expression is true"
- Loop does NOT change the tool - it wraps execution behavior
- Example:
  ```yaml
  - step: fetch_all
    tool: http            # The action to repeat
    loop:                 # Repeat configuration
      collection: "{{ items }}"
      element: item
      mode: sequential
  ```

### Sink Levels
Current sink can be placed at:
1. **Step/Tool level**: `sink:` at same level as `tool:` attribute
2. **Retry policy level**: `retry[].then.sink` (within when/then policy)

### Current Result Reporting Problem
Loop currently emits `step_result` event for EACH iteration. This is wrong because:
- Creates event noise (N results for N iterations)
- Unclear what the final step result is
- Should use `retry[].then.collect` to accumulate data
- Should emit single aggregated result after loop completes

## Unified Solution

### 1. Unify Retry with When/Then Pattern

**Decision**: Replace `on_error`/`on_success` with unified `when`/`then` pattern for consistency across entire DSL.

**Problem with current design**:
- Two different conditional systems: `next:` uses `when`/`then`, `retry:` uses `on_error`/`on_success`
- Harder to learn and maintain
- Less flexible for complex retry scenarios

**New unified structure**:

```yaml
retry:
  - when: "{{ error.status in [500, 502, 503] }}"
    then:
      max_attempts: 3
      backoff_multiplier: 2.0
      initial_delay: 0.5
      
  - when: "{{ response.paging.hasMore == true }}"
    then:
      max_attempts: 100
      next_call:
        params:
          page: "{{ (response.paging.page | int) + 1 }}"
      collect:
        strategy: append
        path: data
        into: pages
```

**Benefits**:
- **Single conditional pattern** throughout entire DSL (next, retry, future features)
- **Consistency** - Only one way to express conditions
- **Flexibility** - Multiple retry policies with different conditions evaluated in order
- **Composability** - Easy to add new retry scenarios
- **Simpler learning curve** - One pattern to understand

### 2. Distinguishing Error vs Success Conditions

**Current Problem**: Loop handler emits `step_result` for each iteration

**Solution**: Use `retry[].then.collect` for accumulation, emit single result after loop completes

```yaml
- step: fetch_medications
  tool: http
  url: "{{ api_url }}/patients/{{ patient_id }}/medications"
  loop:
    collection: "{{ patient_ids }}"
    element: patient_id
    mode: sequential
  retry:
    - when: "{{ error.status >= 500 }}"
      then:
        max_attempts: 3
        backoff_multiplier: 2.0
    
    - when: "{{ response.paging.hasMore }}"
      then:
        max_attempts: 100
        next_call:
          params:
            page: "{{ response.paging.page + 1 }}"
        collect:            # CRITICAL: Accumulates pagination results
          strategy: append
          path: data
          into: pages
```

**Loop Execution Flow**:
1. Loop handler starts iteration for patient_id[0]
2. Worker executes HTTP call (page 1)
3. First retry policy with `when: "{{ error.status >= 500 }}"` checked → false (no error)
4. Second retry policy with `when: "{{ response.paging.hasMore }}"` checked → true
5. **First matching policy executes** → pagination continues
6. Worker executes HTTP call (page 2) with updated params
7. Results accumulated via `collect.strategy: append` → `pages` variable
8. When second policy's `when` → false, iteration completes
9. Worker emits `iteration_completed` with accumulated result (all pages)
10. Repeat for patient_id[1], patient_id[2], etc.
11. **After ALL iterations complete**: Emit single `step_result` with array of all iteration results

**Important**: Order matters! If pagination policy came before error policy, rate limiting (429) wouldn't be handled with appropriate delays.

**Correct ordering**:
```yaml
retry:
  - when: "{{ error.status == 429 }}"     # Most specific first
    then: { max_attempts: 10, initial_delay: 60 }
  
  - when: "{{ error.status >= 500 }}"     # General errors
    then: { max_attempts: 3, backoff_multiplier: 2.0 }
  
  - when: "{{ response.paging.hasMore }}" # Success continuation
    then: { max_attempts: 100, next_call: ..., collect: ... }
```

**Result Structure**:
```python
{
    "results": [
        {"patient_id": "p1", "data": [...]},  # All pages for p1
        {"patient_id": "p2", "data": [...]},  # All pages for p2
        # ... for each patient
    ],
    "stats": {
        "total": 100,
        "success": 95,
        "failed": 5
    }
}
```

### 5. Two-Level Sink Architecture

Sink can be specified at two levels with clear execution semantics:

#### Level 1: Step/Tool-level Sink

Executes based on loop presence:

**Without loop** - Executes once after tool execution:
```yaml
- step: fetch_data
  tool: http
  url: "{{ api_url }}"
  sink:  # Executes once after HTTP call
    tool: postgres
    table: raw_data
    statement: "INSERT INTO raw_data ..."
```

**With loop** - Executes ONCE after ALL iterations complete (aggregated result):
```yaml
- step: fetch_all_patients
  tool: http
  url: "{{ api_url }}/patients/{{ patient_id }}"
  loop:
    collection: "{{ patient_ids }}"
    element: patient_id
  sink:  # Executes ONCE with aggregated results from all iterations
    tool: postgres
    table: batch_summary
    statement: |
      INSERT INTO batch_summary (execution_id, total_patients, data)
      VALUES (
        {{ execution_id }},
        {{ result | length }},
        $${{ result | tojson }}$$::jsonb
      )
```

#### Level 2: Retry-level Sink

Executes at retry policy completion (per iteration when in loop):

**In loop with per-iteration sink**:
```yaml
- step: fetch_all_patients
  tool: http
  url: "{{ api_url }}/patients/{{ patient_id }}/medications"
  loop:
    collection: "{{ patient_ids }}"
    element: patient_id
  retry:
    - when: "{{ response.paging.hasMore }}"
      then:
        max_attempts: 100
        next_call:
          params:
            page: "{{ response.paging.page + 1 }}"
        collect:
          strategy: append
          path: data
        sink:  # Executes for EACH patient after their pagination completes
          tool: postgres
          table: patient_medications
          statement: |
            INSERT INTO patient_medications (patient_id, medications)
            VALUES (
              '{{ patient_id }}',
              $${{ result | tojson }}$$::jsonb
            )
            ON CONFLICT (patient_id) DO UPDATE SET
              medications = $${{ result | tojson }}$$::jsonb,
              updated_at = now()
```

**Execution Flow**:
1. Loop iteration starts for patient_id[0]
2. HTTP call (page 1) → success
3. Pagination policy evaluates `when: "{{ response.has_more }}"` → true, continue
4. HTTP call (page 2) → success
5. All pages accumulated via `collect`
6. Pagination completes → **retry policy's `then.sink` executes** (saves patient_id[0] data)
7. Iteration reports completion
8. Repeat for patient_id[1], etc.

### Sink Precedence Rules

When both sinks are defined:

```yaml
- step: process_batch
  tool: http
  loop:
    collection: "{{ items }}"
    element: item
  retry:
    - when: "{{ response.has_more }}"
      then:
        max_attempts: 100
        collect:
          strategy: append
          path: data
        sink:  # EXECUTES per iteration after retry/pagination completes
          tool: postgres
          table: item_details
  sink:  # EXECUTES once after ALL iterations complete
    tool: postgres
    table: batch_summary
```

**Both sinks execute**:
1. `retry[].then.sink` → Per iteration (after retry policy completes)
2. `sink` at step level → Once after loop completes (aggregated)

**Use Cases**:
- **Per-iteration sink**: Upsert individual records as they're fetched (incremental progress)
- **Step-level sink**: Summary/batch metadata after everything completes

## Implementation Details

### Loop Result Accumulation Logic

```python
async def execute_loop_iteration(iteration_ctx):
    """Execute single loop iteration with pagination support."""
    
    # Execute tool with retry/pagination
    result = await execute_with_retry(
        tool_config=iteration_ctx.tool,
        retry_config=iteration_ctx.retry
    )
    
    # Result already accumulated by retry[].then.collect
    # Do NOT emit step_result here - only iteration_completed
    
    await emit_event({
        "event_type": "iteration_completed",
        "status": "success",
        "result": result  # Accumulated pagination results for this iteration
    })
    
    return result


async def execute_loop(loop_ctx):
    """Execute loop - accumulate iteration results, emit single step_result."""
    
    iteration_results = []
    
    for element in loop_ctx.collection:
        iteration_result = await execute_loop_iteration(element)
        iteration_results.append(iteration_result)
    
    # Aggregate all iteration results
    aggregated = {
        "results": iteration_results,
        "stats": {
            "total": len(iteration_results),
            "success": sum(1 for r in iteration_results if r.get("status") == "success")
        }
    }
    
    # Execute step-level sink if present (with aggregated results)
    if loop_ctx.sink:
        await execute_sink(loop_ctx.sink, result=aggregated)
    
    # Emit SINGLE step_result after loop completes
    await emit_event({
        "event_type": "step_result",
        "status": "completed",
        "result": aggregated
    })
```

### Sink Execution Context

**Available variables in sink templates**:
- **`result`**: Unwrapped result data (data field from envelope, already extracted)
- **`this`**: Full result envelope with `status`, `data`, `error`, `meta` fields
- **`workload`**: Global workflow variables
- **`execution_id`**: Current execution identifier
- **Loop context variables** (when in loop):
  - `{{ element_name }}` (e.g., `patient_id`) - current iteration element
  - `{{ _loop.index }}` - current iteration index (0-based)
  - `{{ _loop.count }}` - total iterations
**Step-level sink receives aggregated results**:
```yaml
sink:
  tool: postgres
  statement: |
    INSERT INTO summary (total, success_count)
    VALUES (
      {{ result.stats.total }},
      {{ result.stats.success }}
    )
```

**Retry-level sink receives per-iteration results**:
```yaml
retry:
  - when: "{{ response.paging.hasMore }}"
    then:
      collect: ...
      sink:
        tool: postgres
        statement: |
          INSERT INTO items (id, data)
          VALUES (
            '{{ patient_id }}',
            $${{ result | tojson }}$$::jsonb
          )
```     )
```

## Examples

### Complete Example: Loop + Pagination + Per-Iteration Sink

```yaml
- step: fetch_medications
  desc: Fetch medications for all patients with pagination and per-patient persistence
  tool: http
  url: "{{ api_url }}/patients/{{ patient_id }}/medications"
  method: GET
  params:
    page: 1
    pageSize: 100
  
  loop:
    collection: "{{ patient_ids }}"  # Array of patient IDs
  retry:
    # Error retry policy
    - when: "{{ error.status in [500, 502, 503, 504] }}"
      then:
        max_attempts: 3
        backoff_multiplier: 2.0
        initial_delay: 0.5
    
    # Pagination continuation policy  
    - when: "{{ response.paging.hasMore == true }}"
      then:
        max_attempts: 100
        next_call:
          params:
            page: "{{ (response.paging.page | int) + 1 }}"
            pageSize: "{{ response.paging.pageSize }}"
        collect:
          strategy: append
          path: data
          into: pages
        
        # Per-patient sink - saves after all pages fetched for this patient
        sink:
          tool: postgres
          auth: "{{ workload.pg_auth }}"
          statement: |
            INSERT INTO public.patient_medications (pcc_patient_id, payload, fetched_at)
            VALUES (
              '{{ patient_id }}',
              $${{ result | tojson }}$$::jsonb,
              now()
            )
            ON CONFLICT (pcc_patient_id) DO UPDATE SET
              payload = $${{ result | tojson }}$$::jsonb,
              fetched_at = now()
          ON CONFLICT (pcc_patient_id) DO UPDATE SET
            payload = $${{ result | tojson }}$$::jsonb,
            fetched_at = now()
  
  # Step-level sink - saves batch summary after ALL patients processed
  sink:
    tool: postgres
    auth: "{{ workload.pg_auth }}"
    statement: |
      INSERT INTO public.medication_batch_log (
        execution_id,
        total_patients,
        success_count,
        failed_count,
        completed_at
      )
      VALUES (
        {{ execution_id }},
        {{ result.stats.total }},
        {{ result.stats.success }},
        {{ result.stats.failed }},
        now()
      )
  
  next:
    - step: validate_results
```

**Execution Flow**:
1. Loop starts with patient_id = "p001"
2. HTTP call: page=1 → response with hasMore=true
3. HTTP call: page=2 → response with hasMore=true
4. HTTP call: page=3 → response with hasMore=false
5. All pages accumulated → `result` = array of all medication records
6. **Retry policy's `then.sink` executes** → Upserts patient p001 data to database
7. Iteration completes, moves to patient_id = "p002"
8. Repeat steps 2-7 for each patient
9. After ALL patients processed → **`sink` at step level executes** → Saves batch summary
10. Single `step_result` emitted with aggregated results

### Example: Loop Without Pagination (Simple Iteration)

### Example: Loop Without Pagination (Simple Iteration)

```yaml
- step: process_cities
  desc: Process weather data for multiple cities
  tool: http
  url: "{{ api_url }}/weather"
  method: GET
  params:
    city: "{{ city.name }}"
    units: metric
  
  loop:
    collection: "{{ cities }}"
    element: city
    mode: async              # Process in parallel
  retry:
    - when: "{{ error.status >= 500 }}"
      then:
        max_attempts: 3
    
    - when: "{{ error is not defined }}"  # On success
      then:
        sink:  # Per-city sink
          tool: postgres
          table: city_weather
          statement: |
            INSERT INTO city_weather (city_name, temperature, updated_at)
            VALUES (
              '{{ city.name }}',
              {{ result.temperature }},
              now()
            )
            ON CONFLICT (city_name) DO UPDATE SET
              temperature = {{ result.temperature }},
              updated_at = now()me) DO UPDATE SET
            temperature = {{ result.temperature }},
            updated_at = now()
  
  next:
    - step: generate_report
```

### Example: Pagination Only (No Loop)

```yaml
- step: fetch_all_events
  desc: Fetch all events with pagination
  tool: http
  url: "{{ api_url }}/events"
  method: GET
  params:
    limit: 1000
    offset: 0
  retry:
    - when: "{{ response.data | length == 1000 }}"
      then:
        max_attempts: 100
        next_call:
          params:
            offset: "{{ (response.offset | int) + 1000 }}"
        collect:
          strategy: append
          path: dataappend
        path: data
  
  sink:  # Single sink after all pages fetched
    tool: postgres
    statement: |
      INSERT INTO events_cache (execution_id, event_count, events)
      VALUES (
        {{ execution_id }},
        {{ result | length }},
        $${{ result | tojson }}$$::jsonb
      )
  
  next:
    - step: process_events
```

## Testing Requirements

1. **Loop Result Aggregation Tests**
   - Verify NO `step_result` events emitted per iteration
   - Verify SINGLE `step_result` event after loop completes
   - Check result structure contains `results` array and `stats` object
   - Validate stats accuracy (total, success, failed counts)
   - Confirm `retry[].then.collect` accumulates pagination data

2. **Sink Execution Tests**
   - **Per-iteration sink**: Verify `retry[].then.sink` executes per iteration
   - **Step-level sink**: Verify `sink` at step level executes once after loop
   - **Both sinks**: Verify both execute when defined (per-iteration + aggregated)
   - **No loop**: Verify step-level sink executes once
   - **Template context**: Verify `result` contains unwrapped data, `{{ patient_id }}` accessible

3. **Pagination + Loop Integration Tests**
   - Loop with pagination: Verify each iteration paginates completely before next
   - Verify `collect` accumulates across pages per iteration
   - Verify final result contains all iterations with all pages
   - Test with `mode: sequential` and `mode: async`

4. **Error Scenarios**
   - Per-iteration sink failure → iteration fails, loop continues
   - Step-level sink failure → entire step fails after loop completes
   - Pagination error → retry logic kicks in, sink not executed until success

## Benefits

1. **Clarity**: Two-level sink with clear semantics (per-iteration vs aggregated)
2. **Efficiency**: Single `step_result` event per loop (not per iteration)
3. **Flexibility**: 
   - Per-iteration persistence (incremental progress, upserts)
   - Batch summary (analytics, auditing)
   - Both together (comprehensive tracking)
4. **Consistency**: `retry[].then.collect` works same way for pagination with/without loop
5. **Simplicity**: No `tool: iterator` confusion - just `loop: {}` attribute on regular tools
