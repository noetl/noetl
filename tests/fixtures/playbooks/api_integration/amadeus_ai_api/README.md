# Amadeus AI API Integration Example

This playbook demonstrates an AI-powered travel search workflow that integrates Amadeus Flight API with OpenAI for natural language processing.

## Overview

The workflow accepts a natural language travel query (e.g., "I want a one-way flight from SFO to JFK on March 15, 2026 for 1 adult") and:

1. Translates it to Amadeus API parameters using OpenAI
2. Queries the Amadeus Flight Offers API
3. Translates the JSON response back to natural language using OpenAI
4. Stores all API events and final results in PostgreSQL

## Architecture

### Workflow Steps (11 total)

1. **start** - Initialize workflow
2. **create_results_table** - Create `api_results` table for final output
3. **create_amadeus_ai_event_table** - Create `amadeus_ai_events` table for API call logging
4. **get_amadeus_token** - Obtain OAuth access token from Amadeus
5. **translate_query_to_amadeus** - Use OpenAI to convert natural language to API parameters
6. **store_openai_query_event** - Log OpenAI translation in database
7. **parse_openai_response** - Extract endpoint and params from OpenAI response
8. **execute_amadeus_query** - Call Amadeus Flight Offers API
9. **store_amadeus_query_event** - Log Amadeus API call
10. **translate_amadeus_response** - Use OpenAI to convert JSON to natural language
11. **store_openai_response_event** - Log OpenAI translation
12. **insert_final_result** - Store final natural language result
13. **end** - Complete workflow

### Key Features

**Google Secret Manager Integration**: All API credentials are retrieved from Google Secret Manager using OAuth authentication:
- Amadeus API client ID and secret
- OpenAI API key

**Declarative Authentication**: Uses NoETL's unified auth system with provider-based resolution:
```yaml
auth:
  amadeus:
    type: oauth2_client_credentials
    provider: secret_manager
    client_id_key: '{{ workload.amadeus_key_path }}'
    client_secret_key: '{{ workload.amadeus_secret_path }}'
    oauth_credential: '{{ workload.oauth_cred }}'
```

**Credential Caching**: Secrets are cached with 1-hour TTL at execution scope for performance.

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
  oauth_cred: google_oauth  # Your Google OAuth credential name
  openai_secret_path: projects/YOUR-PROJECT-ID/secrets/openai-api-key/versions/1
  amadeus_key_path: projects/YOUR-PROJECT-ID/secrets/api-key-test-api-amadeus-com/versions/1
  amadeus_secret_path: projects/YOUR-PROJECT-ID/secrets/api-secret-test-api-amadeus-com/versions/1
  query: I want a one-way flight from SFO to JFK on March 15, 2026 for 1 adult
```

## Execution

### Using NoETL CLI

```bash
# Register the playbook
task register-playbook PLAYBOOK=tests/fixtures/playbooks/api_integration/amadeus_ai_api

# Execute via API (Phase 1)
curl -X POST http://localhost:8082/api/run/playbook \
  -H "Content-Type: application/json" \
  -d '{"path": "api_integration/amadeus_ai_api", "args": {"query": "I want a one-way flight from SFO to JFK on March 15, 2026 for 1 adult"}}'

# Poll execution status/result via NoETL REST
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

Note: NATS-based live subscriptions are planned for the next phase. For now, polling the REST endpoint is the supported method to retrieve the final markdown result and/or status updates.

## Authentication Architecture

### Secret Manager Provider

The `secret_manager` provider enables fetching credentials from external secret management systems:

```yaml
auth:
  alias_name:
    type: bearer|oauth2_client_credentials|api_key|basic
    provider: secret_manager
    key: path/to/secret  # For single-value secrets
    # OR
    client_id_key: path/to/client_id  # For oauth2_client_credentials
    client_secret_key: path/to/client_secret
    oauth_credential: google_oauth  # OAuth token for Secret Manager API
```

**How it works**:
1. Auth resolver detects `provider: secret_manager`
2. Fetches OAuth token from `oauth_credential` reference
3. Calls Secret Manager API with Bearer token
4. Decodes base64-encoded secret value
5. Caches credential for 1 hour (execution-scoped)
6. Injects credential into template context as `{{ auth.alias_name.field }}`

### OAuth2 Client Credentials Flow

For APIs requiring OAuth client credentials (like Amadeus):

```yaml
auth:
  amadeus:
    type: oauth2_client_credentials
    provider: secret_manager
    client_id_key: '{{ workload.amadeus_key_path }}'
    client_secret_key: '{{ workload.amadeus_secret_path }}'
    oauth_credential: '{{ workload.oauth_cred }}'
data:
  grant_type: client_credentials
  client_id: '{{ auth.amadeus.client_id }}'
  client_secret: '{{ auth.amadeus.client_secret }}'
```

The auth system:
- Fetches both `client_id` and `client_secret` from Secret Manager
- Makes them available in templates as `auth.amadeus.client_id` and `auth.amadeus.client_secret`
- HTTP tool sends them in the OAuth token request

### Bearer Token Authentication

For APIs requiring Bearer tokens (like OpenAI):

```yaml
auth:
  openai:
    type: bearer
    provider: secret_manager
    key: '{{ workload.openai_secret_path }}'
    oauth_credential: '{{ workload.oauth_cred }}'
```

The auth system:
- Fetches the API key from Secret Manager
- Automatically injects `Authorization: Bearer {token}` header
- Token available in templates as `auth.openai.token`

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

**Credential Caching**: Reduces Secret Manager API calls:
- First execution: 3 Secret Manager calls
- Subsequent executions (within 1 hour): 0 Secret Manager calls

## Security Best Practices

1. **No Hardcoded Secrets**: All credentials stored in Secret Manager
2. **OAuth Authentication**: Service accounts with minimal permissions
3. **Execution-Scoped Cache**: Credentials isolated per execution
4. **SQL Injection Protection**: Dollar-quoting for JSON data
5. **Short-Lived Tokens**: Amadeus OAuth tokens valid for ~30 minutes

## Troubleshooting

### "Date/Time is in the past" Error
Update the query date to a future date in `workload.query`.

### "Auth missing 'key'" Error
Ensure Secret Manager paths are correct and OAuth credential has access.

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
