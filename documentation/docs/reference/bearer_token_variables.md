# Bearer Token and Execution Variables

## Overview

NoETL provides execution-scoped variable storage for managing bearer tokens, step results, and computed values during playbook execution. This enables clean separation between credential fetching and token usage across workflow steps.

## Key Features

✅ **Bearer Token Variable Assignment**: Store OAuth/JWT tokens as execution variables  
✅ **Automatic Step Results**: All step outputs accessible as variables  
✅ **Execution-Scoped**: Variables lifetime tied to playbook execution  
✅ **Template Access**: Variables available in Jinja2 templates  
✅ **Automatic Cleanup**: Variables removed when execution completes  

## Database Schema

### Execution Variables Table

```sql
CREATE TABLE noetl.execution_variable (
    execution_id BIGINT NOT NULL,
    variable_name TEXT NOT NULL,
    variable_type TEXT NOT NULL CHECK (variable_type IN ('step_result', 'bearer_token', 'computed', 'user_defined')),
    variable_value JSONB NOT NULL,
    source_step TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    PRIMARY KEY (execution_id, variable_name)
);
```

### Variable Types

- **`step_result`**: Automatic - output from any step (e.g., `{{ step_name.field }}`)
- **`bearer_token`**: OAuth/JWT token from auth system with `bearer: true` flag
- **`computed`**: Derived values calculated during execution
- **`user_defined`**: Explicitly set variables (future feature)

## Bearer Token Pattern

### Syntax

```yaml
- step: get_token
  tool: python
  auth:
    credential: '{{ workload.oauth_creds }}'
    bearer: true           # Flag: store result as bearer token
    variable: my_token     # Variable name for template access
  code: |
    def main(auth_credential):
        # Fetch token from OAuth provider
        import httpx
        response = httpx.post(
            "https://oauth.provider.com/token",
            data={
                "grant_type": "client_credentials",
                "client_id": auth_credential['client_id'],
                "client_secret": auth_credential['client_secret']
            }
        )
        token_data = response.json()
        
        # Return just the access_token string
        return token_data["access_token"]

- step: use_token
  tool: http
  endpoint: https://api.example.com/resource
  headers:
    Authorization: Bearer {{ my_token }}  # Use stored variable
```

### How It Works

1. **Step Execution**: Step with `auth.bearer: true` executes
2. **Variable Storage**: Result stored in `noetl.execution_variable` as `bearer_token` type
3. **Context Extension**: Variable added to Jinja2 context for subsequent steps
4. **Template Access**: Available as `{{ variable_name }}` in any template
5. **Cleanup**: Removed when execution completes

### Bearer Token Types

#### 1. OAuth 2.0 Client Credentials

```yaml
workload:
  oauth_creds: my_oauth_credentials

workflow:
- step: get_oauth_token
  tool: python
  auth:
    credential: '{{ workload.oauth_creds }}'
    bearer: true
    variable: oauth_token
  code: |
    def main(auth_credential):
        import httpx
        response = httpx.post(
            "https://oauth.provider.com/token",
            data={
                "grant_type": "client_credentials",
                "client_id": auth_credential["client_id"],
                "client_secret": auth_credential["client_secret"]
            }
        )
        return response.json()["access_token"]

- step: call_api
  tool: http
  headers:
    Authorization: Bearer {{ oauth_token }}
```

#### 2. Service Account Token

```yaml
- step: get_sa_token
  tool: python
  auth:
    credential: '{{ workload.gcp_service_account }}'
    bearer: true
    variable: gcp_token
  code: |
    def main(auth_credential):
        from google.auth.transport.requests import Request
        from google.oauth2 import service_account
        
        credentials = service_account.Credentials.from_service_account_info(
            auth_credential,
            scopes=['https://www.googleapis.com/auth/cloud-platform']
        )
        credentials.refresh(Request())
        return credentials.token

- step: call_gcp_api
  tool: http
  headers:
    Authorization: Bearer {{ gcp_token }}
```

#### 3. JWT Token

```yaml
- step: generate_jwt
  tool: python
  auth:
    credential: '{{ workload.jwt_secret }}'
    bearer: true
    variable: jwt_token
  code: |
    def main(auth_credential):
        import jwt
        import datetime
        
        payload = {
            "sub": "user_id",
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=1)
        }
        return jwt.encode(payload, auth_credential["secret"], algorithm="HS256")

- step: authenticated_request
  tool: http
  headers:
    Authorization: Bearer {{ jwt_token }}
```

## Execution Variables API

### Python Module: `noetl.worker.execution_variables`

#### Store Variable

```python
from noetl.worker.execution_variables import ExecutionVariables

await ExecutionVariables.set_variable(
    execution_id=507431238966182398,
    variable_name='computed_value',
    variable_value={'total': 1500, 'count': 30},
    variable_type='computed',
    source_step='calculate_metrics'
)
```

#### Retrieve Variable

```python
value = await ExecutionVariables.get_variable(
    execution_id=507431238966182398,
    variable_name='computed_value'
)
# Returns: {'total': 1500, 'count': 30}
```

#### Get All Variables

```python
variables = await ExecutionVariables.get_all_variables(
    execution_id=507431238966182398
)
# Returns: {'oauth_token': 'eyJ...', 'step1': {...}, 'computed_value': {...}}
```

#### Store Bearer Token

```python
await ExecutionVariables.set_bearer_token(
    execution_id=507431238966182398,
    variable_name='amadeus_token',
    token_value='eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...',
    source_step='get_amadeus_token'
)
```

#### Store Step Result (Automatic)

```python
await ExecutionVariables.set_step_result(
    execution_id=507431238966182398,
    step_name='fetch_data',
    result={'data': [...], 'status': 'success'}
)
```

#### Cleanup Execution

```python
await ExecutionVariables.cleanup_execution(
    execution_id=507431238966182398
)
```

## Integration with Jinja2 Context

### Context Extension

Before rendering any template, execution variables are automatically merged into the Jinja2 context:

```python
from noetl.worker.execution_variables import extend_context_with_variables

# Base context
context = {
    'workload': {...},
    'spec': {...},
    'job': {...}
}

# Extend with execution variables
extended_context = await extend_context_with_variables(
    context=context,
    execution_id=507431238966182398
)

# Now includes all execution variables:
# {
#   'workload': {...},
#   'spec': {...},
#   'job': {...},
#   'oauth_token': 'eyJ...',        # Bearer token
#   'fetch_data': {'data': [...]},  # Step result
#   'computed_value': {...}         # Computed variable
# }
```

### Template Access Patterns

#### Bearer Tokens in Headers

```yaml
headers:
  Authorization: Bearer {{ oauth_token }}
  X-API-Key: {{ api_key_var }}
```

#### Step Results in Args

```yaml
args:
  previous_data: '{{ fetch_data.data }}'
  status: '{{ fetch_data.status }}'
```

#### Computed Values in Conditions

```yaml
next:
  - when: "{{ computed_value.total > 1000 }}"
    then:
      - step: high_volume_handler
```

## Complete Example: Amadeus AI API

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: amadeus_ai_api
  path: api_integration/amadeus_ai_api

workload:
  pg_auth: pg_local
  openai_auth: openai_api_key
  amadeus_api_auth: amadeus_api_credentials
  query: I want a one-way flight from SFO to JFK on September 15, 2025 for 1 adult

workflow:
# Step 1: Get Amadeus OAuth token with bearer variable assignment
- step: get_amadeus_token
  desc: Get Amadeus API access token
  tool: python
  auth:
    credential: '{{ workload.amadeus_api_auth }}'
    bearer: true
    variable: amadeus_token  # Stored as execution variable
  code: |
    def main(auth_credential):
        import httpx
        response = httpx.post(
            "https://test.api.amadeus.com/v1/security/oauth2/token",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "grant_type": "client_credentials",
                "client_id": auth_credential["client_id"],
                "client_secret": auth_credential["client_secret"]
            }
        )
        token_data = response.json()
        return token_data["access_token"]
  next:
    - step: translate_query

# Step 2: Use OpenAI with auth credential
- step: translate_query
  desc: Convert query to Amadeus API parameters
  tool: http
  method: POST
  endpoint: https://api.openai.com/v1/chat/completions
  auth: '{{ workload.openai_auth }}'  # Auto-handled by auth system
  payload:
    model: gpt-4o
    messages:
      - role: system
        content: "Translate travel queries to API parameters..."
      - role: user
        content: '{{ workload.query }}'
  next:
    - step: parse_response

# Step 3: Parse OpenAI response (result stored as execution variable)
- step: parse_response
  desc: Extract endpoint and params
  tool: python
  args:
    openai_response: '{{ translate_query.data }}'  # Step result variable
  code: |
    def main(openai_response):
        import json
        content = openai_response['choices'][0]['message']['content']
        parsed = json.loads(content)
        return {
            "endpoint": parsed["endpoint"],
            "params": parsed["params"]
        }
  next:
    - step: call_amadeus_api

# Step 4: Use bearer token from execution variable
- step: call_amadeus_api
  desc: Execute Amadeus API query
  tool: http
  method: GET
  endpoint: https://test.api.amadeus.com{{ parse_response.endpoint }}
  headers:
    Authorization: Bearer {{ amadeus_token }}  # Variable from step 1
    Content-Type: application/json
  next:
    - step: end

- step: end
  desc: Workflow complete
```

## Variable Lifecycle

### Creation
1. **Bearer Token**: Created when step with `auth.bearer: true` completes successfully
2. **Step Result**: Created automatically after every step execution
3. **Computed**: Created explicitly via `ExecutionVariables.set_variable()`

### Access
- Available in Jinja2 templates throughout execution
- Accessible via `{{ variable_name }}` or `{{ variable_name.field }}`
- Retrieved programmatically via `ExecutionVariables.get_variable()`

### Cleanup
- Automatic cleanup when execution completes (success or failure)
- Manual cleanup via `ExecutionVariables.cleanup_execution()`
- No cross-execution leakage

## Monitoring

### Query Execution Variables

```sql
-- Current variables for an execution
SELECT 
    variable_name,
    variable_type,
    source_step,
    created_at
FROM noetl.execution_variable
WHERE execution_id = 507431238966182398
ORDER BY created_at ASC;

-- Bearer tokens across executions
SELECT 
    execution_id,
    variable_name,
    source_step,
    created_at
FROM noetl.execution_variable
WHERE variable_type = 'bearer_token'
ORDER BY created_at DESC
LIMIT 100;

-- Variable usage patterns
SELECT 
    variable_type,
    COUNT(*) as count,
    COUNT(DISTINCT execution_id) as executions
FROM noetl.execution_variable
GROUP BY variable_type;
```

## Best Practices

### 1. Naming Conventions

```yaml
# ✅ Good: descriptive, lowercase with underscores
variable: amadeus_token
variable: gcp_access_token
variable: computed_metrics

# ❌ Bad: unclear, camelCase, generic
variable: token
variable: myToken
variable: var1
```

### 2. Token Return Format

```python
# ✅ Good: return just the token string
def main(auth_credential):
    token_data = fetch_token(auth_credential)
    return token_data["access_token"]

# ❌ Bad: return full response (auth system won't extract token)
def main(auth_credential):
    token_data = fetch_token(auth_credential)
    return token_data  # Contains expires_in, token_type, etc.
```

### 3. Error Handling

```python
# ✅ Good: return error dict or raise exception
def main(auth_credential):
    try:
        return fetch_token(auth_credential)
    except Exception as e:
        return {"error": str(e), "status": "failed"}

# ❌ Bad: return None (variable will be set to None)
def main(auth_credential):
    try:
        return fetch_token(auth_credential)
    except:
        return None
```

### 4. Variable Scope

```yaml
# ✅ Good: use variable in same execution
- step: get_token
  auth:
    bearer: true
    variable: my_token

- step: use_token
  headers:
    Authorization: Bearer {{ my_token }}

# ❌ Bad: expecting variable from previous execution
# Variables are execution-scoped only
```

## Security Considerations

### Storage
- Variables stored as JSONB in PostgreSQL
- Bearer tokens stored in plaintext (use encrypted connection to DB)
- Credentials fetched via auth system remain encrypted in cache

### Access Control
- Variables accessible only within same execution
- No cross-execution variable access
- Automatic cleanup prevents leakage

### Audit Trail
- All variable operations logged
- Source step tracked for bearer tokens
- Created/updated timestamps available

## Future Enhancements

### Planned Features
- **Global Variables**: Cross-execution shared variables with TTL
- **Variable Encryption**: Encrypt sensitive variable values at rest
- **Variable Versioning**: Track variable value history
- **Variable Policies**: TTL, access control, validation rules

### NATS KV Backend
- Distributed variable storage across workers
- Pub/sub for variable updates
- Lower latency for high-throughput workflows

## Related Documentation

- [Credential Caching](./credential_caching.md)
- [Token-Based Authentication](./token_auth_implementation.md)
- [HTTP Action Type](./http_action_type.md)
- [Template Rendering](./dsl_spec.md#jinja2-templates)
