---
sidebar_position: 1
title: NoETL DSL
description: Domain-Specific Language reference for NoETL workflow definitions
---

# NoETL DSL Reference

The NoETL Domain-Specific Language (DSL) defines how workflows are structured and executed. This section covers the complete syntax, patterns, and features of the DSL.

## Core Specification

- [DSL Specification](./dsl_spec) - Complete reference for playbook syntax, step structure, and workflow patterns

## Variables & Data Flow

- [Variables Design](./variables_feature_design) - Architecture for workflow variables and data passing
- [Vars Block Reference](./vars_block_quick_reference) - Quick reference for extracting values from step results
- [Vars Block Implementation](./vars_block_implementation_summary) - Detailed implementation guide

## Control Flow

- [Unified Retry](./unified_retry) - Retry patterns for error recovery and success-driven repetition
- [HTTP Pagination Reference](./http_pagination_quick_reference) - Quick reference for pagination patterns

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
        # Pure Python code - no imports, no def main()
        result = {"status": "success", "data": {"value": input_var}}
workflow:
  - step: start
    next:
      - step: process
  - step: process
    tool:
      kind: workbook
      name: reusable_task
    next:
      - step: end
  - step: end
```

### Key Concepts

| Concept | Description |
|---------|-------------|
| **Playbook** | Top-level workflow definition with metadata, workload, workbook, and workflow |
| **Workload** | Global variables merged with payload, available via Jinja2 templates |
| **Workbook** | Library of named reusable tasks |
| **Workflow** | Ordered list of steps defining execution flow |
| **Step** | Execution unit with tool, args, vars, and routing |
| **Tool** | Action executor (python, http, postgres, duckdb, etc.) |

### Template Namespaces

Access data in templates using these namespaces:

```yaml
# Global variables from workload
"{{ workload.api_url }}"

# Extracted variables from vars blocks
"{{ vars.user_id }}"

# Previous step results
"{{ fetch_data.records }}"

# Current step result (in vars block)
"{{ result.status }}"

# Execution context
"{{ execution_id }}"
```

### Step Routing

```yaml
# Unconditional routing
next:
  - step: next_step

# Conditional routing
next:
  - when: "{{ result.status == 'success' }}"
    then:
      - step: success_handler
  - when: "{{ result.status == 'error' }}"
    then:
      - step: error_handler
  - step: default_handler  # Fallback
```

## See Also

- [Playbook Structure](/docs/features/playbook_structure) - Getting started with playbooks
- [Iterator Feature](/docs/features/iterator) - Looping over collections
- [Pagination](/docs/features/pagination) - HTTP pagination patterns
- [Tools Reference](/docs/reference/tools) - Available action tools
