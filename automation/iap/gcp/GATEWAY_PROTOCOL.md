# NoETL Gateway - Data Exchange Protocol

This document describes how external applications authenticate and communicate with NoETL via the Gateway.

## Architecture Summary

```
External App → Gateway (Public LoadBalancer) → NoETL Server (Internal ClusterIP) → PostgreSQL/NATS/ClickHouse
                 │
                 └─ Auth0 Token Validation (via NoETL playbooks)
```

**Key Points:**
- **Gateway** is the only public entry point (LoadBalancer on port 8090)
- **NoETL Server** is internal only (ClusterIP on port 8082)
- **Authentication** is handled by Gateway middleware calling NoETL auth playbooks
- **All playbook execution** goes through GraphQL API on Gateway

## Authentication Flow

### Step 1: Obtain Auth0 Token
External application authenticates with Auth0 to get an access token.

### Step 2: Exchange Auth0 Token for Session Token

```bash
POST http://<GATEWAY_IP>:8090/api/auth/login
Content-Type: application/json

{
  "auth0_token": "<AUTH0_ACCESS_TOKEN>",
  "auth0_domain": "your-tenant.auth0.com",
  "session_duration_hours": 8
}
```

**Response:**
```json
{
  "status": "authenticated",
  "session_token": "noetl-session-abc123...",
  "user": {
    "user_id": 1,
    "email": "user@example.com",
    "display_name": "User Name"
  },
  "expires_at": "2026-01-26T08:00:00Z"
}
```

### Step 3: Use Session Token for API Calls

Include the session token in all subsequent requests:

```
Authorization: Bearer noetl-session-abc123...
```

## GraphQL API

### Execute Playbook

```bash
POST http://<GATEWAY_IP>:8090/graphql
Content-Type: application/json
Authorization: Bearer <SESSION_TOKEN>

{
  "query": "mutation Execute($name: String!, $vars: JSON) { executePlaybook(name: $name, variables: $vars) { id name status textOutput } }",
  "variables": {
    "name": "api_integration/amadeus_ai_api",
    "vars": {
      "query": "Flight from SFO to JFK"
    }
  }
}
```

**Response:**
```json
{
  "data": {
    "executePlaybook": {
      "id": "exec-12345",
      "name": "amadeus_ai_api",
      "status": "running",
      "textOutput": null
    }
  }
}
```

### Check Execution Status

Poll the execution status:

```bash
POST http://<GATEWAY_IP>:8090/graphql
Content-Type: application/json
Authorization: Bearer <SESSION_TOKEN>

{
  "query": "query Status($id: ID!) { execution(id: $id) { id status result } }",
  "variables": {
    "id": "exec-12345"
  }
}
```

## API Endpoints Summary

| Method | Endpoint | Auth Required | Description |
|--------|----------|---------------|-------------|
| POST | `/api/auth/login` | No | Exchange Auth0 token for session |
| POST | `/api/auth/validate` | No | Validate session token |
| POST | `/api/auth/check-access` | No | Check playbook access permission |
| GET | `/health` | No | Health check |
| POST | `/graphql` | Yes | Execute playbooks (GraphQL) |
| GET | `/graphql` | No | GraphiQL playground |

## Session Token Delivery

Session tokens can be provided in three ways (checked in order):

1. **Authorization Header** (recommended):
   ```
   Authorization: Bearer <session_token>
   ```

2. **X-Session-Token Header**:
   ```
   X-Session-Token: <session_token>
   ```

3. **Cookie**:
   ```
   Cookie: session_token=<session_token>
   ```

## Example: Complete Flow

```bash
# 1. Get Gateway external IP
GATEWAY_IP=$(kubectl get svc noetl-gateway -n gateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')

# 2. Login with Auth0 token
SESSION=$(curl -s -X POST "http://$GATEWAY_IP:8090/api/auth/login" \
  -H "Content-Type: application/json" \
  -d '{"auth0_token": "'$AUTH0_TOKEN'", "auth0_domain": "your-tenant.auth0.com"}' \
  | jq -r '.session_token')

# 3. Execute a playbook
EXEC_ID=$(curl -s -X POST "http://$GATEWAY_IP:8090/graphql" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $SESSION" \
  -d '{
    "query": "mutation { executePlaybook(name: \"regression_test/hello_world\") { id status } }",
    "variables": {}
  }' | jq -r '.data.executePlaybook.id')

echo "Execution ID: $EXEC_ID"

# 4. Check status (poll until completed)
curl -s -X POST "http://$GATEWAY_IP:8090/graphql" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $SESSION" \
  -d '{
    "query": "query { execution(id: \"'$EXEC_ID'\") { id status result } }"
  }' | jq .
```

## Permissions Model

Access is controlled by:
1. **Roles**: admin, developer, analyst, viewer
2. **Permissions**: execute, view, edit, delete
3. **Playbook Patterns**: Wildcard patterns matching playbook paths

Example: Grant execute permission on all `api_integration/*` playbooks to `developer` role.

## In-Cluster Access

For internal services (running in the same cluster), you can access NoETL server directly:

```
http://noetl.noetl.svc.cluster.local:8082
```

This bypasses Gateway authentication - use for trusted internal services only.

## Related Documentation

- [Gateway Auth Integration](../../../crates/gateway/AUTH_INTEGRATION.md)
- [Gateway README](../../../crates/gateway/README.md)
- [Auth0 Playbooks](../../../tests/fixtures/playbooks/api_integration/auth0/)
- [GKE Deployment](./README.md)
