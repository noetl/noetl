# Amadeus AI API Integration Example

This playbook demonstrates an AI-powered travel search workflow that integrates Amadeus Flight API with OpenAI for natural language processing.

## Overview

The workflow accepts a natural language travel query (e.g., "I want a one-way flight from SFO to JFK on March 15, 2026 for 1 adult") and:

1. Translates it to Amadeus API parameters using OpenAI
2. Queries the Amadeus Flight Offers API
3. Translates the JSON response back to natural language using OpenAI
4. Stores all API events and final results in PostgreSQL

## Architecture

### Workflow Steps (10 total)

1. **start** - Initialize workflow and create database tables
2. **translate_query_to_amadeus** - Use OpenAI to convert natural language to API parameters
3. **store_openai_query_event** - Log OpenAI translation in database
4. **parse_openai_response** - Extract endpoint and params from OpenAI response (Python tool)
5. **execute_amadeus_query** - Call Amadeus Flight Offers API with OAuth token
6. **store_amadeus_query_event** - Log Amadeus API call
7. **translate_amadeus_response** - Use OpenAI to convert JSON to natural language
8. **store_openai_response_event** - Log OpenAI translation
9. **insert_final_result** - Store final natural language result
10. **end** - Complete workflow (Python tool)

### Key Features

**Keychain-Based Authentication**: Uses NoETL v2's keychain system for declarative credential management:
- `openai_token` - GCP Secret Manager integration for OpenAI API key
- `amadeus_credentials` - GCP Secret Manager for Amadeus client ID/secret
- `amadeus_token` - OAuth2 client credentials flow with auto-renewal

**Python Tool Structure**: Python steps use the standardized v2 format:
```yaml
tool:
  kind: python
  auth: {}  # Optional authentication references
  libs:     # Required library imports
    json: json
  args:     # Input arguments from workflow context
    input_data: '{{ previous_step.data }}'
  code: |
    # Direct code execution (no def main wrapper)
    result = {"status": "success", "data": processed_value}
```

**AI Model Selection**: Uses `gpt-4o-mini` for cost-effective structured output tasks (60% cheaper than gpt-4o).

**SQL Safety**: Uses PostgreSQL dollar-quoting (`$json$...$json$::jsonb`) to prevent SQL injection when embedding JSON data.

**Template Rendering**: Jinja2 templates in SQL commands are rendered server-side before execution, supporting dynamic data from previous steps.

## Prerequisites

1. **Google Cloud Setup**:
   - Service account with Secret Manager access
   - OAuth credentials configured as `google_oauth` in NoETL

2. **Secrets in Google Secret Manager**:
   - `projects/{project-id}/secrets/openai-api-key/versions/1` - OpenAI API key
   - `projects/{project-id}/secrets/api-key-test-api-amadeus-com/versions/1` - Amadeus client ID
   - `projects/{project-id}/secrets/api-secret-test-api-amadeus-com/versions/1` - Amadeus client secret

3. **PostgreSQL Connection**:
   - Credential `pg_local` configured in NoETL

4. **API Access**:
   - Amadeus Self-Service API account (test environment)
   - OpenAI API account with gpt-4o-mini access

## Configuration

Update the `workload` section in `amadeus_ai_api.yaml`:

```yaml
workload:
  pg_auth: pg_local
  gcp_auth: google_oauth
  openai_secret_path: projects/YOUR-PROJECT-ID/secrets/openai-api-key/versions/1
  amadeus_key_path: projects/YOUR-PROJECT-ID/secrets/api-key-test-api-amadeus-com/versions/1
  amadeus_secret_path: projects/YOUR-PROJECT-ID/secrets/api-secret-test-api-amadeus-com/versions/1
  query: I want a one-way flight from SFO to JFK on March 15, 2026 for 1 adult

keychain:
  - name: openai_token
    kind: secret_manager
    provider: gcp
    scope: global
    auth: "{{ workload.gcp_auth }}"
    map:
      api_key: '{{ workload.openai_secret_path }}'

  - name: amadeus_credentials
    kind: secret_manager
    provider: gcp
    scope: global
    auth: "{{ workload.gcp_auth }}"
    map:
      client_id: '{{ workload.amadeus_key_path }}'
      client_secret: '{{ workload.amadeus_secret_path }}'

  - name: amadeus_token
    kind: oauth2
    scope: global
    auto_renew: true
    endpoint: https://test.api.amadeus.com/v1/security/oauth2/token
    method: POST
    headers:
      Content-Type: application/x-www-form-urlencoded
    data:
      grant_type: client_credentials
      client_id: '{{ keychain.amadeus_credentials.client_id }}'
      client_secret: '{{ keychain.amadeus_credentials.client_secret }}'
```

## Execution

### Using noetl (Recommended)

```bash
# Register the playbook
noetl catalog register tests/fixtures/playbooks/api_integration/amadeus_ai_api/amadeus_ai_api.yaml

# Execute the playbook
noetl execute playbook api_integration/amadeus_ai_api --json

# Get execution status (replace <EXECUTION_ID> with the id returned from execute)
noetl execute status <EXECUTION_ID> --json

# Alternative: Direct execution using path
noetl exec api_integration/amadeus_ai_api
```

### Using REST API (Alternative)

```bash
# Execute via REST API
curl -X POST http://localhost:8082/api/run/playbook \
  -H "Content-Type: application/json" \
  -d '{"path": "api_integration/amadeus_ai_api", "args": {"query": "I want a one-way flight from SFO to JFK on March 15, 2026 for 1 adult"}}'

# Poll execution status/result
# Replace <EXECUTION_ID> with the id returned from the call above
curl -s http://localhost:8082/api/executions/<EXECUTION_ID> | jq .
```

### Expected Output

The workflow stores results in two tables:

**amadeus_ai_events**: API call logs
```sql
SELECT execution_id, event_type, api_call_type, status_code 
FROM amadeus_ai_events 
ORDER BY event_time DESC;
```

**api_results**: Final natural language summary
```sql
SELECT execution_id, result->>'query' as query, 
       result->>'natural_language_result' as summary 
FROM api_results 
ORDER BY created_at DESC;
```

The final result is base64-encoded. Decode it:
```sql
SELECT 
  execution_id,
  result->>'query' as query,
  convert_from(decode(result->>'natural_language_result', 'base64'), 'UTF-8') as summary
FROM api_results 
WHERE execution_id = 'YOUR-EXECUTION-ID';
```

### Using GraphQL Router (Phase 1)

The GraphQL router provides a convenient interface to start the playbook and then poll results from NoETL REST.

1) Start the router (see `noetl-graphql-router/README.md`). Ensure env:
- `NOETL_BASE_URL=http://localhost:8082`

2) Execute the playbook via GraphQL. Use the mutation from this repo file:

File: `tests/fixtures/playbooks/api_integration/amadeus_ai_api/router_example.graphql`
```
mutation ExecuteAmadeus($vars: JSON) {
  executePlaybook(name: "api_integration/amadeus_ai_api", variables: $vars) {
    id
    name
    status
  }
}
```

GraphQL variables example:
```
{
  "vars": {
    "query": "I want a one-way flight from SFO to JFK on March 15, 2026 for 1 adult"
  }
}
```

3) Copy the returned `id` as `<EXECUTION_ID>` and poll NoETL REST for status/result:
```
curl -s http://localhost:8082/api/executions/<EXECUTION_ID> | jq .
```

Note: NATS-based live subscriptions are planned for the next phase. The WebSocket endpoint `/ws` is disabled in Phase 1; polling the REST endpoint is the supported method to retrieve the final markdown result and/or status updates.

## Python Tool Pattern (v2)

The playbook uses NoETL v2's standardized python tool structure:

### Structure
```yaml
tool:
  kind: python
  auth: {}      # Optional: authentication references (e.g., {pg: "{{ workload.pg_auth }}"})
  libs:         # Required: library imports as key-value pairs
    json: json
    datetime: datetime
  args:         # Required: input arguments from workflow context
    input_data: '{{ previous_step.data }}'
    config: '{{ workload.settings }}'
  code: |
    # Direct code execution - no def main() wrapper
    # Access inputs via variable names from args section
    processed = json.loads(input_data)
    
    # Assign result to 'result' variable (not return statement)
    result = {
        "status": "success",
        "data": processed
    }
```

### Key Principles
- **No Function Wrappers**: Code executes directly without `def main()` functions
- **Result Assignment**: Use `result = {...}` instead of `return {...}`
- **Library Imports**: Declare all imports in `libs` section with `import_name: module_name` format
- **Input Arguments**: All inputs passed via `args` section, accessible as variables in code
- **Authentication**: Optional `auth` section for credential references

### Examples from Playbook

**parse_openai_response step**:
```yaml
tool:
  kind: python
  auth: {}
  libs:
    json: json
  args:
    openai_response: '{{ translate_query_to_amadeus.data }}'
  code: |
    try:
        if not openai_response or not openai_response.get('choices'):
            result = {"status": "error", "message": "No response from OpenAI"}
        else:
            content = openai_response['choices'][0]['message']['content'].strip()
            parsed = json.loads(content)
            result = {"status": "success", "endpoint": parsed.get('endpoint'), "params": parsed.get('params')}
    except Exception as e:
        result = {"status": "error", "message": f"Failed to parse: {str(e)}"}
```

**end step**:
```yaml
tool:
  kind: python
  auth: {}
  libs: {}
  args: {}
  code: |
    result = {"status": "completed", "message": "Workflow completed successfully"}
```

## Authentication Architecture (v2)

### Keychain System

NoETL v2 uses a declarative keychain system for credential management:

```yaml
keychain:
  - name: credential_name     # Reference as {{ keychain.credential_name.field }}
    kind: secret_manager|oauth2|basic|bearer
    provider: gcp|aws|azure    # For secret_manager kind
    scope: global|execution    # Credential lifecycle
    auth: "{{ workload.auth_reference }}"  # For accessing secret provider
    map:                       # Field mapping from secrets
      field_name: 'secret/path'
```

### Secret Manager Integration

Fetch credentials from Google Secret Manager:

```yaml
keychain:
  - name: openai_token
    kind: secret_manager
    provider: gcp
    scope: global
    auth: "{{ workload.gcp_auth }}"
    map:
      api_key: '{{ workload.openai_secret_path }}'
```

**How it works**:
1. Keychain entry references GCP auth credential
2. Fetches secret from Secret Manager using OAuth token
3. Caches credential at specified scope (global or execution)
4. Injects credential into template context as `{{ keychain.openai_token.api_key }}`

### OAuth2 Client Credentials Flow

For APIs requiring OAuth client credentials (like Amadeus):

```yaml
keychain:
  - name: amadeus_credentials
    kind: secret_manager
    provider: gcp
    scope: global
    auth: "{{ workload.gcp_auth }}"
    map:
      client_id: '{{ workload.amadeus_key_path }}'
      client_secret: '{{ workload.amadeus_secret_path }}'

  - name: amadeus_token
    kind: oauth2
    scope: global
    auto_renew: true
    endpoint: https://test.api.amadeus.com/v1/security/oauth2/token
    method: POST
    headers:
      Content-Type: application/x-www-form-urlencoded
    data:
      grant_type: client_credentials
      client_id: '{{ keychain.amadeus_credentials.client_id }}'
      client_secret: '{{ keychain.amadeus_credentials.client_secret }}'
```

The keychain system:
- Fetches both `client_id` and `client_secret` from Secret Manager
- Uses them to obtain OAuth access token
- Automatically renews token when `auto_renew: true`
- Makes token available as `{{ keychain.amadeus_token.access_token }}`

### Bearer Token Authentication

For APIs requiring Bearer tokens (like OpenAI):

```yaml
# In HTTP step
tool:
  kind: http
  method: POST
  endpoint: https://api.openai.com/v1/chat/completions
  headers:
    Authorization: "Bearer {{ keychain.openai_token.api_key }}"
  payload:
    model: gpt-4o-mini
```

## Error Handling

The workflow includes comprehensive error logging:

- **API Failures**: Status codes and error messages stored in `amadeus_ai_events`
- **Template Errors**: Jinja2 rendering failures captured in event logs
- **SQL Errors**: PostgreSQL errors with line numbers and context

Monitor execution:
```sql
SELECT event_type, node_name, status, error 
FROM noetl.event 
WHERE execution_id = YOUR_EXECUTION_ID 
ORDER BY created_at DESC;
```

## Cost Optimization

**Model Selection**: Using `gpt-4o-mini` instead of `gpt-4o`:
- Input: $0.15/1M tokens (vs $2.50/1M)
- Output: $0.60/1M tokens (vs $10.00/1M)
- **Savings**: 60% reduction for structured output tasks

**Keychain Credential Caching**: Reduces Secret Manager API calls:
- First execution: 3 Secret Manager calls (openai_token + amadeus_credentials)
- Subsequent executions (with global scope): Credentials reused from cache
- OAuth token auto-renewal: Only when token expires

## Security Best Practices

1. **No Hardcoded Secrets**: All credentials stored in Secret Manager
2. **OAuth Authentication**: Service accounts with minimal permissions
3. **Keychain Scope Management**: Credentials isolated by scope (global/execution)
4. **SQL Injection Protection**: Dollar-quoting for JSON data
5. **Short-Lived Tokens**: OAuth tokens with automatic renewal

## Troubleshooting

### "Date/Time is in the past" Error
Update the query date to a future date in `workload.query`.

### "Auth missing 'key'" Error
Ensure Secret Manager paths are correct in keychain entries and GCP auth credential has access.

### "Invalid keychain reference" Error
Check that keychain names are correctly referenced in template expressions (e.g., `{{ keychain.openai_token.api_key }}`).

### Python Tool Errors
Verify python tools follow v2 structure:
```yaml
# ❌ Bad (v1 style with def main)
code: |
  def main(input_data):
      return {"result": input_data}

# ✅ Good (v2 style)
tool:
  kind: python
  libs: {}
  args:
    input_data: '{{ step.data }}'
  code: |
    result = {"result": input_data}
```

### "syntax error at or near" in SQL
Check that Jinja2 templates use inline conditionals, not multi-line blocks:
```yaml
# ❌ Bad (multi-line)
{% if condition %}
value
{% else %}
NULL
{% endif %}

# ✅ Good (inline)
{% if condition %}value{% else %}NULL{% endif %}
```

### Empty Payload to OpenAI
Verify the `payload` field is used (not `data`) for JSON requests:
```yaml
tool: http
method: POST
payload:  # ✅ For application/json
  model: gpt-4o-mini
  messages: [...]
```

## References

- [Amadeus Self-Service API](https://developers.amadeus.com/)
- [OpenAI API Documentation](https://platform.openai.com/docs/)
- [Google Secret Manager](https://cloud.google.com/secret-manager/docs)
- [NoETL Auth System](../../../../docs/auth_refactoring_summary.md)
- [NoETL DSL Specification](../../../../docs/dsl_spec.md)
