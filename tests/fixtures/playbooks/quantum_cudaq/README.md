# Quantum CUDA-Q Orchestration Playbook

This fixture demonstrates how NoETL can orchestrate an NVIDIA CUDA-Q quantum simulation, hand the intermediate results to an AI Meta agent for narrative insights, and land authoritative records in Postgres before notifying downstream HTTP services. It is staged under `tests/fixtures/playbooks/quantum_cudaq/quantum_cudaq.yaml` with the catalog path `tests/quantum/cudaq_ai_pipeline`.

## Why this scenario

1. **End-to-end orchestration** – The playbook aligns with the event-driven control-plane that the NoETL introduction outlines, using the same metadata/workflow structure plus Petri-net style `next.spec` arcs for deterministic routing.
2. **Hybrid compute** – CUDA-Q runs the quantum workload while NoETL keeps CPU/GPU intensive classical tooling (AI summarization, SQL persistence, HTTP hooks) in lockstep.
3. **AI Meta integration** – The workflow shows how to funnel `ctx.simulations` into an analysis step so an AI agent (referenced via `analysis_agent`) can reason about expectation values before emitting business actions.

## Workflow walkthrough

| Step | Purpose | Notable details |
| ---- | ------- | --------------- |
| `start` | Validates that the workload supplied at least one sweep and seeds shared context. | Admission policy caps sweeps at 64 to keep loop fan-out predictable. |
| `fetch_problem` | Pulls the circuit/problem definition over HTTP. | Retries on 429/5xx to stay inside platform guardrails. |
| `prepare_kernel` | Produces a CUDA-Q kernel template plus a per-sweep run plan. | Stores `ctx.kernel_source`, `ctx.run_plan`, and `ctx.qubits`. |
| `run_simulations` | Executes each sweep in a parallel loop. | Wraps the CUDA-Q call in a `try/except` so fixtures keep working without a GPU by emitting synthetic counts. |
| `ai_analysis` | Summarizes expectation values and crafts AI actions. | Designed to plug into `ai-meta` agents for autonomous reasoning, but still works offline by computing statistics. |
| `persist_results` | Ensures the `public.quantum_results` table exists and upserts JSONB payloads for auditing. | Uses `ctx.simulations` and the AI summary, escaping JSON through the `tojson` filter. |
| `publish_results` | Sends the payload to any HTTP collaborator (dashboards, incident bots, etc.). | Uses policy rules to retry transient errors while annotating `ctx.ai_notes`. |
| `end` | Emits an execution digest so the event log clearly shows how many sweeps ran. | Ingest platforms can read `result.notes` for delivery diagnostics. |

## Workload knobs

| Field | Description |
| ----- | ----------- |
| `problem_catalog_url` + `problem_id` | HTTP endpoint that describes the quantum problem. Replace with a real catalog service before running in production. |
| `cudaq_target` | CUDA-Q backend string (e.g., `cudaq:sim`, `mqpu:dgx`, or managed targets exposed via Quantum Cloud). |
| `sweeps` | List of shots/angles/depths that the loop iterates across. Keep the list short for demos, expand for parameter sweeps. |
| `analysis_agent` / `ai_review_prompt` | Which AI Meta persona should summarize the results and what guidance it receives. |
| `postgres_auth` / `postgres_table` | Credential alias plus table to store JSONB artifacts. The command block will create it if missing. |
| `http_endpoint` / `http_auth` | Downstream collaborator endpoint and corresponding credential. |

## Running the playbook locally

1. Register credentials for Postgres, CUDA-Q, and HTTP collaborators as needed (see `tests/fixtures/credentials/` for templates).
2. Register the playbook: `noetl register tests/fixtures/playbooks/quantum_cudaq/quantum_cudaq.yaml --host localhost --port 8082`.
3. Execute it with overrides for your environment, e.g.:

   ```bash
   noetl execute tests/quantum/cudaq_ai_pipeline \
     --host localhost --port 8082 \
     --set problem_catalog_url=https://demo.lab/api/problems \
     --set problem_id=maxcut-16 \
     --set cudaq_target=cudaq:sim \
     --set postgres_auth=pg_test
   ```
4. Inspect `logs/event.json` for the `loop.done` and `call.done` events that prove each phase completed.
5. Verify `public.quantum_results` contains a JSONB payload per `problem_id`/`target`.

## Observability tips

- Watch the event stream for `call.error` events on `run_simulations` to spot CUDA-Q resource shortages early.
- Because the loop writes `ctx.simulations` during each iteration, you can query the execution record mid-flight via the NoETL API to watch partial counts accumulate.
- HTTP delivery annotations live in `ctx.ai_notes`; surface them through dashboards or Slack bots to close the loop with stakeholders.

## References

- NoETL Intro: <https://noetl.dev/docs/intro>
- Getting Started – Architecture: <https://noetl.dev/docs/getting-started/architecture>
- AI Meta integration guide: <https://noetl.dev/docs/ai-meta/>
- NVIDIA CUDA-Q overview: <https://developer.nvidia.com/cuda-q>
