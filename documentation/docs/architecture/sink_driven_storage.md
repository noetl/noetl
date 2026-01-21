# Sink-Driven Data Storage Architecture Implementation

## Overview
Implement architectural changes to separate data storage from event/NATS payloads, preventing payload size issues in loop+pagination scenarios.

## Problem Statement
Current architecture stores full HTTP response payloads in noetl.event table and NATS k/v, causing 500 errors when paginating large datasets within loops. The sink mechanism saves data externally BUT doesn't prevent full payloads from flowing through events.

## Proposed Solution

### 1. Result Reference Pattern
When sink is present, actions should return metadata/references instead of full data:

```python
# Current (problematic):
result = {
    'status': 'success',
    'data': {
        'response': {...full_http_response...},  # 1000+ items
        'url': '...',
        'headers': {...}
    }
}

# New (sink-driven):
result = {
    'status': 'success',
    'data': {
        'data_reference': {
            'sink_type': 'postgres',
            'table': 'pagination_test_results',
            'row_count': 30,
            'key_range': {'min_id': 1, 'max_id': 30}
        },
        'metadata': {
            'url': '...',
            'status_code': 200,
            'elapsed': 0.5
        }
    }
}
```

### 2. Separate Sink Events
Sink execution should emit dedicated events:

- `sink.start`: Sink execution begins
- `sink.done`: Sink completed successfully (with summary)
- `sink.error`: Sink failed

Event structure:
```python
{
    'event_type': 'sink.done',
    'node_name': 'fetch_all_endpoints.sink',
    'result': {
        'sink_type': 'postgres',
        'table': 'pagination_test_results',
        'rows_affected': 30,
        'execution_time': 0.15
    }
}
```

### 3. Case Evaluation Events
Emit events showing which case conditions matched:

```python
{
    'event_type': 'case.evaluated',
    'node_name': 'fetch_all_endpoints.case.0',
    'result': {
        'case_index': 0,
        'condition': "{{ response.data.paging.hasMore == true }}",
        'matched': True,
        'actions': ['sink', 'retry']
    }
}
```

### 4. Variables for Collection
Use transient table storage instead of collect blocks:

```yaml
# Instead of collect blocks (accumulates in NATS):
case:
  - when: "{{ response.data.paging.hasMore == true }}"
    then:
      - collect:
          strategy: append
          path: data.data
          into: pages

# Use variables (stored in transient table):
case:
  - when: "{{ response.data.paging.hasMore == true }}"
    then:
      - vars:
          pages: "{{ vars.pages | default([]) + response.data.data }}"
```

## Implementation Plan

### Phase 1: HTTP Plugin Changes
**File**: `noetl/tools/http/executor.py`

1. Detect sink presence in step configuration
2. When sink exists, return metadata instead of full response
3. Include sink configuration in response for worker execution

Changes:
```python
async def execute_http_task(..., step_config: Optional[Dict] = None):
    # ... existing code ...
    
    # After response processing
    response_data = process_response(response)
    
    # Check if sink is present in step config
    has_sink = step_config and 'sink' in step_config
    
    if has_sink:
        # Return reference instead of full data
        result_data = build_result_reference(response_data, step_config['sink'])
    else:
        # Return full data (existing behavior)
        result_data = response_data
    
    return _complete_task(...)
```

### Phase 2: Sink Execution Events
**File**: `noetl/worker/v2_worker_nats.py` - `_execute_case_sinks()`

1. Emit `sink.start` before execution
2. Emit `sink.done` with summary on success
3. Emit `sink.error` on failure
4. Include transformation details in events

Changes:
```python
async def _execute_case_sinks(...):
    # ... existing code ...
    
    # BEFORE sink execution
    await self._emit_event(
        server_url, execution_id, f"{step}.sink",
        "sink.start",
        {"case_index": idx, "sink_type": sink_kind}
    )
    
    # Execute sink
    sink_result = await loop.run_in_executor(...)
    
    # AFTER sink execution (success)
    await self._emit_event(
        server_url, execution_id, f"{step}.sink",
        "sink.done",
        {
            "case_index": idx,
            "sink_type": sink_kind,
            "summary": extract_sink_summary(sink_result)
        }
    )
```

### Phase 3: Case Evaluation Events
**File**: `noetl/worker/v2_worker_nats.py` - `_evaluate_case_blocks()`

Emit `case.evaluated` events for each case condition:

```python
async def _evaluate_case_blocks(...):
    for idx, case in enumerate(case_blocks):
        # ... evaluate condition ...
        
        await self._emit_event(
            server_url, execution_id, f"{step}.case.{idx}",
            "case.evaluated",
            {
                "case_index": idx,
                "condition": when_condition,
                "matched": condition_met,
                "actions": list_actions(then_block)
            }
        )
```

### Phase 4: Result Structure Changes
**File**: `noetl/tools/http/response.py`

Add function to build result references:

```python
def build_result_reference(
    response_data: Dict[str, Any],
    sink_config: Dict[str, Any]
) -> Dict[str, Any]:
    """Build result reference when sink is present."""
    sink_tool = sink_config.get('tool', {})
    sink_kind = sink_tool.get('kind', 'unknown')
    
    # Extract summary from response
    data = response_data.get('data', {})
    if isinstance(data, dict):
        items_count = len(data.get('data', []))
    else:
        items_count = 1
    
    return {
        'data_reference': {
            'sink_type': sink_kind,
            'table': sink_tool.get('table'),
            'row_count': items_count,
            'sink_config': sink_config  # Include for worker execution
        },
        'metadata': {
            'url': response_data.get('url'),
            'status_code': response_data.get('status_code'),
            'elapsed': response_data.get('elapsed'),
            'headers': response_data.get('headers')
        },
        # Include actual data for worker to execute sink
        '_internal_data': data
    }
```

### Phase 5: Worker Integration
**File**: `noetl/worker/v2_worker_nats.py`

1. Detect data_reference in result
2. Use `_internal_data` for sink execution
3. Remove `_internal_data` before storing in events

```python
async def _execute_command(...):
    # ... execute action ...
    result = await self._execute_tool(...)
    
    # Check for sink-driven result
    if isinstance(result, dict) and 'data_reference' in result:
        # Extract internal data for sink
        internal_data = result.pop('_internal_data', None)
        
        # Execute sink with internal data
        if case_blocks and internal_data:
            # Build response with internal data for sink
            sink_response = {'data': internal_data}
            await self._execute_case_sinks(
                case_blocks, sink_response, render_context,
                server_url, execution_id, step
            )
        
        # Result now contains only reference/metadata
    
    # Report result (without _internal_data)
    await self._emit_event(..., result=result)
```

## Testing Strategy

### 1. Unit Tests
- Test `build_result_reference()` with various response structures
- Test sink event emission (start, done, error)
- Test case evaluation event emission

### 2. Integration Tests
- Run loop+pagination playbook with sink
- Verify only metadata stored in events
- Verify full data stored in Postgres
- Verify NATS payload sizes stay under limits

### 3. Validation Queries
```sql
-- Check event payload sizes
SELECT 
    event_type,
    node_name,
    pg_column_size(result) as result_size_bytes,
    pg_column_size(context) as context_size_bytes
FROM noetl.event 
WHERE execution_id = :execution_id
ORDER BY created_at;

-- Check sink events
SELECT event_type, node_name, result
FROM noetl.event
WHERE execution_id = :execution_id
  AND event_type IN ('sink.start', 'sink.done', 'sink.error')
ORDER BY created_at;

-- Check case evaluation events
SELECT event_type, node_name, result
FROM noetl.event
WHERE execution_id = :execution_id
  AND event_type = 'case.evaluated'
ORDER BY created_at;

-- Verify data in sink table
SELECT COUNT(*), MIN(id), MAX(id)
FROM pagination_test_results
WHERE execution_id = :execution_id;
```

## Rollout Plan

1. **Phase 1**: Implement result reference pattern in HTTP plugin (backward compatible)
2. **Phase 2**: Add sink event emission in worker
3. **Phase 3**: Add case evaluation events
4. **Phase 4**: Update playbook to use new pattern
5. **Phase 5**: Test and validate

## Backward Compatibility

- If NO sink present, return full data (existing behavior)
- If sink present, return reference (new behavior)
- Old playbooks without sink continue working
- New playbooks with sink get optimized behavior

## Benefits

1. **Payload Size Reduction**: Events store only metadata (KB instead of MB)
2. **NATS Stability**: No more payload size errors
3. **Better Observability**: Separate events for sink operations
4. **Clear Data Flow**: Explicit separation of data storage and event tracking
5. **Scalability**: Can paginate/loop over large datasets without limits

## Next Steps

1. Implement Phase 1 (HTTP plugin changes)
2. Implement Phase 2 (Sink event emission)
3. Update test playbook
4. Validate with regression tests
5. Document new pattern in documentation
