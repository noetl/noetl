# Rendering 

Jinja template evaluation in the codebase happens at these main stages:

## 1. When executing tasks `noetl/job/`:

In execute_task and its helpers `execute_http_task`, `execute_python_task`, `execute_duckdb_task`, `execute_postgres_task`, fields like endpoint, params, payload, headers, command, and `with` are rendered using `render_template` right before use.

## 2. When executing steps `noetl/broker.py`:

- In `Broker.execute_step`, the `with` parameters for a step are rendered before updating the context and passing to the task.
- For loop steps, the `in` and `filter` fields are rendered before iterating.
For conditional transitions, the `when` condition is rendered before deciding the next step.

## 3. When initializing workload/context `noetl/worker.py`:

- In `Worker.__init__`, the workload from DB or playbook is rendered with the current context at agent startup.

Rendering applys "just-in-time" immediately before a value is needed for logic to use the latest context.