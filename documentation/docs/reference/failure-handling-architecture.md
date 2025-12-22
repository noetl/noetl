---
sidebar_position: 10
---

# Failure Handling Architecture

## Overview

All execution paths (success, failure, stopped, killed) must converge at the "end" step before workflow/playbook completion is reported. This universal convergence ensures proper result aggregation and status evaluation regardless of execution outcome.

## Key Principles

1. **"end" Step is Mandatory Convergence Point**
   - All execution paths must route to "end" - it's the single terminal leaf in the workflow tree
   - "end" step acts as aggregator for all execution results
   - Only "end" step can trigger workflow/playbook completion events

2. **Implicit "end" Step Injection**
   - If playbook workflow doesn't define "end" step, one is auto-injected during registration
   - Default "end" evaluates all step results and determines overall status
   - Can be overridden with explicit "end" step definition including tools and logic

3. **Implicit End Routing**
   - Steps without explicit `next:` field automatically route to "end"
   - Prevents orphaned execution branches
   - Ensures universal convergence even for playbooks missing explicit routing

4. **Failure Routing**
   - When step fails (after all retries exhausted), routes to "end" step
   - Failed step emits `step_failed` but does NOT emit `workflow_failed`
   - Workflow continues to "end" step for final evaluation
   - Metadata includes `routed_to_end: true` and `original_failed_step`

5. **Parallel Step Cancellation** (Future)
   - When one parallel step fails with critical error, send cancellation signals
   - Cancelled steps complete their current operation then route to "end"
   - "end" step waits for all paths (cancelled, failed, successful) to join

6. **"end" Step Aggregation**
   - Collects results from all completed steps
   - Evaluates overall execution status (success if all succeeded, failed if any failed)
   - Can apply custom logic in explicit "end" step (e.g., partial success handling)
   - Emits `workflow_completed` or `workflow_failed` based on evaluation
   - Includes metadata: `evaluated_by_end_step: true`, `total_steps`, `failed_steps_count`

7. **Sub-Playbook Status Inheritance** (Future)
   - Step with `tool: {kind: playbook}` executes child playbook
   - Parent step waits for child playbook completion event
   - Inherits child's final status (success/failure) from child's "end" step evaluation
   - Failed child playbook causes parent step to fail and route to parent's "end"

## Implementation Status

### ✅ Completed

1. **Completion Detection** (`orchestrator.py` - `_check_execution_completion()`)
   - Modified to wait for 'end' step completion (checks for `step.exit` event on 'end')
   - Collects all step results (successful/failed) for evaluation
   - Emits `workflow_completed` if all steps succeeded
   - Emits `workflow_failed` if any steps failed

2. **Failure Routing** (`orchestrator.py` - `_handle_action_failure()`)
   - Routes failures to "end" instead of immediate workflow_failed
   - Loads playbook to find "end" step definition
   - Emits `step_started` for "end" step and enqueues it
   - Fallback to `_emit_immediate_failure()` if routing fails

3. **Implicit End Injection** (`catalog/service.py` - `register_resource()`)
   - Auto-injects "end" step if playbook doesn't define one
   - Default end has Python tool with aggregation logic
   - Description: "Implicit workflow aggregator (auto-injected)"

4. **Implicit End Routing** (`orchestrator.py` - `_process_transitions()`)
   - Detects steps without explicit "next" field
   - Automatically creates transition to "end" for universal convergence
   - Skips implicit routing for "end" step itself (prevents infinite loop)

### 🚧 Remaining Work

1. **Parallel Step Cancellation**
   - Track parallel step groups
   - Send cancellation signals when one fails
   - Cancelled steps route to "end"

2. **Sub-Playbook Status Inheritance**
   - Modify playbook tool handler in worker
   - Wait for child playbook completion event
   - Inherit child's final status from child's "end" evaluation

## Implementation Details

### 1. Implicit "end" Step Injection

**Location**: `noetl/server/api/catalog/service.py:175`

```python
@staticmethod
async def register_resource(content: str, resource_type: str = "Playbook") -> Dict[str, Any]:
    resource_data = yaml.safe_load(content) or {}
    path = (resource_data.get("metadata") or {}).get("path") or ...

    # Inject implicit "end" step if playbook doesn't have one
    if resource_type == "Playbook":
        workflow = resource_data.get("workflow", [])
        if workflow and not any(step.get("step", "").lower() == "end" for step in workflow):
            logger.info(f"CATALOG: Injecting implicit 'end' step for playbook '{path}'")
            workflow.append({
                "step": "end",
                "desc": "Implicit workflow aggregator (auto-injected)",
                "tool": {
                    "kind": "python",
                    "code": "def main():\n    return {'status': 'aggregated'}"
                }
            })
            resource_data["workflow"] = workflow
```

### 2. Implicit End Routing

**Location**: `noetl/server/api/run/orchestrator.py:1760`

```python
# Get transitions for this step
step_transitions = transitions_by_step.get(step_name, [])

if not step_transitions:
    # No explicit transitions - check if this is 'end' step
    if step_name.lower() == 'end':
        logger.info(f"Step '{step_name}' is 'end' step with no transitions")
        continue
    
    # Not 'end' step and no transitions - implicitly route to 'end'
    logger.info(f"No transitions found for '{step_name}' - implicitly routing to 'end'")
    
    # Check if workflow has 'end' step
    end_step_def = by_name.get('end')
    if not end_step_def:
        logger.warning(f"No 'end' step found - cannot route '{step_name}'")
        continue
    
    # Create implicit transition to 'end'
    step_transitions = [{
        "to_step": "end",
        "condition": None,
        "with_params": {}
    }]
```

### 3. Failure Routing

**Location**: `noetl/server/api/run/orchestrator.py:571`

```python
async def _handle_action_failure(execution_id: int, action_failed_event_id: Optional[str]) -> None:
    """Route failed steps to 'end' step for aggregation."""
    
    # Load step info and playbook
    step_name, error_message = await _get_failure_details(execution_id, action_failed_event_id)
    playbook = await _load_playbook(execution_id)
    
    # Find 'end' step
    end_step = _find_end_step(playbook)
    if not end_step:
        logger.error("No 'end' step found, falling back to immediate failure")
        await _emit_immediate_failure(...)
        return
    
    # Emit step_failed event
    step_failed_event_id = await _emit_step_failed(execution_id, step_name, error_message)
    
    # Route to end step
    await _emit_step_started_for_end(execution_id, end_step, step_failed_event_id)
    await QueuePublisher.publish_step("end", end_step, execution_id, ...)
```

### 4. Completion Detection

**Location**: `noetl/server/api/run/orchestrator.py:190`

```python
async def _check_execution_completion(execution_id: str, workflow_steps: Dict[str, Dict]) -> None:
    """Check if execution is complete and emit final events."""
    
    # Check if 'end' step has completed
    await cur.execute("""
        SELECT COUNT(*) as end_completed
        FROM noetl.event
        WHERE execution_id = %(execution_id)s
          AND node_name = 'end'
          AND event_type = 'step.exit'
          AND status = 'COMPLETED'
    """, {"execution_id": int(execution_id)})
    
    end_completed = (await cur.fetchone())["end_completed"]
    if end_completed == 0:
        logger.debug(f"'end' step not yet completed, waiting")
        return
    
    # Evaluate all step results
    step_results = await _get_all_step_results(execution_id)
    failed_steps = [s for s in step_results if s["status"] == "FAILED"]
    has_failures = len(failed_steps) > 0
    
    meta = {
        "evaluated_by_end_step": True,
        "total_steps": len(step_results),
        "failed_steps_count": len(failed_steps)
    }
    
    if has_failures:
        # Emit workflow_failed and playbook_failed
        await _emit_workflow_failed(execution_id, failed_steps, meta)
        await _emit_playbook_failed(execution_id, failed_steps, meta)
    else:
        # Emit workflow_completed and playbook_completed
        await _emit_workflow_completed(execution_id, meta)
        await _emit_playbook_completed(execution_id, meta)
```

## Event Flow

### Success Path
```
step1 -> step2 -> step3 -> end
                          └─> [end evaluates: all success]
                              └─> workflow_completed -> playbook_completed
```

### Failure Path (Single Step)
```
step1 -> step2 (fails after retries)
         └─> step_failed(step2)
             └─> route to end
                 └─> end executes
                     └─> [end evaluates: has failure]
                         └─> workflow_failed -> playbook_failed
```

### Implicit Routing Path
```
step1 (no next: field)
      └─> [implicit route created]
          └─> end
              └─> [end evaluates: success]
                  └─> workflow_completed -> playbook_completed
```

### Parallel Failure Path (Future)
```
step1 -> [step2a (parallel) -> continues
         step2b (parallel, fails) -> step_failed -> cancel(step2a)]
      -> step2a (cancelled, routes to end)
      -> end -> [end evaluates: has failure] -> workflow_failed -> playbook_failed
```

### Sub-Playbook Failure (Future)
```
parent_step [calls child_playbook]
  ├─> child: step1 -> step2 (fails) -> child_end
  │                                    └─> [evaluates]
  │                                        └─> child_playbook_failed
  └─> parent_step (inherits failure)
      └─> step_failed(parent_step)
          └─> parent_end
              └─> [evaluates]
                  └─> parent_workflow_failed -> parent_playbook_failed
```

## Database Schema

Current schema supports the architecture. Future enhancements may add:

### Event Table (Future)
- `cancellation_requested` field to track cancellation signals
- `aggregation_data` jsonb field on "end" step events for collected results

### Workflow Tracking (Future)
- Track parallel step groups for cancellation coordination
- Track step dependencies for "end" step wait logic

## Testing

To test the universal "end" convergence:

1. **Success Path**: Create playbook with steps that all succeed
2. **Failure Path**: Create playbook with intentional failure (e.g., divide by zero)
3. **Implicit Routing**: Create playbook with step missing `next:` field
4. **Implicit End**: Create playbook without "end" step definition

All paths should converge at "end" and emit appropriate completion events.

## Migration Notes

- **Backward Compatible**: Existing playbooks work without changes
- **Implicit Injection**: Playbooks without "end" get one automatically
- **Implicit Routing**: Steps without "next" automatically route to "end"
- **No Schema Changes**: Current implementation uses existing event/queue tables
