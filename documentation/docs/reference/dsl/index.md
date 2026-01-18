---
sidebar_position: 1
title: NoETL DSL
description: Domain-Specific Language reference for NoETL workflow definitions
---

# NoETL DSL Reference

The NoETL Domain-Specific Language (DSL) defines how workflows are structured and executed. This section covers the complete syntax, patterns, and features of the DSL.

## Core Specification

- [DSL Specification](./spec) - Formal specification for playbook syntax, step structure, and workflow patterns (v2)

## Runtime & Events

- [Runtime Event Model](./runtime_events) - Canonical event taxonomy and envelope specification
- [Result Storage & Access](./runtime_results) - How tool outputs and step results are stored and retrieved
- [Artifact Tool](./artifact_tool) - Reading and writing externally stored results
- [Result Storage Implementation](./results_storage_implementation) - Implementation guide for ResultRef and manifests

## Architecture

- [Execution Model](./execution_model) - Event-sourced execution with control plane / data plane architecture
- [Event Sourcing Whitepaper](./event_sourcing_whitepaper) - Technical whitepaper on the event-sourced architecture
- [Formal Specification (Extended)](./formal_specification) - Extended formal specification with detailed semantics

## Variables & Data Flow

- [Variables Design](./variables_feature_design) - Architecture for workflow variables and data passing
- [Vars Block Reference](./vars_block_quick_reference) - Quick reference for extracting values from step results
- [Vars Block Implementation](./vars_block_implementation_summary) - Detailed implementation guide

## Control Flow

- [Unified Retry](./unified_retry) - Retry patterns for error recovery and success-driven repetition
- [HTTP Pagination Reference](./http_pagination_quick_reference) - Quick reference for pagination patterns

---

## DSL Overview

### Playbook Structure

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: example_workflow
  path: workflows/example
workload:
  variable: value
workbook:
  - name: reusable_task
    tool:
      kind: python
      libs: {}
      args:
        input_var: "{{ workload.variable }}"
      code: |
        # Pure Python code - variables from args are directly available
        result = {"status": "success", "data": {"value": input_var}}
workflow:
  - step: start
    tool:
      kind: python
      auth: {}
      libs: {}
      args: {}
      code: |
        result = {"status": "initialized"}
    case:
      - when: "{{ event.name == 'step.exit' }}"
        then:
          next:
            - step: process
  - step: process
    tool:
      kind: workbook
      name: reusable_task
    case:
      - when: "{{ event.name == 'step.exit' }}"
        then:
          next:
            - step: end
  - step: end
    tool:
      kind: python
      auth: {}
      libs: {}
      args: {}
      code: |
        result = {"status": "completed"}
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Playbook** | Top-level workflow definition with metadata, workload, workbook, and workflow |
| **Workload** | Global variables merged with payload, available via Jinja2 templates |
| **Workbook** | Library of named reusable tasks |
| **Workflow** | Ordered list of steps defining execution flow |
| **Step** | Execution unit with tool, args, vars, case, and routing |
| **Tool** | Action executor with `kind` field (python, http, postgres, duckdb, etc.) |

### Available Tool Kinds

| Kind | Description |
|------|-------------|
| `python` | Execute inline Python code |
| `http` | HTTP requests (GET, POST, etc.) |
| `postgres` | PostgreSQL query execution |
| `duckdb` | DuckDB query execution |
| `workbook` | Reference to named task in workbook |
| `playbook` | Execute sub-playbook by catalog path |
| `secrets` | Fetch secret from provider |
| `iterator` | Loop iteration control |
| `snowflake` | Snowflake query execution |
| `gcs` | Google Cloud Storage operations |

### Template Namespaces

Access data in templates using these namespaces:

```yaml
# Global variables from workload
"{{ workload.api_url }}"

# Extracted variables from vars blocks
"{{ vars.user_id }}"

# Previous step results
"{{ fetch_data.records }}"

# Current step result (in vars block only)
"{{ result.status }}"

# Execution context
"{{ execution_id }}"

# Event object (in case.when)
"{{ event.name }}"

# Response envelope (in case.when)
"{{ response.status_code }}"
```

### Step Routing (v2 Pattern)

In v2, conditional routing uses `case/when/then`:

```yaml
# Event-driven conditional routing
case:
  - when: "{{ event.name == 'step.exit' and response.status == 'success' }}"
    then:
      next:
        - step: success_handler
  - when: "{{ event.name == 'call.error' }}"
    then:
      next:
        - step: error_handler

# Default fallback routing (when no case matches)
next:
  - step: default_handler
```

**Note:** The old v1 pattern with `next: [{ when: ..., then: ... }]` is not supported in v2. Use `case` for conditional routing.

## See Also

- [Playbook Structure](/docs/features/playbook_structure) - Getting started with playbooks
- [Iterator Feature](/docs/features/iterator) - Looping over collections
- [Pagination](/docs/features/pagination) - HTTP pagination patterns
- [Tools Reference](/docs/reference/tools) - Available action tools
