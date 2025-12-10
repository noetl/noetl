# Unified Retry + Sink Implementation Plan

> **Status**: Implementation plan for when/then retry pattern  
> **Design Doc**: See `unified_retry_sink_design.md` for complete specification  
> **Evaluation**: First-match (short-circuit) semantics  
> **Migration**: Includes automated migration script and examples

## Overview

This document outlines the implementation plan for fixing loop result reporting and clarifying sink execution semantics.

## Key Design Decisions

### 1. Unify Retry Structure to When/Then Pattern

**Decision**: Replace `on_error`/`on_success` with unified `when`/`then` pattern for consistency.

**Rationale**:
- **Single conditional pattern** throughout entire DSL (next, retry, future features)
- **Consistency** - Only one way to express conditions
- **First-match semantics** - Same evaluation order as next: routing
- **Flexibility** - Multiple retry policies with different conditions
- **Composability** - Easy to add rate limiting, circuit breakers, etc.
- **Simpler learning curve** - One pattern to understand

**Evaluation Semantics**:
- **First match wins** - Policies evaluated in order, first truthy condition executes
- Consistent with `next:` routing pattern
- Order matters - place specific conditions before general ones

**Migration**:
- Support both patterns during transition
- Convert existing playbooks with automated migration tool
- Deprecate `on_error`/`on_success` in next major version

### 2. Fix Loop Result Reporting

**Current Problem**:
- Loop emits `step_result` event for EACH iteration
- Creates event noise (N results for N elements)
- Unclear what the final step result is

**Solution**:
- Use `retry[].then.collect` to accumulate pagination results per iteration
- Loop handler collects ALL iteration results internally
- Emit SINGLE `step_result` event after loop completes with aggregated structure:
  ```json
  {
    "results": [<iteration_0_result>, <iteration_1_result>, ...],
    "stats": {"total": N, "success": M, "failed": K}
  }
  ```

### 3. Two-Level Sink Architecture

**Level 1: Step/Tool-level sink**
- **Without loop**: Executes once after tool execution
- **With loop**: Executes once after ALL iterations complete (receives aggregated results)

**Level 2: Retry-level sink**
- `retry[].then.sink` (within when/then policy)
- **Without loop**: Executes after retry policy completes
- **With loop**: Executes PER ITERATION after that iteration's retry/pagination completes

**Both can coexist**: Per-iteration sink for incremental progress, step-level sink for batch summary

## Implementation Tasks

### Phase 1: Core Loop Result Aggregation

**Files to modify**:
- `noetl/plugin/controller/result/aggregation.py` - Loop result aggregation logic
- Loop execution handler (worker-side) - Prevent per-iteration `step_result` emission

**Changes**:
1. Loop handler should NOT emit `step_result` per iteration
2. Only emit `iteration_completed` per iteration (internal tracking)
3. After ALL iterations complete, collect results and emit SINGLE `step_result`
4. Result structure:
   ```python
   {
       "results": [iter_0_result, iter_1_result, ...],
       "stats": {
           "total": len(iterations),
           "success": count_successful,
           "failed": count_failed
       }
   }
   ```

### Phase 2: Sink Execution Logic

**Files to modify**:
- Sink execution handler (worker-side)
- Retry handler with sink support

**Changes**:

1. **Step-level sink**:
   ```python
   async def execute_step_with_loop(step_config):
       iteration_results = []
       
       for element in collection:
           iter_result = await execute_iteration(element)
           iteration_results.append(iter_result)
       
       aggregated = {
           "results": iteration_results,
           "stats": calculate_stats(iteration_results)
       }
       
       # Execute step-level sink if present (with aggregated results)
       if step_config.get('sink'):
           await execute_sink(
               sink_config=step_config['sink'],
               result=aggregated,  # Aggregated results
               context={
                   'execution_id': execution_id,
                   'workload': workload,
                   ...
               }
           )
       
       # Emit single step_result
       await emit_event({
           "event_type": "step_result",
           "status": "completed",
           "result": aggregated
       })
   ```

2. **Retry-level sink (per-iteration)**:
   ```python
   async def execute_iteration(element, retry_config):
       # Execute tool with retry/pagination
       result = await execute_with_retry(
           tool_config=tool,
           retry_config=retry_config
       )
       
       # If any retry policy has a sink, execute it after retry completes
       for policy in retry_config:
           if 'sink' in policy.get('then', {}):
               await execute_sink(
                   sink_config=policy['then']['sink'],
                   result=result,  # Per-iteration result (after pagination)
                   context={
                       'execution_id': execution_id,
                       'workload': workload,
                       element_name: element_value,  # e.g., patient_id: "p001"
                       '_loop': {
                           'index': iteration_index,
                           'count': iteration_count
                       }
                   }
               )
       
       return result
   ```

### Phase 3: Template Context for Sinks

**Sink template context**:
```python
{
    'result': unwrapped_result,  # Data extracted from envelope
    'this': full_envelope,       # {status, data, error, meta}
    'execution_id': exec_id,
    'workload': workflow_vars,
    # Loop context (if in loop)
    element_name: element_value,  # e.g., patient_id: "p001"
    '_loop': {
        'index': 0,
        'count': 1,
        'size': total_iterations
    }
}
```

### Phase 4: Update Documentation

**Files to update**:
- `documentation/docs/reference/unified_retry.md` - Add sink placement examples
- `documentation/docs/features/pagination.md` - Update with sink examples
- `documentation/docs/features/distributed_loop_retry_architecture.md` - Loop result aggregation

**New content**:
- Two-level sink architecture explanation
- Per-iteration vs aggregated sink use cases
- Template context for sinks
- Complete examples with loop + pagination + sinks

### Phase 5: Update Tests

**Test files**:
- `tests/fixtures/playbooks/pagination/loop_with_pagination/test_loop_with_pagination.yaml` ✅ (Updated)
- Add new test: `tests/fixtures/playbooks/pagination/loop_with_sink/test_loop_with_sink.yaml`
- Add new test: `tests/fixtures/playbooks/pagination/loop_with_per_iteration_sink.yaml`

**Test scenarios**:
1. Loop without sink → verify single `step_result` with aggregated structure
2. Loop with step-level sink → verify sink executes once with aggregated data
3. Loop with retry-level sink → verify sink executes per iteration
4. Loop with both sinks → verify both execute (per-iteration + aggregated)
5. Pagination without loop + sink → verify sink executes once after all pages
6. Loop + pagination + per-iteration sink → verify sink per iteration after pagination

## Testing Checklist

- [ ] Loop emits SINGLE `step_result` (not per iteration)
- [ ] Result structure has `results` array and `stats` object
- [ ] Stats contain correct counts (total, success, failed)
- [ ] Step-level sink receives aggregated results
- [ ] Retry-level sink receives per-iteration results
- [ ] Both sinks execute when defined
- [ ] Template context includes loop variables (`element_name`, `_loop.index`)
- [ ] `retry.on_success.collect` accumulates pagination data correctly
- [ ] Loop + pagination works (each iteration paginates completely)
- [ ] Error handling: iteration failure doesn't break loop

## Migration Notes

**Breaking Changes**: None - this is a fix/clarification of existing behavior

**Backward Compatibility**:
- Existing playbooks without sinks continue to work
- Existing playbooks with step-level sinks work as before
- New feature: `retry[].then.sink` (retry-level sinks within when/then policies)

**Performance Impact**:
- Positive: Fewer events emitted (single `step_result` vs N per loop)
- Positive: Incremental persistence via per-iteration sinks

## Example Use Cases

### Use Case 1: Incremental Patient Data Fetch

**Requirement**: Fetch medication data for 1000 patients, save each patient's data as it's fetched (don't lose progress if job crashes).

**Solution**: Loop with per-iteration sink
```yaml
- step: fetch_medications
  tool: http
  url: "{{ api }}/patients/{{ patient_id }}/meds"
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
        sink:  # Per-patient persistence
          tool: postgres
          statement: "INSERT INTO patient_meds ..."
```

### Use Case 2: Batch Summary Report

**Requirement**: Fetch data for multiple endpoints, generate single summary report after all complete.

**Solution**: Loop with step-level sink
```yaml
- step: fetch_all_endpoints
  tool: http
  loop:
    collection: "{{ endpoints }}"
  sink:  # Single batch summary
    tool: postgres
    statement: "INSERT INTO batch_log (total, success) VALUES ..."
```

### Use Case 3: Both Incremental + Summary

**Requirement**: Save individual patient records + batch summary for audit.

**Solution**: Loop with both sinks
```yaml
- step: fetch_medications
  tool: http
  loop:
    collection: "{{ patient_ids }}"
    element: patient_id
  retry:
    - when: "{{ error is not defined }}"  # On success
      then:
        sink:  # Per-patient
          tool: postgres
          statement: "INSERT INTO patient_meds ..."
  sink:  # Batch summary
    tool: postgres
    statement: "INSERT INTO batch_audit ..."
```

## Success Criteria

1. ✅ Single `step_result` event per loop (not per iteration)
2. ✅ Step-level sink executes with aggregated results
3. ✅ Retry-level sink executes per iteration
4. ✅ Both sinks can coexist
5. ✅ Unified `when`/`then` retry pattern across DSL
6. ✅ Documentation updated with clear examples
7. ✅ Tests cover all scenarios
8. ✅ Migration guide for `on_error`/`on_success` → `when`/`then`

## Migration Guide: on_error/on_success → when/then

### Automated Migration Script

Create `scripts/migrate_retry_syntax.py`:

```python
"""Migrate retry syntax from on_error/on_success to when/then."""

def migrate_retry_block(retry_config: dict) -> list:
    """Convert old retry format to new unified format."""
    policies = []
    
    # Convert on_error block
    if 'on_error' in retry_config:
        error_policy = retry_config['on_error']
        policy = {
            'when': error_policy.get('when', '{{ error is defined }}'),
            'then': {
                'max_attempts': error_policy.get('max_attempts', 3),
                'backoff_multiplier': error_policy.get('backoff_multiplier', 2.0),
                'initial_delay': error_policy.get('initial_delay', 0.5)
            }
        }
        policies.append(policy)
    
    # Convert on_success block
    if 'on_success' in retry_config:
        success_policy = retry_config['on_success']
        then_block = {
            'max_attempts': success_policy.get('max_attempts', 100)
        }
        
        # Map 'while' to 'when' condition
        if 'while' in success_policy:
            when_condition = success_policy['while']
        else:
            when_condition = '{{ error is not defined }}'
        
        # Copy continuation fields
        if 'next_call' in success_policy:
            then_block['next_call'] = success_policy['next_call']
        if 'collect' in success_policy:
            then_block['collect'] = success_policy['collect']
        if 'sink' in success_policy:
            then_block['sink'] = success_policy['sink']
        
        policies.append({
            'when': when_condition,
            'then': then_block
        })
    
    return policies
```

### Manual Migration Examples

**Before (old format)**:
```yaml
retry:
  on_error:
    when: "{{ error.status >= 500 }}"
    max_attempts: 3
    backoff_multiplier: 2.0
  on_success:
    while: "{{ response.paging.hasMore }}"
    max_attempts: 100
    next_call:
      params:
        page: "{{ response.paging.page + 1 }}"
    collect:
      strategy: append
      path: data
```

**After (new format)**:
```yaml
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
      collect:
        strategy: append
        path: data
```

### Backward Compatibility

Support both formats during transition period:

```python
def normalize_retry_config(retry_config):
    """Normalize retry config to unified format."""
    if isinstance(retry_config, list):
        # Already new format
        return retry_config
    
    if 'on_error' in retry_config or 'on_success' in retry_config:
        # Old format - migrate on the fly
        return migrate_retry_block(retry_config)
    
    # Legacy simple format
    return [{
        'when': retry_config.get('when', '{{ error is defined }}'),
        'then': retry_config
    }]
```

### Deprecation Timeline

- **Phase 1 (v1.x)**: Support both formats, log warnings for old format
- **Phase 2 (v1.x+1)**: Provide migration tool, update all docs/examples
- **Phase 3 (v2.0)**: Remove old format support (breaking change)
