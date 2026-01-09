---
sidebar_position: 1
title: Auth0 Integration
description: Authenticate users with Auth0 OAuth
---

# Auth0 Integration Example

This example demonstrates integrating Auth0 authentication with NoETL for user session management.

:::tip Working Examples
Complete OAuth playbooks are available in the repository:
- [tests/fixtures/playbooks/oauth/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/oauth) - Google OAuth, GCS, Secret Manager
- [tests/fixtures/playbooks/api_integration/](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/api_integration) - Auth0 integration
:::

## Overview

The Auth0 integration implements OAuth Implicit Flow for browser-based authentication:
1. User clicks "Sign In with Auth0"
2. Auth0 redirects back with JWT token
3. NoETL playbook validates token and creates session
4. Session token stored for subsequent API calls

## Prerequisites

- Auth0 application configured
- PostgreSQL database
- NoETL server running

## Database Schema

First, provision the authentication schema:

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: provision_auth_schema
  path: api_integration/auth0/provision_auth_schema

workbook:
  - name: create_schema
    tool: postgres
    auth:
      type: postgres
      credential: pg_demo
    query: |
      CREATE SCHEMA IF NOT EXISTS auth;
      
      CREATE TABLE IF NOT EXISTS auth.users (
        id SERIAL PRIMARY KEY,
        user_id VARCHAR(255) UNIQUE NOT NULL,
        email VARCHAR(255) UNIQUE,
        auth0_id VARCHAR(255) UNIQUE NOT NULL,
        name VARCHAR(255),
        is_active BOOLEAN DEFAULT true,
        created_at TIMESTAMP DEFAULT NOW(),
        updated_at TIMESTAMP DEFAULT NOW()
      );
      
      CREATE TABLE IF NOT EXISTS auth.sessions (
        id SERIAL PRIMARY KEY,
        session_token VARCHAR(255) UNIQUE NOT NULL,
        user_id VARCHAR(255) REFERENCES auth.users(user_id),
        created_at TIMESTAMP DEFAULT NOW(),
        expires_at TIMESTAMP DEFAULT NOW() + INTERVAL '24 hours',
        is_valid BOOLEAN DEFAULT true
      );

workflow:
  - step: start
    next:
      - step: create_schema

  - step: create_schema
    tool: workbook
    name: create_schema
    next:
      - step: end

  - step: end
```

## Login Playbook

The main authentication playbook:

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: auth0_login
  path: api_integration/auth0/auth0_login

workload:
  auth0_token: ""  # JWT from Auth0 callback
  client_ip: "127.0.0.1"

workbook:
  - name: decode_jwt
    tool: python
    code: |
      import base64
      import json
      
      def main(token):
          """Decode JWT without external libraries."""
          parts = token.split('.')
          if len(parts) != 3:
              return {"error": "Invalid JWT format"}
          
          payload = parts[1]
          # Add padding if needed
          padding = 4 - (len(payload) % 4)
          if padding != 4:
              payload += '=' * padding
          
          decoded = json.loads(base64.urlsafe_b64decode(payload))
          return {
              "sub": decoded.get("sub"),
              "email": decoded.get("email"),
              "name": decoded.get("name"),
              "email_verified": decoded.get("email_verified", False)
          }

  - name: upsert_user
    tool: postgres
    auth:
      type: postgres
      credential: pg_demo
    query: |
      INSERT INTO auth.users (user_id, email, auth0_id, name)
      VALUES (
        '{{ vars.auth0_id }}',
        '{{ vars.email }}',
        '{{ vars.auth0_id }}',
        '{{ vars.name }}'
      )
      ON CONFLICT (auth0_id) DO UPDATE SET
        email = EXCLUDED.email,
        name = EXCLUDED.name,
        updated_at = NOW()
      RETURNING user_id;

  - name: create_session
    tool: postgres
    auth:
      type: postgres
      credential: pg_demo
    query: |
      INSERT INTO auth.sessions (session_token, user_id)
      VALUES (
        md5(random()::text || clock_timestamp()::text),
        '{{ vars.user_id }}'
      )
      RETURNING session_token;

workflow:
  - step: start
    next:
      - step: decode_token

  - step: decode_token
    tool: workbook
    name: decode_jwt
    args:
      token: "{{ workload.auth0_token }}"
    vars:
      auth0_id: "{{ result.data.sub }}"
      email: "{{ result.data.email }}"
      name: "{{ result.data.name }}"
    next:
      - when: "{{ vars.auth0_id is defined }}"
        then:
          - step: upsert_user
      - step: auth_failed

  - step: upsert_user
    tool: workbook
    name: upsert_user
    vars:
      user_id: "{{ result.data.command_1[0].user_id }}"
    next:
      - step: create_session

  - step: create_session
    tool: workbook
    name: create_session
    vars:
      session_token: "{{ result.data.command_1[0].session_token }}"
    next:
      - step: success

  - step: success
    tool: python
    code: |
      def main(session_token, user_id, email):
          return {
              "status": "success",
              "session_token": session_token,
              "user_id": user_id,
              "email": email
          }
    args:
      session_token: "{{ vars.session_token }}"
      user_id: "{{ vars.user_id }}"
      email: "{{ vars.email }}"
    next:
      - step: end

  - step: auth_failed
    tool: python
    code: |
      def main():
          return {"status": "error", "message": "Authentication failed"}
    next:
      - step: end

  - step: end
```

## Session Validation

Validate session tokens for protected routes:

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: auth0_validate_session
  path: api_integration/auth0/auth0_validate_session

workload:
  session_token: ""

workbook:
  - name: validate
    tool: postgres
    auth:
      type: postgres
      credential: pg_demo
    query: |
      SELECT 
        s.session_token,
        s.user_id,
        u.email,
        u.name,
        s.expires_at > NOW() AS is_valid
      FROM auth.sessions s
      JOIN auth.users u ON s.user_id = u.user_id
      WHERE s.session_token = '{{ workload.session_token }}'
        AND s.is_valid = true
        AND s.expires_at > NOW();

workflow:
  - step: start
    next:
      - step: validate

  - step: validate
    tool: workbook
    name: validate
    vars:
      session_valid: "{{ result.data.command_1 | length > 0 }}"
      user_data: "{{ result.data.command_1[0] if result.data.command_1 else {} }}"
    next:
      - when: "{{ vars.session_valid }}"
        then:
          - step: valid_session
      - step: invalid_session

  - step: valid_session
    tool: python
    code: |
      def main(user_data):
          return {
              "status": "valid",
              "user_id": user_data.get("user_id"),
              "email": user_data.get("email"),
              "name": user_data.get("name")
          }
    args:
      user_data: "{{ vars.user_data }}"
    next:
      - step: end

  - step: invalid_session
    tool: python
    code: |
      def main():
          return {"status": "invalid", "message": "Session expired or invalid"}
    next:
      - step: end

  - step: end
```

## Frontend Integration

Example JavaScript for handling Auth0 callback:

```javascript
// Handle Auth0 callback
const hashParams = new URLSearchParams(window.location.hash.substring(1));
const idToken = hashParams.get('id_token');

if (idToken) {
    // Call NoETL playbook
    const response = await fetch('/api/execute', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
            path: 'api_integration/auth0/auth0_login',
            payload: {
                auth0_token: idToken,
                client_ip: '127.0.0.1'
            }
        })
    });
    
    const result = await response.json();
    if (result.status === 'success') {
        localStorage.setItem('session_token', result.session_token);
        window.location.href = '/dashboard.html';
    }
}
```

## Testing

```bash
# 1. Register the playbooks
noetl run playbook tests/fixtures/playbooks/api_integration/auth0/provision_auth_schema.yaml

# 2. Test login flow with a mock token
curl -X POST http://localhost:8082/api/execute \
  -H 'Content-Type: application/json' \
  -d '{
    "path": "api_integration/auth0/auth0_login",
    "payload": {
      "auth0_token": "eyJ...",
      "client_ip": "127.0.0.1"
    }
  }'

# 3. Validate session
curl -X POST http://localhost:8082/api/execute \
  -H 'Content-Type: application/json' \
  -d '{
    "path": "api_integration/auth0/auth0_validate_session",
    "payload": {
      "session_token": "abc123..."
    }
  }'
```

## See Also

- [Authentication Reference](/docs/reference/auth_and_keychain_reference)
- [PostgreSQL Tool](/docs/reference/tools/postgres)
- [Python Tool](/docs/reference/tools/python)
