# Heavy Loop Aggregation Test

This playbook tests the NATS K/V refactoring for loop handling and result aggregation under heavy load conditions.

## Purpose

The primary purpose of this test is to validate that:

1. **NATS K/V 1MB Limit is Respected**: The refactored code stores only counts and metadata in NATS K/V, not actual result values
2. **Loop Handling Works at Scale**: Large loops (100+ items) complete successfully
3. **Result Aggregation Works**: All iteration results are properly aggregated at the end
4. **Event Table Storage**: Results are correctly stored in the event table (not NATS K/V)

## Background

NATS JetStream K/V has a maximum value size limit of 1MB. Previously, the NoETL engine stored actual result values in NATS K/V, which could exceed this limit with:
- Many loop iterations
- Large result payloads
- A combination of both

The refactored code now stores only:
- `collection_size` - number of items to process
- `completed_count` - number of completed iterations (integer)
- `iterator`, `mode`, `event_id` - loop metadata

Actual results are stored in the event table and fetched via the aggregate service when needed.

## Configuration

The playbook has configurable workload parameters:

```yaml
workload:
  # Number of items to process (increase for stress testing)
  item_count: 100

  # Size of padding added to each result (bytes)
  # Increase to test larger payloads
  result_padding_size: 100

  # Processing delay per item (seconds)
  # Set to 0 for maximum throughput
  processing_delay: 0
```

## Workflow Steps

1. **initialize**: Generates a list of items to process based on `item_count`
2. **process_items**: Loop step that processes each item and produces a result
3. **aggregate_results**: Aggregates all loop results and computes statistics
4. **validate_results**: Validates the test completed successfully
5. **end**: Marks the workflow as complete

## Running the Test

### Register the Playbook

```bash
curl -X POST http://localhost:8082/api/catalog/register \
  -H "Content-Type: application/json" \
  -d @tests/fixtures/playbooks/load_test/heavy_loop_aggregation/heavy_loop_aggregation.yaml
```

### Execute with Default Settings (100 items)

```bash
curl -X POST http://localhost:8082/api/execute \
  -H "Content-Type: application/json" \
  -d '{"path": "load_test/heavy_loop_aggregation", "payload": {}}'
```

### Execute with Custom Item Count (Stress Test)

```bash
# 500 items
curl -X POST http://localhost:8082/api/execute \
  -H "Content-Type: application/json" \
  -d '{
    "path": "load_test/heavy_loop_aggregation",
    "payload": {
      "workload": {
        "item_count": 500
      }
    }
  }'

# 1000 items with larger payloads
curl -X POST http://localhost:8082/api/execute \
  -H "Content-Type: application/json" \
  -d '{
    "path": "load_test/heavy_loop_aggregation",
    "payload": {
      "workload": {
        "item_count": 1000,
        "result_padding_size": 500
      }
    }
  }'
```

## Expected Results

A successful test run will show:

```
============================================================
HEAVY LOAD LOOP TEST: PASSED
============================================================
  [PASS] item_count: Processed 100 items as expected
  [PASS] success_rate: 100% success rate
  [PASS] aggregation: Loop and aggregation completed
============================================================
```

## Validation Checks

The test validates:

| Check | Description | Pass Criteria |
|-------|-------------|---------------|
| `item_count` | Number of items processed | Equals `workload.item_count` |
| `success_rate` | Percentage of successful iterations | 100% |
| `aggregation` | Loop and aggregation completed | Both flags true |

## Monitoring

During execution, you can monitor:

### NATS K/V State

The loop state in NATS K/V should contain only:
```json
{
  "collection_size": 100,
  "completed_count": 50,
  "iterator": "item",
  "mode": "sequential",
  "event_id": "..."
}
```

**NOT** a `results` array with actual values.

### Event Table

Results are stored in the `noetl.event` table:
```sql
SELECT event_type, node_name, result, loop_name, current_index
FROM noetl.event
WHERE execution_id = <execution_id>
  AND loop_name = 'process_items'
  AND event_type = 'step.exit'
ORDER BY current_index;
```

## Troubleshooting

### Test Fails with NATS Size Error

If you see errors like "value too large" or "max value size exceeded", the refactoring may not be complete. Check:

1. `nats_kv.py` uses `increment_loop_completed()` instead of `append_loop_result()`
2. `engine.py` stores `completed_count` instead of `results` array
3. No code is accidentally adding results to NATS K/V state

### Aggregation Results Empty

If aggregation shows 0 results:

1. Check the aggregate service is fetching from event table
2. Verify `loop_name` is correctly set on events
3. Check event table has the iteration results

## Related Files

- `noetl/core/cache/nats_kv.py` - NATS K/V cache implementation
- `noetl/core/dsl/v2/engine.py` - Execution engine with loop handling
- `noetl/server/api/aggregate/service.py` - Result aggregation service
- `noetl/core/workflow/result/aggregation.py` - Result aggregation worker
