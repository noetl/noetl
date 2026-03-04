# amadeus_ai_chat_request_query

This fixture contains a corrected version of the `api_integration/amadeus_ai_chat_request_query` playbook and explains why the original execution failed.

## What was wrong

The observed execution (`574872248926864111`, started on **2026-03-03 20:08:33** local time) failed for two separate reasons:

1. Runtime infrastructure failure (primary immediate failure)
- Terminal errors show event emission failed after retries:
  - `Server error '500 Internal Server Error' for url 'http://noetl.noetl.svc.cluster.local:8082/api/events'`
- This is outside playbook business logic. When the worker cannot emit lifecycle events, the workflow is marked failed.

2. Playbook design/DSL issues (latent defects)
- Legacy/fragile control flow pattern:
  - Used a `case:` routing step instead of canonical `next.spec + next.arcs[].when` routing.
- Ambiguous HTTP fields:
  - Mixed `endpoint`/`params` patterns that are inconsistent across fixtures and harder to validate.
- Non-standard execution identifier reference:
  - Used `job.uuid` rather than `execution_id` used by current fixtures.
- Missing deterministic sink bootstrap:
  - Inserts assumed `api_results` already exists.
- Weak intent parsing hardening:
  - Did not robustly normalize markdown-wrapped or malformed JSON from LLM output.

## What this fixed playbook changes

1. Canonical routing
- Replaced `case` branching with explicit `next.spec.mode=exclusive` + `next.arcs[].when` conditions.

2. Deterministic persistence
- Adds a start step to create `api_results` if missing.
- Uses `execution_id` consistently.

3. Hardened OpenAI parsing
- Handles markdown code fences.
- Converts parse failures into explicit `status: error` payloads.
- Routes parse failures to `store_parse_error`.

4. Safe Amadeus request construction
- Validates allowed endpoint (`/v2/shopping/flight-offers`).
- Validates required params.
- Clamps `max` to `<= 3`.
- Builds a concrete GET URL before the HTTP call.

5. Explicit error/clarification sinks
- `store_clarification_request` for incomplete intent.
- `store_parse_error` for malformed LLM output.
- `store_validation_error` for invalid endpoint/param shapes.

## Workflow overview

1. `start` - ensure `api_results` exists
2. `analyze_user_intent` - call OpenAI for structured intent JSON
3. `parse_intent_result` - parse/normalize intent payload
4. `build_amadeus_query` - validate endpoint and params, build query URL
5. `execute_amadeus_query` - call Amadeus
6. Persistence branches:
- clarification -> `store_clarification_request`
- parse error -> `store_parse_error`
- validation error -> `store_validation_error`
- success -> `store_amadeus_result`
7. `end`

## Operational notes for this failure class

If you see terminal errors against `/api/events` again, fix runtime health first:
- Verify NoETL server health endpoint and event API responsiveness.
- Check server logs around event write path and backing dependencies.
- Re-run the playbook only after event emission is healthy; otherwise all playbooks can fail independent of DSL quality.

## File

- `amadeus_ai_chat_request_query.yaml`
