# Execution model

NoETL playbook execution model similar to the Erlang process model (as described by Joe Armstrong):

1. __Everything is a Process (Task/Step)__
   - Every task and step is an isolated "process" with its own context/state.
   - Each process (task/step) has a unique name.
2. __Strong Isolation__
   - Each process (task/step) should have its own context and not share state directly with others.
   - Data should only be passed via explicit message passing (not by mutating shared context).
3. __Lightweight Creation/Destruction__
   - Processes (tasks/steps) can be created and destroyed dynamically.
   - They should be lightweight, with minimal overhead for creation and destruction.
   - Each process (task/step) should run independently without relying on shared mutable state.
   - Task/step execution should be lightweight and stateless except for their own context.
4. __Message Passing Only__
   - Processes (tasks/steps) communicate only through messages.
   - No direct function calls or shared mutable state between processes.
   - Data/results are passed explicitly via step transitions (next), with blocks, and task outputs.
   - No global mutable state; only explicit context passing.
5. __Addressability__
   - Each process (task/step) can be addressed by name.
   - If the name of a process (task/step) is known, it can be invoke with data by message.
6. __No Shared Resources__
   - No shared mutable state between processes (tasks/steps).
   - Each process (task/step) should operate on its own context.
   - Data is passed explicitly, not shared or mutated.
   - No global mutable state; only explicit context passing.
7. __Non-local Error Handling__
   - If a process (task/step) fails, it should not handle the error locally.
   - Instead, it should route to an error handler step that is responsible for handling errors.
   - This allows for centralized error handling and recovery strategies.
8. __Do or Fail__
   - Each process (task/step) should either complete its job successfully or fail.
   - If it fails, it should trigger error handling, allowing the system to recover or log the error.
   - Each process (task/step) is responsible for its own success or failure.



#### Isolated Contexts and Message Passing
- When a task/step runs, it creates a new context for it, initialized from the parent, but never mutate the parent context.
- When a task/step finishes, its output/result is passed as a message to the next step/task via the with block or transition.
- All data passing between steps/tasks is explicit.
#### Step/Task Execution Model
- Each step/task is a function: result = run(context)
- The only way to pass data to the next step/task is via the with block or transition.
- The engine should never mutate a global context; only pass data forward.
#### Error Handling
- If a task/step fails, the engine should route to an error handler step, passing the error as a message. 

#### Subtasks and Nested Runs
- When a task/step runs subtasks (via run), each subtask gets its own context, and results are passed up as messages.

#### Message Passing in Steps
```yaml
workflow:
  - step: fetch_data
    run:
      - task: fetch_weather
        with:
          city: "London"
    next:
      - when: "{{ fetch_weather.status == 'success' }}"
        then:
          - step: process_data
            with:
              weather: "{{ fetch_weather.data }}"
      - else:
          - step: error_handler
            with:
              error: "{{ fetch_weather.error }}"
```
- fetch_weather runs in isolation, gets its own context.
- Its result is passed as a message to process_data via the with block.
- No global state is mutated; all data is passed explicitly.

### Implementation
- Each task/step gets a fresh context (copy of parent + explicit with/input).
- Results are only passed via explicit message passing (with, next, task output).
- No global context mutation except for logging/diagnostics.


| Erlang Principle | NoETL Equivalent             |
|------------------|------------------------------|
| Everything is a process | Every task/step is a process |
| Strong isolation | Each task/step has its own context |
| Lightweight processes | Task/step creation is lightweight |
| Message passing only | Data passed only via with, next, task output |
| Unique names | Tasks/steps have unique names |
| Addressability | Tasks/steps can be invoked by name |
| No shared resources | No global mutable state; only explicit context passing |
| Non-local error handling | Error handler steps receive error messages |
| Do or fail | Tasks/steps either succeed or route to error handler |

Relationaship

```text
workbook
  |
  |-> basic_api_call (http)
  |   |-> input: api_key
  |   `-> output: API response
  |
  |-> configurable_alert (http)
  |   |-> input: severity (default="medium"), message
  |   `-> output: alert status
  |
  |-> process_weather (python)
      |-> input: data, rules
      |-> output: {processed, alerts}
      |
      |-> calls -> basic_api_call
      |   |-> uses: result.processed.api_key
      |   
      `-> calls -> configurable_alert
          |-> uses: result.alerts
          `-> when: alerts exist

batch_process (loop)
  |-> in: items
  |-> iterator: item
  |-> with: batch_id
  |
  `-> process_item (python) [for each item]
      |-> input: current(item), batch
      |-> output: {item_id}
      |
      `-> calls -> configurable_alert
          |-> severity="high"
          `-> message=result.item_id

data_pipeline (loop)
  |-> in: data_sources
  |-> iterator: source
  |
  |-> fetch_data (http)
  |   |-> endpoint: source.url
  |   `-> output: raw_data
  |
  `-> transform_data (python)
      |-> input: fetch_data.result
      |-> output: {transformed}
      |
      `-> calls -> store_data
          `-> data=result.transformed

smart_processor (python)
  |-> input: input_data
  |-> output: {needs_alert, needs_storage, data}
  |
  |-> calls -> configurable_alert
  |   |-> when: result.needs_alert
  |   
  `-> calls -> store_data
      |-> when: result.needs_storage
```

Data Flow:
```text
Parameters ---> Task ----> Result
                 |
                 `-> calls --> Other Task
                      with: result.xyz

Loop Context:
items -----> Loop Task -----> item
              |
              `-> Nested Task --> Result
                   with: item.xyz

Pipeline Flow:
fetch_data -----> transform_data -----> store_data
result          with: fetch_data.result   with: result.transformed

Conditional Flow:
Task -----> [when: condition] -----> Called Task
     \
      `-----> [when: condition] -----> Another Called Task

```

