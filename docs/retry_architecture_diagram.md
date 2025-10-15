# Event-Driven Retry Architecture Diagram

## High-Level Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                    NoETL Retry Architecture                          │
│                 (Server-Side Orchestration)                          │
└─────────────────────────────────────────────────────────────────────┘

┌──────────┐           ┌──────────┐           ┌──────────┐
│  Worker  │◄─────────►│  Server  │◄─────────►│ Database │
└──────────┘           └──────────┘           └──────────┘
     │                      │                       │
     │                      │                       │
     ▼                      ▼                       ▼
Execute Task          Evaluate Retry         Store State
Report Event          Enqueue Retry          Event Log
                      Trigger Broker         Queue Table
```

## Detailed Flow

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Retry Execution Cycle                        │
└─────────────────────────────────────────────────────────────────────┘

WORKER                   SERVER                      DATABASE
  │                        │                            │
  │ 1. Lease Job           │                            │
  │───────────────────────>│                            │
  │                        │ SELECT FROM queue          │
  │                        │───────────────────────────>│
  │                        │<───────────────────────────│
  │<───────────────────────│ {job_data, attempts=0}     │
  │                        │                            │
  │ 2. Execute Task        │                            │
  │  (HTTP/Python/etc)     │                            │
  │                        │                            │
  │ 3. Report Event        │                            │
  │  action_error          │                            │
  │───────────────────────>│                            │
  │                        │ 4. Store Event             │
  │                        │───────────────────────────>│
  │                        │ INSERT INTO event          │
  │                        │<───────────────────────────│
  │                        │                            │
  │                        │ 5. Route Event             │
  │                        │  (dispatcher)              │
  │                        │                            │
  │                        │ 6. Action Handler          │
  │                        │  _handle_action_error      │
  │                        │                            │
  │                        │ 7. Get Queue Entry         │
  │                        │───────────────────────────>│
  │                        │<───────────────────────────│
  │                        │                            │
  │                        │ 8. Get Retry Config        │
  │                        │  (from playbook)           │
  │                        │───────────────────────────>│
  │                        │<───────────────────────────│
  │                        │                            │
  │                        │ 9. Evaluate Retry          │
  │                        │  RetryEvaluator            │
  │                        │  - Check retry_when        │
  │                        │  - Check max_attempts      │
  │                        │  - Calculate delay         │
  │                        │                            │
  │                        │ 10. Update Queue           │
  │                        │───────────────────────────>│
  │                        │ UPDATE queue SET           │
  │                        │   attempts = 1,            │
  │                        │   available_at = NOW()+1s  │
  │                        │<───────────────────────────│
  │                        │                            │
  │                        │ 11. Emit Retry Event       │
  │                        │───────────────────────────>│
  │                        │ INSERT step_retry event    │
  │                        │<───────────────────────────│
  │                        │                            │
  │ [Wait for              │                            │
  │  available_at]         │                            │
  │                        │                            │
  │ 12. Lease Job (retry)  │                            │
  │───────────────────────>│                            │
  │                        │ SELECT FROM queue WHERE    │
  │                        │  available_at <= NOW()     │
  │                        │───────────────────────────>│
  │                        │<───────────────────────────│
  │<───────────────────────│ {job_data, attempts=1}     │
  │                        │                            │
  │ 13. Execute Task       │                            │
  │  (retry attempt)       │                            │
  │                        │                            │
  │ 14. Report Event       │                            │
  │  action_completed      │                            │
  │───────────────────────>│                            │
  │                        │ 15. Store Event            │
  │                        │───────────────────────────>│
  │                        │<───────────────────────────│
  │                        │                            │
  │                        │ 16. Broker Evaluation      │
  │                        │  (advance workflow)        │
  │                        │                            │
  │                        │ 17. Enqueue Next Step      │
  │                        │───────────────────────────>│
  │                        │<───────────────────────────│
  │                        │                            │
```

## Component Interactions

```
┌────────────────────────────────────────────────────────────────┐
│                     Component Interactions                      │
└────────────────────────────────────────────────────────────────┘

EventService.emit()
    │
    ├─> Store in noetl.event
    │
    └─> control.dispatcher.route_event()
            │
            └─> control.action.handle_action_event()
                    │
                    ├─> If action_error:
                    │   │
                    │   └─> _handle_action_error_with_retry()
                    │           │
                    │           ├─> _get_queue_entry()
                    │           │
                    │           ├─> retry.get_retry_config_for_step()
                    │           │
                    │           ├─> retry.RetryEvaluator.should_retry()
                    │           │       │
                    │           │       ├─> _evaluate_condition(retry_when)
                    │           │       ├─> _evaluate_condition(stop_when)
                    │           │       └─> _calculate_delay()
                    │           │
                    │           └─> Decision:
                    │               ├─> YES: retry.enqueue_retry()
                    │               │         │
                    │               │         ├─> UPDATE queue SET
                    │               │         │     available_at = NOW() + delay
                    │               │         │
                    │               │         └─> emit step_retry event
                    │               │
                    │               └─> NO: retry.handle_retry_exhausted()
                    │                         │
                    │                         ├─> UPDATE queue SET status='dead'
                    │                         │
                    │                         └─> emit step_retry_exhausted event
                    │
                    └─> broker.evaluate_broker_for_execution()
                            │
                            └─> Advance workflow
```

## State Transitions

```
┌────────────────────────────────────────────────────────────────┐
│                      Queue State Machine                        │
└────────────────────────────────────────────────────────────────┘

                    ┌──────────┐
                    │  queued  │◄─────────┐
                    └────┬─────┘          │
                         │                │
                         │ Worker Lease   │ Retry Enqueue
                         │                │
                    ┌────▼─────┐          │
                    │  leased  │          │
                    └────┬─────┘          │
                         │                │
                         │ Execute        │
                         │                │
                ┌────────┼────────┐       │
                │                 │       │
           Success            Failure     │
                │                 │       │
                │                 │       │
         ┌──────▼───────┐   ┌────▼───────┴──┐
         │  completed   │   │  Retry Check   │
         └──────────────┘   └────┬───────────┘
                                 │
                        ┌────────┼────────┐
                        │                 │
                 Should Retry?      No More Retries
                        │                 │
                        │                 │
                 ┌──────▼───────┐   ┌────▼────┐
                 │    queued    │   │  dead   │
                 │(with delay)  │   └─────────┘
                 └──────────────┘
                        │
                        └─────────────► (retry cycle)
```

## Event Timeline Example

```
┌────────────────────────────────────────────────────────────────┐
│                    Event Timeline (3 attempts)                  │
└────────────────────────────────────────────────────────────────┘

Time    Event                    Queue State              Details
────────────────────────────────────────────────────────────────
T+0s    action_started           leased, attempts=0      Worker starts
        (attempt=1)                                      

T+1s    action_error             leased, attempts=0      Task fails
        (503 error)              

T+1s    step_retry               queued, attempts=1      Retry scheduled
        (delay=1s)               available_at=T+2s       

        [Worker polls queue but job not available yet]

T+2s    action_started           leased, attempts=1      Worker retries
        (attempt=2, is_retry)    

T+3s    action_error             leased, attempts=1      Task fails again
        (503 error)              

T+3s    step_retry               queued, attempts=2      Retry scheduled
        (delay=2s)               available_at=T+5s       

        [Worker polls queue but job not available yet]

T+5s    action_started           leased, attempts=2      Worker retries
        (attempt=3, is_retry)    

T+6s    action_completed         completed, attempts=2   Success!
        

T+6s    [Broker advances         -                       Next step
        workflow to next step]                           

────────────────────────────────────────────────────────────────

If T+6s had failed instead:

T+6s    action_error             leased, attempts=2      Final attempt fails
        (503 error)              

T+6s    step_retry_exhausted     dead, attempts=3        No more retries
        

T+6s    step_failed_terminal     dead                    Terminal failure
        

T+6s    execution_failed         -                       Workflow fails
```

## Retry Configuration Flow

```
┌────────────────────────────────────────────────────────────────┐
│              Retry Configuration Resolution                     │
└────────────────────────────────────────────────────────────────┘

Playbook YAML
    │
    ├─> workflow:
    │     - step: my_step
    │       type: http
    │       retry:              ◄─── Retry config here
    │         max_attempts: 3
    │         retry_when: "..."
    │
    ▼
Catalog Storage (noetl.catalog)
    │
    │ Content: <playbook YAML>
    │
    ▼
Server Evaluation (get_retry_config_for_step)
    │
    ├─> Load playbook from catalog
    ├─> Parse YAML
    ├─> Find step by node_id
    └─> Extract retry config
    │
    ▼
Normalize Config
    │
    ├─> Boolean: true → {} (defaults)
    ├─> Integer: 5 → {max_attempts: 5}
    └─> Dict: <as-is>
    │
    ▼
RetryEvaluator.should_retry()
    │
    ├─> Check max_attempts
    ├─> Evaluate retry_when (Jinja2)
    ├─> Evaluate stop_when (Jinja2)
    └─> Calculate delay
    │
    ▼
Decision: (should_retry, delay) → (True, 2.5s)
```
