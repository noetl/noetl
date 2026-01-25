# NoETL Architecture

**Architecture design patterns:**

* `worker` → pure background worker pool, **no HTTP endpoints**.

* `server` → orchestration \+ HTTP API; **only** component that applies DSL control flow and updates the queue table.

* `noetl` → CLI to manage workers/server lifecycle.

DSL docs & examples live in files like:

* `docs/dsl_spec.md`

* `docs/examples/weather_loop_example.yaml`

* examples embedded in `README.md`

## System Components and Responsibilities

- API Server: Hosts REST APIs (catalog, events, queue, context rendering, health). It evaluates DSL control flow, records runtime status, and enqueues work for workers.
- Catalog: Stores playbooks (content, metadata, versions) and serves them to the server.
- Event Log: Persists execution events (execution start, step start/complete, action started/completed, errors). Used to reconstruct state and decide next steps.
- Queue: Lightweight job queue (backed by DB). Stores jobs for workers to lease and report completion/failure.
- Workers: Poll for jobs, render context deterministically via server, execute actions, and emit events back to the server.
- Broker Engine:
  - Server-side evaluator: Computes next actionable steps from event history and playbook content and enqueues jobs.
  - Local broker runner: Implements step execution primitives (loops, transitions) for local/agent-style runs.

## Server–Worker Lifecycle (High Level)

1) Register/Load Playbook (optional): A client registers a YAML playbook in the catalog.
2) Start Execution: A client triggers execution; the server writes initial events with input context and playbook metadata.
3) Evaluate Next Steps: The server reconstructs state from the event log, renders conditions and parameters, and picks the next actionable step(s). Skipped steps emit events without creating jobs.
4) Enqueue Jobs: For each actionable step, the server enqueues a job with the resolved node/action and input context.
5) Workers Execute: Workers lease jobs, request server-side context rendering, execute the task, emit events, and mark jobs complete/fail.
6) Advance Workflow: On completion, the server reevaluates state to schedule subsequent steps until the workflow ends.

## Core Database Entities (Conceptual)

- catalog: Playbook resources with content and versions.
- event_log: All execution events with input contexts and results per node/step/action.
- queue: Jobs for workers (execution_id, node_id, action spec, input_context, status, attempts, worker_id, lease_until, etc.).
- runtime: Registrations/heartbeats for server and worker pools.

## Templating and Broker

- Deterministic templating happens on the server; workers request a server-rendered view of context and task configuration to minimize divergence.
- Conditions (pass/when) are evaluated by the broker/evaluator to select branches and skip steps.
- Local broker provides primitives: execute_step, looping, end_loop aggregation, and get_next_steps.

## Reliability and Scaling Notes

- Queue leasing uses DB-level locking to avoid contention.
- Leases/heartbeats allow workers to extend or fail jobs; the server can reap expired leases.
- Idempotency is recommended for steps and actions; the event log is the source of truth for progression.
- Horizontal scaling is achieved by adding worker processes/nodes; the server remains stateless aside from the database.

## **Architecture Overview**

1. Step-level **`case/when/then`** is the single conditional mechanism.

2. **`next`** is structural and unconditional in the schema; all conditional transitions are in `case.then.next`.

3. For transitions, `args` is used. Data for the next step is passed only via `args`.

4. `sink` is usable as an action inside `then` (like `collect`).

5. A **server-side DSL control-flow engine** consumes events and emits commands into the queue.

6. Workers send **events** only; no "update queue" APIs.

7. **Variable extraction** via `vars:` block at step level stores values in `transient` table, accessible as `{{ vars.var_name }}`.

## **Variable Management**

**Two mechanisms for variable handling**:

1. **`vars:` block** (step-level, declarative):
   - Extracts values from step results AFTER execution completes
   - Stored in `noetl.transient` database table
   - Accessible in templates as `{{ vars.var_name }}`
   - REST API: `/api/vars/{execution_id}` for external access
   - Example:
     ```yaml
     - step: fetch_user
       tool:
         kind: postgres
         auth: "{{ workload.pg_auth }}"
         command: "SELECT user_id, email FROM users WHERE id = 1"
       vars:
         user_id: "{{ result[0].user_id }}"
         email: "{{ result[0].email }}"

     - step: send_email
       tool:
         kind: http
         method: POST
         endpoint: "https://api.example.com/send"
         payload:
           to: "{{ vars.email }}"
           subject: "Hello user {{ vars.user_id }}"
     ```

2. **`set:` action** (inside `case.then` blocks, event-driven):
   - Mutates runtime context during event processing
   - Used with `ctx:` for step-specific state
   - Temporary, in-memory only (not persisted to database)
   - Example:
     ```yaml
     case:
       - when: "{{ event.name == 'step.enter' }}"
         then:
           set:
             ctx:
               pages: []  # Initialize accumulator
     ```

**Key Differences**:
- **`vars:`** = Persistent database storage, accessible across all steps via templates and REST API
- **`set:`** = Ephemeral runtime context, exists only during current step execution

## **1\. DSL: step-level `case` with `when` / `then`**

### **1.1 Step shape**

Each step can have an optional **`case`** attribute (4 letters) with entries:

```yaml
- step: fetch_all_endpoints
  desc: Loop over endpoints with HTTP pagination - verify single step_result after loop
  tool:
    kind: http
    url: "{{ workload.api_url }}{{ endpoint.path }}"
    method: GET
    params:
      page: 1
      pageSize: "{{ endpoint.page_size }}"

  loop:
    in: "{{ workload.endpoints }}"
    iterator: endpoint

  case:
    # example: initialize aggregation when the step starts
    - when: "{{ event.name == 'step.enter' }}"
      then:
        set:
          ctx:
            pages: []

    # retry rule on 5xx
    - when: >-
        {{ event.name == 'call.done'
           and error is defined
           and error.status in [500, 502, 503] }}
      then:
        retry:
          max_attempts: 3
          backoff_multiplier: 2.0
          initial_delay: 0.5

    # pagination rule
    - when: >-
        {{ event.name == 'call.done'
           and response is defined
           and response.paging.hasMore == true }}
      then:
        collect:
          from: response.data
          into: pages
          mode: append
        call:
          params:
            page: "{{ (response.paging.page | int) + 1 }}"
            pageSize: "{{ response.paging.pageSize }}"

    # final page → set result and transition
    - when: >-
        {{ event.name == 'call.done'
           and response is defined
           and not response.paging.hasMore }}
      then:
        collect:
          from: response.data
          into: pages
          mode: append
        result:
          from: pages
        next:
          - step: validate_results
            args:
              pages: "{{ pages }}"
```

Rules:

* `case` is a list.

* Each entry has:

  * `when`: Jinja expression (bool), evaluated with an `event` object in context.

  * `then`: action block (dict or list of actions).

### **1.2 Events**

The engine emits **internal events** per step and sets:

* `event.name` in the Jinja context.

First pass: support at least:

* `step.enter` – right before step starts (before loop begins, if present).

* `call.done` – after each tool call (success or error). For looped steps, fires once per iteration.

* `step.exit` – when the step is about to finish (after ALL loop iterations complete or loop breaks early).

**Loop Event Semantics:**

For steps with a `loop`:
1. `step.enter` fires once at the beginning
2. `call.done` fires N times (once per item in the collection)
3. `step.exit` fires once when:
   - All iterations complete normally, OR
   - A `case.then.next` action breaks the loop early

**Iterator Variable Scope:**

The loop `iterator` variable (e.g., `{{ city }}`) is available:
- ✅ In `tool` configuration (endpoint, params, query, etc.)
- ✅ In `case.when` conditions during loop execution
- ✅ In `collect`, `set`, `sink` actions during loop execution
- ❌ NOT in `next.args` (transitions happen at step boundary, after loop completes)

Later we can expand (`loop.item`, `loop.done`, etc.), but design `case` to work generically with `event.name`.

All step-level decision logic is expressed via `case` entries.

---

## **2\. `next` semantics \+ `args` for transitions**

**Current implementation:**

* `next` in the spec as "next step name(s)".

* In examples like `weather_loop_example.yaml`, `next` entries also use `when / then / else` and `with`.

The **`next`** field has the following behavior:

* `next` in schema: **unconditional**, structural.

* **Conditional transitions** are expressed via **`case`**.

* When passing data to another step during a transition, **`args`** is used.

### **2.1 Schema-level `next`**

In the DSL spec (`dsl_spec.md`), `next` supports:

* `next: <string>` or
* `next: [<string>, ...]` or
* `next: [ { step: <name> }, ... ]`

`next` is unconditional and structural. Conditional flows use `case`.

### **2.2 `next` as an action in `then`, with `args`**

Under `case[*].then`, the **`next` action** has this structure:

* `next` under `then` is an **action**, distinct from the structural `next` attribute.

* Each entry under `next` is an object with:

  * `step` (required): name of the target step.

  * `args` (optional, object): values to inject into the target step's context/args.

### **2.3 Transition Patterns**

**Conditional Start Step:**

```yaml
- step: start
  desc: "Start Weather Analysis Workflow"
  next: city_loop  # structural default
  case:
    - when: "{{ event.name == 'step.exit' and workload.state != 'ready' }}"
      then:
        next:
          - step: end
```

**Loop with Args Transition:**

```yaml
- step: city_loop
  desc: "Iterate over cities"
  loop:
    in: "{{ workload.cities }}"
    iterator: city
  next: fetch_and_evaluate  # structural next
  case:
    - when: "{{ event.name == 'step.exit' }}"
      then:
        next:
          - step: fetch_and_evaluate
            args:
              city: "{{ city }}"
              base_url: "{{ workload.base_url }}"
              temperature_threshold: "{{ workload.temperature_threshold }}"
```

Steps that branch based on previous results use `case`-based transitions with `args` for data passing.

### **2.4 `with` vs `args`**

* `with` is used **only** where the step type definition expects it (e.g., `workbook`, `python`, `playbooks`) as inputs to that step/task.

* `args` is used exclusively for cross-step parameter passing in **`next` actions**.

Example for a workbook step:

* Previous step's `case.then.next[*].args` populates `args` for this step.

* `with` is now computing its values from `args`, making the dataflow explicit.

---

## **3\. Actions inside `then` (including `sink`)**

Inside `case[*].then`, the following actions are supported:

* `call:` – re-invoke the current step's tool with updated params/body/headers.

* `retry:` – re-run the last call with backoff and max\_attempts.

* `collect:` – accumulate data into context:

  * `from`, `into`, `mode` (`append`, `extend`, etc.).

* `sink:` – write data to external sink (e.g., postgres/duckdb), using the same structure already used for sink steps or sink blocks in the DSL.

* `set:` – mutate step/workflow context (e.g. `ctx`).

* `result:` – set the step's result payload.

* `next:` – transition to other steps using `args` (as described above).

* `fail:` – mark step/workflow as failed.

* `skip:` – mark step as skipped.

---

## **4\. Server-side DSL Control-flow Engine**

The **control-flow engine** (`dsl/engine.py`) implements event-driven workflow orchestration:

`class Event(BaseModel):`
    `execution_id: str`
    `step: str | None`
    `name: str          # "step.enter", "call.done", "step.exit", "worker.done", etc.`
    `payload: dict      # response, error, metadata...`

`class Command(BaseModel):`
    `execution_id: str`
    `step: str`
    `tool: str`
    `params: dict | None = None`
    `args: dict | None = None  # passed to target step`

`class ControlFlowEngine:`
    `def __init__(self, playbook_repo: PlaybookRepo, state_store: StateStore): ...`

    `def handle_event(self, event: Event) -> list[Command]:`
        `"""`
        `1. Load workflow/playbook definition for execution_id.`
        `2. Determine current step.`
        `3. Build evaluation context:`
           `- workload/context/state`
           `- step metadata`
           `- response/error from event.payload`
           `- event (with event.name)`
           `- args for this step (from previous next.args)`
        `4. Evaluate step.case entries:`
           ``- For each entry: evaluate `when`.``
           ``- If true: execute `then`:``
             `* call => new Command(s) for same step/tool`
             `* retry => new Command(s) with retry metadata`
             `* collect/sink => update StateStore (context/results)`
             `* result => update step result in StateStore`
             `* next => create Command(s) for target step(s) with args`
             `* fail/skip => update state`
        ``5. Also respect structural `next` if no `case`-driven transitions fire and step is complete.``
        `6. Return list[Command] to be persisted into queue table.`
        `"""`

The server's HTTP handlers simply:

* Accept worker events.

* Call `ControlFlowEngine.handle_event`.

* Insert/update commands in the **queue table**.

* Return an ACK.

---


## **5\. Credential Management and Authentication Caching**

### **5.1 Credential API**

The server provides credential management endpoints via `/api/credentials`:

* **POST /api/credentials** - Create or update encrypted credentials
* **GET /api/credentials** - List all credentials with optional filtering
* **GET /api/credentials/\{identifier\}** - Get credential by ID or name
  * Query parameters:
    * `include_data=true` - Include decrypted credential data
    * `execution_id` - Optional execution context for scoped caching
    * `parent_execution_id` - Optional parent execution context
* **DELETE /api/credentials/\{identifier\}** - Delete credential

Implementation:
* Module: `noetl/server/api/credential/`
  * `endpoint.py` - FastAPI route handlers
  * `service.py` - Business logic with encryption/decryption
  * `schema.py` - Pydantic models for request/response

### **5.2 Authentication Cache (auth_cache)**

To optimize credential access and reduce decryption overhead, the server implements an authentication cache in the `noetl.auth_cache` table.

**Schema:**
```sql
CREATE TABLE noetl.auth_cache (
    cache_key TEXT PRIMARY KEY,
    credential_name TEXT NOT NULL,
    credential_type TEXT NOT NULL,
    cache_type TEXT NOT NULL CHECK (cache_type IN ('secret', 'token')),
    scope_type TEXT NOT NULL CHECK (scope_type IN ('execution', 'global')),
    execution_id BIGINT,
    parent_execution_id BIGINT,
    data_encrypted BYTEA NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    accessed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    access_count INTEGER NOT NULL DEFAULT 0
);
```

**Caching Behavior:**

1. **When credentials are fetched with `include_data=true`**:
   * Server decrypts the credential data
   * Encrypts it for cache storage
   * Inserts/updates `auth_cache` with:
     * `cache_type='secret'` (for credentials) or `'token'` (for OAuth tokens)
     * `scope_type='execution'` if `execution_id` provided, otherwise `'global'`
     * `expires_at` set to 1 hour from now (configurable TTL)
   * On conflict (cache hit), updates:
     * `data_encrypted` (refreshes cached data)
     * `accessed_at` (tracks last access)
     * `access_count` (increments usage counter)
     * `expires_at` (extends expiration)

2. **Workers access cached credentials**:
   * Workers call server API: `GET /api/credentials/{key}?include_data=true&execution_id={id}`
   * Server checks cache first (future optimization)
   * Returns decrypted credential data
   * Cache tracks access patterns for monitoring and optimization

**Implementation Standards:**

All database operations in credential service MUST follow these patterns (described conceptually, without code):

- Use the shared async DB pool helper from the core package for all DB access.
- Use dictionary parameters for queries, not positional parameters.
- Use a dictionary-style row factory for cursor results and access fields by column name.
- Do not perform manual commits; rely on the pool/transaction management.
- Do not use low-level connection helpers directly from server code.

**Key Requirements:**
* ONLY use `get_pool_connection()` from `noetl.core.db.pool`
* ALL queries MUST use dict parameters: `%(param_name)s` with dict values
* ALL cursors MUST use `row_factory=dict_row` for result access
* Access results via dict keys: `row["column"]` not tuple indices
* NO manual commits (pool handles transactions automatically)
* NO direct `get_async_db_connection()` usage in server code

**Benefits:**
* Reduces credential decryption overhead (expensive crypto operations)
* Tracks credential usage patterns via `access_count` and `accessed_at`
* Supports both global (cross-execution) and execution-scoped caching
* Automatic expiration and cache refresh on access
* Foundation for future optimizations (local worker-side caching)

### **5.3 Worker Credential Resolution**

Workers fetch credentials during execution via the worker secrets module by calling the server's credential API (e.g., `GET /credentials/{key}?include_data=true`). Optionally, workers may pass `execution_id` (and `parent_execution_id`) to enable execution‑scoped caching.

Future enhancement: Workers can optionally pass `execution_id` and `parent_execution_id` query parameters to enable execution-scoped credential caching, preventing cross-execution credential leakage.

---

## **6\. Workers: read commands, send events (no queue writes)**

Refactor `worker.py` so that workers:

1. **Consume commands** from the queue table (or whatever DB/stream abstraction you use).

2. Execute the specified action (http/postgres/duckdb/python/etc.).

3. POST back to server's event endpoint, e.g.:

   * `POST /v1/events`

   * Body → `Event` model, typically:

     * `name = "call.done"`

     * `payload.response` / `payload.error`

     * `payload.meta` (duration, status, etc.)

Workers must **not**:

* Call APIs to directly update queue rows.

* Write to the queue table except via commands persisted by the server.

Remove or disable any existing "update queue" endpoints used by workers, and replace usage with event posting.

---

## **6\. Parser, schema, docs, tests**

1. **Models / parser**

Add:

 `class CaseEntry(BaseModel):`
    `when: str`
    `then: dict | list`

*
  * Add `case: list[CaseEntry] | None` to the step model.

  * Remove support for step-level `when`.

  * Constrain `next` in models/JSON Schema:

    * As a structural field: `str | list[str] | list[{step: str}]`

    * No `when/then/else` on `next`.

  * Extend action schema to include `next` with `step` and `args` inside `then`.

2. **Docs**

   * Update `docs/dsl_spec.md`:

     * Introduce `case/when/then` as the central conditional construct.

     * Clarify that:

       * `next` on the step is unconditional.

       * Conditional transitions use `case` \+ `then.next`.

       * Use `args` (not `with`) for cross-step data in transitions.

     * Clarify that `with` is reserved for step-type inputs (e.g., workbook/python).

   * Update `weather_loop_example.yaml` and any other examples:

     * Remove `next.when/then/else`.

     * Replace `next.with` with `next.args`.

3. **Tests**

   * DSL parsing tests:

     * Steps with `case` parse correctly.

     * Old `next` with `when/then/else` fails validation (or is at least flagged as deprecated if you want a soft migration).

     * `next.args` is allowed under `then` but not as a top-level `next` field on the step.

   * Engine tests:

     * Given a `call.done` event with `error.status == 503`, and a `case.when` matching that, a `retry` command is produced.

     * Given a `call.done` with `hasMore == true`, `collect` and `call` work as expected.

     * Given a `step.exit` event with conditions, `case.then.next` produces the right Command(s) with `args`, and args appear in the next step's context.

---

Implement these changes incrementally:

1. Update DSL models & schema (`case`, `next`, `args`, removal of step-level `when` and `next.when/then/else`).

2. Update DSL docs \+ examples (`dsl_spec.md`, `weather_loop_example.yaml`, related README snippets).

3. Implement `ControlFlowEngine` and hook it into the server's event endpoint.

4. Refactor workers to send events instead of updating the queue.

5. Add tests for parsing and control flow.

##### **"step" level attribues \- "case" belongs to step or "tool"?**

* **`case` should belong to the *step*** (control-flow of the node).

* **`loop` should also belong to the *step*** (how often that node runs / on what collection).

* **Tool-specific knobs** (`url`, `method`, `query`, etc.) are the ones that should live under a `tool` (or `type`) object.

Let me walk through why.

---

## **1\. Where does `case` logically belong?**

What `case` is doing in your new design:

* reacts to **events** (`step.enter`, `call.done`, `step.exit`, later `loop.*`)

* drives:

  * retries of the current call,

  * pagination calls,

  * aggregation (`collect` / `sink`),

  * **transitions** (`next`),

  * marking the step as `result` / `fail` / `skip`.

That's fundamentally about **"what this step does over its lifetime"**, not just "how this HTTP call behaves".

A single step might:

* call **one tool** (http), then based on result:

  * sink to postgres,

  * then go to another step.

* or even be a *pure routing* step with no tool at all (only `next` logic).

If you glued `case` under `tool`, you'd get weird questions:

* What is `event.name == 'step.exit'` attached to? The tool doesn't know about the whole step lifecycle.

* How do you express transitions (`next`) that aren't tied to one specific tool call?

So:

**Design:** `case` is a **step-level** attribute.
 It owns "how this node behaves in the workflow graph".

Shape:

`- step: fetch_all_endpoints`
  `desc: ...`
  `loop: ...`
  `tool: ...`
  `case:`
    `- when: "{{ event.name == 'step.enter' }}"`
      `then: ...`
    `- when: "{{ event.name == 'call.done' and error.status == 503 }}"`
      `then: ...`
    `- when: "{{ event.name == 'step.exit' }}"`
      `then:`
        `next:`
          `- step: validate_results`
            `args: { ... }`

---

## **2\. Where does `loop` belong?**

`loop` also affects the **step lifecycle**:

* defines the iteration space (`in`, `iterator`),

* influences event semantics (`loop.item`, `loop.done` later),

* wraps the tool call, but is not part of the tool itself (same HTTP tool can be used with or without a loop).

You want to be able to say:

* "This step iterates over `workload.endpoints`."

* "On each item, run this tool and maybe collect/sink results."

* "When the loop is done, transition to another step."

That's again step-level behavior.

So:

**Design:** `loop` is also a **step-level** attribute.

Example:

`- step: fetch_all_endpoints`
  `desc: ...`
  `loop:`
    `in: "{{ workload.endpoints }}"`
    `iterator: endpoint`
  `tool:`
    `kind: http`
    `url: "{{ workload.api_url }}{{ endpoint.path }}"`
    `method: GET`
    `params:`
      `page: 1`
      `pageSize: "{{ endpoint.page_size }}"`
  `case:`
    `- when: "{{ event.name == 'call.done' and response.paging.hasMore }}"`
      `then: ...`

This reads as:

"This step is a loop over endpoints, using an HTTP tool, with these rules."

Much cleaner than burying `loop` inside the tool.

---

## **3\. Should tool attributes be under a `tool` object?**

Here it **does** help to group things.

If we have have:

`- step: fetch_all_endpoints`
  `tool: http`
  `url: ...`
  `method: ...`
  `headers: ...`
  `params: ...`
  `timeout: ...`
  `loop: ...`
  `case: ...`

This mixes three layers:

1. **Step wiring**: `step`, `desc`, `args`, `loop`, `case`, `next`

2. **Tool config**: `url`, `method`, `headers`, `query`, `code`, …

3. **Result wiring**: `as`, `sink`, etc.

Long-term this gets messy (name collisions, harder parsing, harder codegen).

strongly recommended a canonical shape like:

`- step: fetch_all_endpoints`
  `desc: Loop over endpoints with HTTP pagination`
  `args: {}`
  `loop:`
    `in: "{{ workload.endpoints }}"`
    `iterator: endpoint`

  `tool:`
    `kind: http`
    `url: "{{ workload.api_url }}{{ endpoint.path }}"`
    `method: GET`
    `params:`
      `page: 1`
      `pageSize: "{{ endpoint.page_size }}"`
    `timeout: 5`

  `case:`
    `- when: "{{ event.name == 'call.done' and response.paging.hasMore }}"`
      `then: ...`
    `- when: "{{ event.name == 'call.done' and not response.paging.hasMore }}"`
      `then: ...`

  `# optional structural default`
  `next: validate_results`

**Step-level** (graph / control):

* `step`

* `desc`

* `args`

* `loop`

* `case`

* `next`

* `as` (if you keep it)

* anything about routing or state.

**Tool-level** (execution details):

* `tool.kind` (http, pg, duck, py, etc.)

* `tool.url` / `tool.query` / `tool.code` / `tool.endpoint`

* `tool.headers`, `tool.params`, `tool.body`, `tool.timeout`, auth, etc.

* The server-side engine can take `(step, tool, case, loop)` and generate commands easily.

* Workers see a `Command` with a `tool` struct they understand, without needing to know about `case`/`loop`.

---

## **4\. How it lines up with the event-driven engine**

In the architecture you described:

* **Server**:

  * owns DSL parsing and control flow,

  * receives **events**,

  * evaluates **step.case** (using `loop` info if needed),

  * decides which **tool** to call next and pushes commands to the queue.

* **Workers**:

  * just read commands (`tool` \+ args),

  * execute,

  * send back **events**.

That maps very naturally to:

* **Step** \= control-flow container → owns `loop`, `case`, `next`, `args`.

* **Tool** \= execution payload → sits under `tool`.

Putting `case` or `loop` under `tool` would blur that boundary and make the engine "tool-aware" in places that should stay graph-aware.

---

### **TL;DR recommendation**

* **Keep `case` as a step-level attribute.**

* **Keep `loop` as a step-level attribute.**

* **Move HTTP/DB/Python-specific attributes under `tool`**, with `tool.kind` (or `tool.type`) indicating which worker pool executes it.

Here's a fresh, self-contained Copilot prompt you can paste into VS Code.
 I've baked in `tool.kind`, step-level `case`/`loop`, `args` for transitions, and **no backward compatibility**.

`You are working in the NoETL repo.`

`⚠️ HARD REQUIREMENTS`

`- Do NOT preserve backward compatibility with the existing DSL or engine code.`
``- Do NOT try to keep the old step `type:` model, old `next.when/then/else`, or mixed top-level HTTP/postgres attributes.``
`- You are allowed to delete / replace old models, parsers, and control-flow logic and create a clean v2.`
`- Architecture assumptions:`
  `- worker.py = pure background worker pool, NO HTTP endpoints.`
  `- server.py = orchestration + HTTP API; the ONLY component that updates the queue table and applies DSL control flow.`
  `- clictl.py = CLI to manage server and worker lifecycle (start/stop, etc.).`

`We are designing a NEW NoETL DSL execution model with:`

`- Step-level control:`
  ``- `loop` and `case` belong to the STEP, not the tool.``
`- Tool config:`
  ``- All execution-specific fields live under `tool`, keyed by `tool.kind`.``
`- Event-driven server-side control-flow engine:`
  ``- Server receives events, evaluates DSL (`case`, `next`), and writes commands into a queue table.``
  `- Workers only consume commands and emit events back; they NEVER directly update the queue via HTTP.`

`-------------------------------------------------------------------------------`
`1. NEW DSL SHAPE (NO BACKWARD COMPAT)`
`-------------------------------------------------------------------------------`

`Define a NEW step schema (v2) like this:`

`- step: string         # step name`
`- desc: string         # description (optional)`
`- args: object         # inputs for this step, usually from previous steps (optional)`
`- loop: object?        # step-level looping`
`- tool: object         # tool config; MUST contain tool.kind`
`- case: list?          # conditional behavior, event-driven`
`- next: string | list? # structural default next step(s), unconditional`

`1.1 Step-level LOOP`

`` `loop` belongs to the step, not the tool. It controls "how many times this node runs" and over what collection: ``

```` ```yaml ````
`loop:`
  `in: "{{ workload.items }}"   # expression for a collection`
  `iterator: item               # per-item variable name`

(You can extend later with `mode`, etc., but start with `in` and `iterator`.)

The control-flow engine should be aware of loop context (iterator variable, index) when evaluating `case` and constructing commands.

1.2 TOOL CONFIG: tool.kind

Every executable step MUST have:

* REMOVE old `type:` at step level – the new code should NOT use `type: http|python|...` on steps.

* For any old examples (like weather\_loop\_example.yaml, amadeus\_ai\_api.yaml), migrate them to `tool.kind` and tool-specific fields under `tool`.

1.3 CASE / WHEN / THEN (step-level event-based rules)

Each step may define:

`case:`
  `- when: "<jinja expression>"`
    `then:`
      `# action block`

Semantics:

* The server-side engine emits internal events during step execution:

  * At minimum:

    * event.name \= "step.enter" \# before the step starts

    * event.name \= "call.done" \# after a tool call completes (success or error)

    * event.name \= "step.exit" \# when the step is done (result known)

* For each event, build a Jinja context that includes:

  * event.name

  * workload, args, loop state, previous step results, etc.

  * response / error (for call.done)

* Evaluate all `case[*].when` in order:

  * If `when` evaluates to true, execute the corresponding `then` block.

Example for a paginated HTTP step:

`- step: fetch_all_endpoints`
  `desc: Loop over endpoints with HTTP pagination`
  `loop:`
    `in: "{{ workload.endpoints }}"`
    `iterator: endpoint`

  `tool:`
    `kind: http`
    `method: GET`
    `endpoint: "{{ workload.api_url }}{{ endpoint.path }}"`
    `params:`
      `page: 1`
      `pageSize: "{{ endpoint.page_size }}"`

  `case:`
    `# initialize aggregation once when step starts`
    `- when: "{{ event.name == 'step.enter' }}"`
      `then:`
        `set:`
          `ctx:`
            `pages: []`

    `# retry on 5xx`
    `- when: >-`
        `{{ event.name == 'call.done'`
           `and error is defined`
           `and error.status in [500, 502, 503] }}`
      `then:`
        `retry:`
          `max_attempts: 3`
          `backoff_multiplier: 2.0`
          `initial_delay: 0.5`

    `# collect + paginate`
    `- when: >-`
        `{{ event.name == 'call.done'`
           `and response is defined`
           `and response.paging.hasMore == true }}`
      `then:`
        `collect:`
          `from: response.data`
          `into: pages`
          `mode: append`
        `call:`
          `params:`
            `page: "{{ (response.paging.page | int) + 1 }}"`
            `pageSize: "{{ response.paging.pageSize }}"`

    `# final page: set result and go to next step`
    `- when: >-`
        `{{ event.name == 'call.done'`
           `and response is defined`
           `and not response.paging.hasMore }}`
      `then:`
        `collect:`
          `from: response.data`
          `into: pages`
          `mode: append`
        `result:`
          `from: pages`
        `next:`
          `- step: validate_results`
            `args:`
              `pages: "{{ pages }}"`

Important:

* There is NO step-level `when:` anymore; everything is done through `case`.

* Do NOT reintroduce a separate "before/after/error" block; use `event.name` and `case`.

1.4 STEP NEXT vs NEXT ACTION

The current design:

* Structural `next` at step level: simple default edges, unconditional.

* Conditional transitions defined via `case[*].then.next`.

Step-level `next` (unconditional):

`next: validate_results`
`# or`
`next:`
  `- validate_results`
  `- another_step`

No `when/then/else` on this `next` field.

Conditional transitions in `case.then`:

`case:`
  `- when: "{{ event.name == 'step.exit' and some_flag }}"`
    `then:`
      `next:`
        `- step: city_loop`
          `args:`
            `city: "{{ result.city }}"`
  `- when: "{{ event.name == 'step.exit' and not some_flag }}"`
    `then:`
      `next:`
        `- step: end`

Rules:

* Inside `then`, `next` is an ACTION, with:

  * step: target step name

  * args: object injected into the next step's args

* Use **`args` only**, NOT `with`, for cross-step data passing.

* Reserve `with` for tool-level (e.g. workbook/python tasks) if needed.

1.5 ACTION VOCABULARY INSIDE `then`

Implement a core set of actions (extendable):

* call:

  * Re-invoke the step's tool.

  * Accepts overrides like `params`, `endpoint`, `command`, etc. depending on tool.kind.

* retry:

  * Re-run the last call with max\_attempts, backoff\_multiplier, initial\_delay.

* collect:

  * Aggregate data in the step's context.

  * Fields: from, into, mode ("append", "extend", etc.).

* sink:

  * Write data to an external sink; reuse existing semantics from v1 sink blocks, but now callable as an action.

  * Example:
```
     sink:
     tool:
     kind: postgres
     auth: "{{ workload.pg_auth }}"
     command: |
     INSERT INTO events (...)
     args:
     value: "{{ result.value }}"
```
* set:

  * Mutate context (ctx, flags, counters, etc.).

* result:

  * Set this step's result payload (what downstream steps see).

* next:

  * Conditional transitions as described above.

* fail / skip:

  * Mark step (and maybe workflow) as failed or skipped.

The old "rule/case/run" model is not supported; this new `case/when/then` model is used.

---

2. SERVER-SIDE CONTROL-FLOW ENGINE (EVENTS → COMMANDS)

---

Implement a NEW control-flow engine module on the server (e.g. `dsl/engine.py`).

Core models:

`class Event(BaseModel):`
    `execution_id: str`
    `step: str | None`
    `name: str               # "step.enter", "call.done", "step.exit", "worker.done", etc.`
    `payload: dict           # response, error, timing, etc.`
    `# You may add fields like worker_id, attempt, etc.`

`class ToolCall(BaseModel):`
    `kind: str               # "http", "postgres", "duckdb", "python", "workbook", ...`
    `config: dict            # normalized tool config (method, endpoint, command, code, etc.)`

`class Command(BaseModel):`
    `execution_id: str`
    `step: str`
    `tool: ToolCall`
    `args: dict | None = None  # input args for that step/tool`
    `# plus metadata like attempt, backoff, priority if needed`

`class ControlFlowEngine:`
    `def __init__(self, playbook_repo: PlaybookRepo, state_store: StateStore):`
        `...`

    `def handle_event(self, event: Event) -> list[Command]:`
        `...`

`handle_event` responsibilities:

1. Look up the playbook & workflow associated with execution\_id.

2. Determine the current step based on event.step and stored state.

3. Build Jinja context:

   * workload

   * args for this step (from previous transitions)

   * current context variables / loop state

   * event (with event.name and event.payload)

   * response / error extracted from event.payload for call.done

4. Evaluate this step's `case` entries:

   * For each entry:

     * Evaluate `when`.

     * If true:

       * Interpret `then` actions (call, retry, collect, sink, set, result, next, fail, skip).

       * Update state\_store accordingly (context, step result, loop state, workflow status).

       * Generate Command objects for any `call` or `next` actions.

5. If a step completes and no `case`\-based transition overrides it:

   * Use structural step-level `next` as default transitions → create Command(s) for next step(s).

6. Return the list\[Command\] to be inserted into the queue table.

This engine should be **pure orchestration logic**; it does NOT talk directly to workers or run tools.

---

3. SERVER API (HTTP) AND QUEUE TABLE

---

On the server:

* Define an HTTP endpoint for workers and internal components to submit events, e.g.:

  * POST /api/events

    * Body: Event JSON.

    * Implementation:

      * Deserialize to Event.

      * Call ControlFlowEngine.handle\_event(event).

      * Persist returned Command objects into the queue table.

      * Return OK/ACK (no need to return commands themselves to the worker; workers read queue separately).

* The server must be the ONLY writer to the queue table:

  * Inserts new commands.

  * Updates command statuses / attempts.

If there are existing APIs where workers PATCH/PUT queue records directly, remove them and route all updates through events → handle\_event → queue.

---

4. WORKERS (worker.py) – EXECUTION ONLY

---

Refactor worker.py to:

1. Poll / subscribe to the queue table to fetch available Command records.

2. For each Command:

   * Execute based on tool.kind:

     * http: issue HTTP request.

     * postgres: run SQL.

     * duckdb: run SQL/script.

     * python: run inline code.

     * workbook: call another task, etc.

   * Build an Event with:

     * execution\_id, step

     * name \= "call.done" (or other event names if needed)

     * payload:

       * response envelope (data, status, headers, etc.) on success

       * error object on failure

       * meta: latency, status\_code, etc.

3. POST the Event to the server's /api/events endpoint.

Workers do not:

* Call "update queue" endpoints.

* Directly insert/update records in the queue table except via executing Commands that the server has already decided on.

---

5. MODELS / PARSER / SCHEMA / DOCS

---

Models:

* Create NEW Pydantic models (or dataclasses) for:

  * Playbook v2

  * Step v2

  * ToolSpec with `tool.kind`

  * CaseEntry (when: str, then: dict|list)

  * Loop

Do NOT try to extend old models; replace them and migrate the code paths to v2.

Parser:

* Implement a clean YAML → v2 model parser.

* Existing examples (weather\_loop\_example.yaml, amadeus\_ai\_api.yaml) have been migrated to the new schema; the old layout is not supported.

* Remove support for:

  * step-level `type` field.

  * `next` entries that contain `when` / `then` / `else`.

  * old `run/rule/case` or similar constructs.

Docs & Examples:

* Update the DSL spec file to reflect the new design:

  * Step has: step, desc, args, loop, tool, case, next.

  * tool.kind identifies the tool, with kind-specific fields under tool.

  * `case/when/then` is the only conditional mechanism.

  * Structural `next` is unconditional; conditional transitions are done via `case.then.next` using args.

  * `sink` can be used as a step-level block OR as an action inside `then`, with consistent semantics.

* Rewrite weather\_loop\_example.yaml and amadeus\_ai\_api.yaml to v2 layout:

  * Replace step-level type with tool.kind.

  * Replace any `next.when/then/else` with `case/when/then` plus next actions.

  * Replace cross-step `with` on next with `args`.

---

6. STYLE / IMPLEMENTATION NOTES

---

* Favor small, composable modules:

  * dsl/models.py (Playbook, Step, ToolSpec, CaseEntry, Loop)

  * dsl/parser.py (YAML → models)

  * dsl/engine.py (ControlFlowEngine)

  * server/api.py (HTTP handlers: /api/events, etc.)

  * worker/executor.py (command execution by tool.kind)

* Write unit tests for:

  * Parsing a step with tool.kind, loop, and case.

  * ControlFlowEngine.handle\_event for:

    * retry on error.status \== 503\.

    * pagination with collect \+ call.

    * conditional transitions via case.then.next with args.

* NO backward compatibility. It's OK if old playbooks and engine code stop working; the goal is a clean, logically correct, event-driven v2.

### **Small patch to the Copilot instructions**

**`next` behavior when `case` is absent or doesn't match**

* If a step has **no `case` at all**:

  * The engine:

    * Runs the step's `tool` (respecting `loop` if present).

    * When the step is complete, emits an internal `step.exit` event.

    * Uses the step-level `next` field as-is to schedule the next step(s):

      * `next: "foo"` → schedule step `"foo"` with `args = {}`.

      * `next: ["foo", "bar"]` → schedule `"foo"` and `"bar"` with `args = {}`.

      * `next: [{ step: "foo", args: {...} }, ...]` → schedule each with their static `args`.

* If a step **does have `case`**:

  * On `step.exit`, the engine evaluates all `case[*].when`.

  * If any matching `case` entry executes a `then.next` action, those transitions are used and **structural `next` is ignored** for that event.

  * If no `case.then.next` fires on `step.exit`, the engine falls back to structural `next` exactly as above.

That gives you a very clear story:

* `case` \= optional override / branching logic.

* `next` \= default unconditional edges that always work, even when `case` is completely absent.
