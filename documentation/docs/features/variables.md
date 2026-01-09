# Variables System

NoETL provides a powerful variable management system for sharing data between workflow steps and integrating with external systems.

## Overview

The variables system supports:
- **Declarative extraction** via `vars` blocks in playbook steps
- **Programmatic access** via REST API for external systems
- **Template resolution** using `{{ vars.* }}` syntax
- **Metadata tracking** with access counts and timestamps

## Quick Start

### Extract Variables from Step Results

```yaml
- step: fetch_data
  tool: postgres
  query: "SELECT user_id, email FROM users LIMIT 1"
  vars:
    user_id: "{{ result[0].user_id }}"
    email: "{{ result[0].email }}"
  next:
    - step: process

- step: process
  tool: python
  args:
    user_id: "{{ vars.user_id }}"
    email: "{{ vars.email }}"
  code: |
    def main(user_id, email):
      print(f"Processing user {user_id}: {email}")
```

### Inject Variables via API

External systems can inject variables during execution:

```bash
curl -X POST http://localhost:8082/api/vars/{execution_id} \
  -H "Content-Type: application/json" \
  -d '{
    "variables": {
      "config_override": "production",
      "max_retries": 5
    },
    "var_type": "user_defined",
    "source_step": "external_system"
  }'
```

Then access in playbook:

```yaml
- step: apply_config
  tool: python
  args:
    config: "{{ vars.config_override }}"
    retries: "{{ vars.max_retries }}"
```

## Variable Types

- **step_result** - Extracted from step outputs via vars block
- **user_defined** - Injected externally via API
- **computed** - Calculated values from expressions
- **iterator_state** - Loop iteration variables

## Variable Management API

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/vars/{execution_id}` | GET | List all variables with metadata |
| `/api/vars/{execution_id}/{var_name}` | GET | Get specific variable (increments access_count) |
| `/api/vars/{execution_id}` | POST | Set/inject variables |
| `/api/vars/{execution_id}/{var_name}` | DELETE | Delete variable |

## Variable Metadata

Each variable tracks:
- `value` - The actual value (JSON-serializable)
- `type` - Variable type classification
- `source_step` - Step that created/updated it
- `created_at` - Creation timestamp (UTC)
- `accessed_at` - Last access timestamp (UTC)
- `access_count` - Number of reads via API

## Documentation

- **[Variables Feature Design](/docs/reference/dsl/variables_feature_design)** - Complete design specification
- **[Vars Block Quick Reference](/docs/reference/dsl/vars_block_quick_reference)** - Syntax and patterns
- **[Implementation Summary](/docs/reference/dsl/vars_block_implementation_summary)** - Technical implementation details

## Use Cases

**CI/CD Integration:**
```yaml
- step: deploy
  tool: python
  args:
    environment: "{{ vars.target_env }}"  # Injected by CI pipeline
    version: "{{ vars.release_version }}"
```

**Manual Intervention:**
Operator provides approval token during execution:
```bash
curl -X POST /api/vars/{execution_id} \
  -d '{"variables": {"approval_token": "APPROVED-12345"}}'
```

**Dynamic Configuration:**
Change behavior mid-execution without modifying playbook:
```bash
curl -X POST /api/vars/{execution_id} \
  -d '{"variables": {"debug_mode": true, "log_level": "DEBUG"}}'
```

**State Inspection:**
Debug workflow state without code changes:
```bash
curl http://localhost:8082/api/vars/{execution_id} | jq
```
