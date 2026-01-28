---
sidebar_position: 6
title: API Usage Guide
description: How to authenticate and call playbooks via the NoETL Gateway API
---

# Gateway API Usage Guide

This guide explains how developers can authenticate via Auth0 and use the Gateway API to execute NoETL playbooks.

## Authentication Flow

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│   Your App   │───▶│    Auth0     │───▶│   Gateway    │───▶│   NoETL      │
│              │    │   Login      │    │  /api/auth   │    │  Playbook    │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
       │                   │                    │                   │
       │  1. Redirect      │                    │                   │
       │─────────────────▶│                    │                   │
       │                   │                    │                   │
       │  2. User Login    │                    │                   │
       │◀─────────────────│                    │                   │
       │     (id_token)    │                    │                   │
       │                   │                    │                   │
       │  3. Exchange token for session        │                   │
       │──────────────────────────────────────▶│                   │
       │                   │                    │  4. Validate &    │
       │                   │                    │     Create Session│
       │                   │                    │──────────────────▶│
       │                   │                    │◀──────────────────│
       │  5. session_token │                    │                   │
       │◀──────────────────────────────────────│                   │
       │                   │                    │                   │
       │  6. Call /graphql with session_token  │                   │
       │──────────────────────────────────────▶│  7. Execute       │
       │                   │                    │──────────────────▶│
       │                   │                    │◀──────────────────│
       │  8. Playbook result                   │                   │
       │◀──────────────────────────────────────│                   │
```

## Step 1: Auth0 Authentication

### Option A: Browser-based (Implicit Flow)

Redirect users to Auth0 Universal Login:

```javascript
const auth0Domain = 'your-tenant.us.auth0.com';
const clientId = 'YOUR_CLIENT_ID';
const redirectUri = 'https://your-app.com/callback';

const authUrl = `https://${auth0Domain}/authorize?` +
  `response_type=id_token token&` +
  `client_id=${clientId}&` +
  `redirect_uri=${encodeURIComponent(redirectUri)}&` +
  `scope=openid profile email&` +
  `nonce=${Math.random().toString(36).substring(7)}`;

window.location.href = authUrl;
```

### Option B: Backend (Authorization Code Flow)

For server-side applications, use the Authorization Code flow with PKCE.

## Step 2: Exchange Auth0 Token for Session

After Auth0 authentication, exchange the `id_token` for a Gateway session token:

```bash
curl -X POST https://gateway.mestumre.dev/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "auth0_token": "eyJhbGciOiJSUzI1NiIs...",
    "auth0_domain": "your-tenant.us.auth0.com",
    "session_duration_hours": 8
  }'
```

**Response:**

```json
{
  "status": "authenticated",
  "session_token": "d23c3024d55b4d0faea4886eb13c2347",
  "user": {
    "user_id": 1,
    "email": "user@example.com",
    "display_name": "User Name"
  },
  "expires_at": "2026-01-28T22:11:41.335589+00:00",
  "message": "Authentication successful"
}
```

**Store the `session_token`** - you'll need it for all subsequent API calls.

## Step 3: Execute Playbooks via GraphQL

Once authenticated, use the `/graphql` endpoint to execute playbooks:

### Basic Playbook Execution

```bash
curl -X POST https://gateway.mestumre.dev/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -d '{
    "query": "mutation { executePlaybook(name: \"my_playbook\", variables: {}) { executionId } }"
  }'
```

### Playbook with Variables

```bash
curl -X POST https://gateway.mestumre.dev/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -d '{
    "query": "mutation ExecutePlaybook($name: String!, $vars: JSON!) { executePlaybook(name: $name, variables: $vars) { executionId status } }",
    "variables": {
      "name": "data_pipeline/transform_data",
      "vars": {
        "input_file": "gs://bucket/input.csv",
        "output_format": "parquet"
      }
    }
  }'
```

**Response:**

```json
{
  "data": {
    "executePlaybook": {
      "executionId": "549325390032929117",
      "status": "running"
    }
  }
}
```

### Check Execution Status

```bash
curl -X POST https://gateway.mestumre.dev/graphql \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -d '{
    "query": "query GetStatus($id: String!) { executionStatus(executionId: $id) { executionId status completed variables } }",
    "variables": {
      "id": "549325390032929117"
    }
  }'
```

## JavaScript/TypeScript Example

```typescript
class NoETLGatewayClient {
  private baseUrl: string;
  private sessionToken: string | null = null;

  constructor(baseUrl: string = 'https://gateway.mestumre.dev') {
    this.baseUrl = baseUrl;
  }

  // Exchange Auth0 token for session
  async login(auth0Token: string, auth0Domain: string): Promise<void> {
    const response = await fetch(`${this.baseUrl}/api/auth/login`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        auth0_token: auth0Token,
        auth0_domain: auth0Domain,
        session_duration_hours: 8
      })
    });

    if (!response.ok) {
      throw new Error(`Login failed: ${response.status}`);
    }

    const data = await response.json();
    this.sessionToken = data.session_token;
  }

  // Execute a playbook
  async executePlaybook(name: string, variables: Record<string, any> = {}): Promise<string> {
    if (!this.sessionToken) {
      throw new Error('Not authenticated. Call login() first.');
    }

    const response = await fetch(`${this.baseUrl}/graphql`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.sessionToken}`
      },
      body: JSON.stringify({
        query: `
          mutation ExecutePlaybook($name: String!, $vars: JSON!) {
            executePlaybook(name: $name, variables: $vars) {
              executionId
              status
            }
          }
        `,
        variables: { name, vars: variables }
      })
    });

    const result = await response.json();

    if (result.errors) {
      throw new Error(result.errors[0].message);
    }

    return result.data.executePlaybook.executionId;
  }

  // Check execution status
  async getExecutionStatus(executionId: string): Promise<any> {
    if (!this.sessionToken) {
      throw new Error('Not authenticated. Call login() first.');
    }

    const response = await fetch(`${this.baseUrl}/graphql`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.sessionToken}`
      },
      body: JSON.stringify({
        query: `
          query GetStatus($id: String!) {
            executionStatus(executionId: $id) {
              executionId
              status
              completed
              variables
            }
          }
        `,
        variables: { id: executionId }
      })
    });

    const result = await response.json();
    return result.data.executionStatus;
  }

  // Validate current session
  async validateSession(): Promise<boolean> {
    if (!this.sessionToken) return false;

    const response = await fetch(`${this.baseUrl}/api/auth/validate`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ session_token: this.sessionToken })
    });

    if (!response.ok) return false;

    const data = await response.json();
    return data.valid === true;
  }
}

// Usage example
async function main() {
  const client = new NoETLGatewayClient();

  // After Auth0 callback, get the id_token from URL hash
  const urlParams = new URLSearchParams(window.location.hash.substring(1));
  const idToken = urlParams.get('id_token');

  // Login to gateway
  await client.login(idToken, 'your-tenant.us.auth0.com');

  // Execute a playbook
  const executionId = await client.executePlaybook('data_pipeline/my_playbook', {
    input: 'test-data',
    mode: 'production'
  });

  console.log('Execution started:', executionId);

  // Poll for completion
  let status;
  do {
    await new Promise(resolve => setTimeout(resolve, 1000));
    status = await client.getExecutionStatus(executionId);
    console.log('Status:', status.status);
  } while (!status.completed);

  console.log('Result:', status.variables);
}
```

## Python Example

```python
import requests
from typing import Optional, Dict, Any

class NoETLGatewayClient:
    def __init__(self, base_url: str = "https://gateway.mestumre.dev"):
        self.base_url = base_url
        self.session_token: Optional[str] = None

    def login(self, auth0_token: str, auth0_domain: str, duration_hours: int = 8) -> Dict[str, Any]:
        """Exchange Auth0 token for gateway session."""
        response = requests.post(
            f"{self.base_url}/api/auth/login",
            json={
                "auth0_token": auth0_token,
                "auth0_domain": auth0_domain,
                "session_duration_hours": duration_hours
            }
        )
        response.raise_for_status()
        data = response.json()
        self.session_token = data["session_token"]
        return data

    def _graphql(self, query: str, variables: Dict[str, Any] = None) -> Dict[str, Any]:
        """Execute GraphQL query."""
        if not self.session_token:
            raise ValueError("Not authenticated. Call login() first.")

        response = requests.post(
            f"{self.base_url}/graphql",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.session_token}"
            },
            json={"query": query, "variables": variables or {}}
        )
        response.raise_for_status()
        result = response.json()

        if "errors" in result:
            raise Exception(result["errors"][0]["message"])

        return result["data"]

    def execute_playbook(self, name: str, variables: Dict[str, Any] = None) -> str:
        """Execute a playbook and return execution ID."""
        query = """
            mutation ExecutePlaybook($name: String!, $vars: JSON!) {
                executePlaybook(name: $name, variables: $vars) {
                    executionId
                    status
                }
            }
        """
        result = self._graphql(query, {"name": name, "vars": variables or {}})
        return result["executePlaybook"]["executionId"]

    def get_execution_status(self, execution_id: str) -> Dict[str, Any]:
        """Get execution status."""
        query = """
            query GetStatus($id: String!) {
                executionStatus(executionId: $id) {
                    executionId
                    status
                    completed
                    variables
                }
            }
        """
        result = self._graphql(query, {"id": execution_id})
        return result["executionStatus"]

    def wait_for_completion(self, execution_id: str, poll_interval: float = 1.0) -> Dict[str, Any]:
        """Wait for playbook execution to complete."""
        import time
        while True:
            status = self.get_execution_status(execution_id)
            if status["completed"]:
                return status
            time.sleep(poll_interval)


# Usage example
if __name__ == "__main__":
    client = NoETLGatewayClient()

    # Login with Auth0 token (obtained from Auth0 authentication)
    auth0_token = "eyJhbGciOiJSUzI1NiIs..."
    client.login(auth0_token, "your-tenant.us.auth0.com")

    # Execute a playbook
    execution_id = client.execute_playbook(
        "data_pipeline/transform_data",
        {"input_file": "data.csv", "output_format": "parquet"}
    )
    print(f"Execution started: {execution_id}")

    # Wait for completion
    result = client.wait_for_completion(execution_id)
    print(f"Result: {result['variables']}")
```

## API Reference

### Authentication Endpoints

#### POST /api/auth/login

Exchange Auth0 token for a session token.

**Request:**
```json
{
  "auth0_token": "string (required) - Auth0 id_token",
  "auth0_domain": "string (required) - Auth0 tenant domain",
  "session_duration_hours": "integer (optional, default: 8)"
}
```

**Response (200):**
```json
{
  "status": "authenticated",
  "session_token": "string",
  "user": {
    "user_id": "integer",
    "email": "string",
    "display_name": "string"
  },
  "expires_at": "ISO8601 timestamp",
  "message": "Authentication successful"
}
```

**Errors:**
- `401` - Invalid Auth0 token
- `500` - Internal error

#### POST /api/auth/validate

Validate a session token.

**Request:**
```json
{
  "session_token": "string (required)"
}
```

**Response (200):**
```json
{
  "valid": true,
  "user": {
    "user_id": "integer",
    "email": "string",
    "display_name": "string"
  },
  "expires_at": "ISO8601 timestamp"
}
```

#### POST /api/auth/check-access

Check if user has access to a specific playbook.

**Request:**
```json
{
  "session_token": "string (required)",
  "playbook_name": "string (required)"
}
```

**Response (200):**
```json
{
  "allowed": true,
  "playbook_name": "string",
  "user_id": "integer"
}
```

### GraphQL Endpoint

#### POST /graphql

Execute GraphQL queries/mutations. Requires `Authorization: Bearer <session_token>` header.

**Available Operations:**

```graphql
# Execute a playbook
mutation ExecutePlaybook($name: String!, $vars: JSON!) {
  executePlaybook(name: $name, variables: $vars) {
    executionId
    status
  }
}

# Get execution status
query GetExecutionStatus($id: String!) {
  executionStatus(executionId: $id) {
    executionId
    status
    completed
    failed
    currentStep
    completedSteps
    variables
  }
}

# List playbooks
query ListPlaybooks {
  playbooks {
    name
    description
    variables
  }
}
```

## Error Handling

### Common Error Responses

```json
{
  "error": "Error message description"
}
```

| Status Code | Meaning |
|-------------|---------|
| 400 | Bad request - invalid input |
| 401 | Unauthorized - invalid or expired session |
| 403 | Forbidden - no access to resource |
| 404 | Not found - playbook doesn't exist |
| 500 | Internal server error |
| 502 | Bad gateway - NoETL server unreachable |

### Session Expiration

Sessions expire after the configured duration (default: 8 hours). When a session expires:

1. API calls will return `401 Unauthorized`
2. Re-authenticate via Auth0 to get a new session

```javascript
// Handle session expiration
async function callAPI(endpoint, options) {
  const response = await fetch(endpoint, options);

  if (response.status === 401) {
    // Session expired, redirect to Auth0 login
    redirectToAuth0Login();
    return;
  }

  return response.json();
}
```

## Best Practices

1. **Store session tokens securely** - Use HttpOnly cookies or secure storage
2. **Handle token expiration** - Implement automatic re-authentication
3. **Use HTTPS** - Always use HTTPS in production
4. **Validate sessions periodically** - Check session validity before critical operations
5. **Log out properly** - Clear session tokens on logout

## Troubleshooting

### "Invalid or expired session"

- Session token has expired - re-authenticate via Auth0
- Session token is malformed - check token format

### "No access to playbook"

- User doesn't have permission - check playbook access configuration
- Playbook name is incorrect - verify playbook path

### CORS Errors

- Add your origin to `corsAllowedOrigins` in gateway configuration
- Ensure Cloudflare cache bypass is configured for API endpoints

### "NoETL server unreachable"

- Check NoETL server is running
- Verify `NOETL_BASE_URL` configuration in gateway
