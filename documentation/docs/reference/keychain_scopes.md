---
sidebar_position: 6
title: Keychain Scopes Explained
description: Clear explanation of keychain scope types - local, global, and shared
---

# Keychain Scopes Explained

NoETL keychain system supports three scope types that control how keychain entries are shared and accessed across executions.

## Quick Reference

| Scope | Who Can Access | Lifetime | Best For |
|-------|----------------|----------|----------|
| **local** | Single execution only | Until execution completes | User sessions, execution-specific tokens |
| **global** | All executions of playbook | Until token expires | API keys, shared service tokens |
| **shared** | Execution tree (parent + children) | Until root completes | Multi-level orchestration |

## Scope Types

### Local Scope (Execution-Scoped)

**Isolation Level:** Single execution  
**Cache Key:** `{name}:{catalog_id}:{execution_id}`

Each execution gets its own isolated keychain entry. No sharing between executions - not even with child playbooks.

```yaml
keychain:
  - name: user_session
    kind: oauth2
    scope: local  # Execution-scoped isolation
    endpoint: https://auth.example.com/login
    data:
      username: "{{ workload.username }}"
      password: "{{ workload.password }}"
```

**Access Rules:**
- ✅ The execution that created it
- ❌ Child playbooks (sub-playbooks)
- ❌ Parent execution
- ❌ Sibling executions
- ❌ Other executions

**When to Use:**
- User-specific authentication tokens
- Execution-specific temporary credentials
- Per-run isolated state
- Testing with different credentials per execution

**Example Scenario:**
```
Execution 123: Creates local keychain "user_session" → Only 123 can access
Execution 456: Creates local keychain "user_session" → Only 456 can access
Both are completely isolated, even if they run the same playbook
```

---

### Global Scope (Playbook-Wide)

**Isolation Level:** All executions of the playbook  
**Cache Key:** `{name}:{catalog_id}:global`

Shared across all executions of the playbook. Most efficient for high-concurrency scenarios.

```yaml
keychain:
  - name: api_token
    kind: oauth2
    scope: global  # Shared across all executions
    auto_renew: true
    endpoint: https://api.example.com/oauth/token
```

**Access Rules:**
- ✅ All executions of this playbook
- ✅ Concurrent executions
- ✅ Past and future executions
- ✅ Child playbooks (via inheritance)

**When to Use:**
- Service-to-service authentication
- API keys that don't change per execution
- Rate-limited APIs (share token across executions)
- High-concurrency workloads (avoid duplicate token requests)

**Example Scenario:**
```
Playbook: "data-sync" (catalog_id: 12345)
- Execution 100: Uses api_token (fetches it)
- Execution 101: Uses api_token (cached from 100)
- Execution 102: Uses api_token (cached from 100)
All three share the same token
```

---

### Shared Scope (Execution Tree)

**Isolation Level:** Parent + all descendants  
**Cache Key:** `{name}:{catalog_id}:shared:{execution_id}`

Accessible by the entire execution tree - parent and all child/grandchild playbooks.

```yaml
keychain:
  - name: orchestration_context
    kind: http
    scope: shared  # Accessible by execution tree
    endpoint: https://api.example.com/initialize
    method: POST
    data:
      project_id: "{{ workload.project_id }}"
```

**Execution Tree Example:**
```
Playbook A (execution 100) → Creates shared keychain "orchestration_context"
├── Playbook B (execution 200) → Can access "orchestration_context"
│   └── Playbook C (execution 300) → Can access "orchestration_context"
└── Playbook D (execution 400) → Can access "orchestration_context"

All executions in tree can access the shared keychain
```

**Access Rules:**
- ✅ Parent execution (creator)
- ✅ Direct children (sub-playbooks)
- ✅ All descendants (grandchildren, etc.)
- ❌ Sibling execution trees
- ❌ Unrelated executions

**When to Use:**
- Multi-level playbook orchestration
- Passing authentication context through call chain
- Initialization state needed by sub-playbooks
- Parent-child coordination

**Example Scenario:**
```
Main orchestrator playbook:
- Creates shared keychain with project context
- Calls data-ingestion playbook (child)
  - Calls validation playbook (grandchild)
    - All can access the project context from parent
- Calls reporting playbook (child)
  - Can also access the project context

Separate orchestrator execution:
- Cannot access the other tree's shared keychain
```

---

## Choosing the Right Scope

### Use **local** when:
- Each execution needs its own isolated credentials
- Testing with different users/credentials
- User-specific session tokens
- Execution-specific temporary state

### Use **global** when:
- Token/credential is the same for all executions
- High concurrency (share token to avoid rate limits)
- Service-to-service authentication
- Long-lived API keys

### Use **shared** when:
- Parent playbook calls sub-playbooks (orchestration)
- Child playbooks need parent's authentication
- Multi-level workflow coordination
- Context passing through execution tree

---

## Technical Details

### Cache Key Formats

```
local:  {keychain_name}:{catalog_id}:{execution_id}
        Example: "user_session:518486534513754563:518508477736551392"

global: {keychain_name}:{catalog_id}:global
        Example: "api_token:518486534513754563:global"

shared: {keychain_name}:{catalog_id}:shared:{execution_id}
        Example: "context:518486534513754563:shared:518508477736551392"
```

### Database Schema

```sql
CREATE TABLE noetl.keychain (
    cache_key TEXT PRIMARY KEY,
    keychain_name TEXT NOT NULL,
    catalog_id BIGINT NOT NULL,
    scope_type TEXT NOT NULL CHECK (scope_type IN ('local', 'global', 'shared')),
    execution_id BIGINT,
    parent_execution_id BIGINT,
    -- ... other fields
);
```

**Valid scope_type values:** `local`, `global`, `shared`

---

## Common Patterns

### Pattern 1: Global Service Token
```yaml
keychain:
  - name: api_token
    kind: oauth2
    scope: global
    auto_renew: true
    endpoint: https://api.example.com/oauth/token
    
workflow:
  - step: fetch_data
    tool:
      kind: http
      url: https://api.example.com/data
      headers:
        Authorization: "Bearer {{ keychain.api_token.access_token }}"
```

### Pattern 2: Local User Session
```yaml
workload:
  username: "{{ env.USER }}"
  password: "{{ env.PASSWORD }}"
  
keychain:
  - name: user_session
    kind: http
    scope: local
    endpoint: https://app.example.com/login
    method: POST
    data:
      username: "{{ workload.username }}"
      password: "{{ workload.password }}"
    
workflow:
  - step: get_profile
    tool:
      kind: http
      url: https://app.example.com/profile
      headers:
        Cookie: "session={{ keychain.user_session.session_id }}"
```

### Pattern 3: Shared Orchestration Context
```yaml
# Main orchestrator playbook
keychain:
  - name: project_context
    kind: http
    scope: shared  # Available to all sub-playbooks
    endpoint: https://api.example.com/projects/initialize
    method: POST
    data:
      project_id: "{{ workload.project_id }}"
      
workflow:
  - step: run_ingestion
    tool:
      kind: playbook
      path: data/ingestion
      # Child can access {{ keychain.project_context }}
      
  - step: run_validation
    tool:
      kind: playbook
      path: data/validation
      # Child can access {{ keychain.project_context }}
```

---

## Migration Guide

If you have playbooks using invalid scope values:

### Replace `scope: execution` with `scope: local`
```yaml
# ❌ Before (invalid)
keychain:
  - name: my_token
    scope: execution

# ✅ After (correct)
keychain:
  - name: my_token
    scope: local  # Execution-scoped
```

### Replace `scope: catalog` with `scope: global`
```yaml
# ❌ Before (invalid)
keychain:
  - name: my_token
    scope: catalog

# ✅ After (correct)
keychain:
  - name: my_token
    scope: global  # Playbook-wide shared
```
