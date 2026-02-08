---
sidebar_position: 15
title: Token Refresh and Keychain Resolution (Canonical v10)
description: How workers refresh expiring tokens during tool auth resolution (credential caching + optional keychain registry) — aligned with Canonical v10
---

# Token Refresh and Keychain Resolution (Canonical v10)

This document updates **Keychain Token Refresh** to match the **Canonical v10** runtime model.

Canonical intent:
- Playbooks do **not** embed tokens; they reference **auth/credentials by name** (often via `workload`).
- Workers resolve auth **per tool task execution** (inside the tool runner).
- Token refresh is part of the **credential materialization + caching** subsystem (see `credential_caching_v2.md`).
- The event log stores **metadata only** (never decrypted token bytes).

> “Keychain” may exist as an **implementation registry** (catalog of credential definitions), but the canonical behavior is: **tool auth resolution** → **refresh if needed** → **cache encrypted** → **execute tool**.

---

## 1) Overview

Many credentials produce **short-lived tokens** (OAuth access tokens, ID tokens, STS tokens). NoETL prevents token-expiration failures by refreshing tokens **before** a tool task uses them.

At tool execution time, the worker:
1. Resolves the requested credential reference (`auth:` / `credential:`)
2. Checks if the resolved token is expired or expiring soon (TTL threshold)
3. Refreshes (or re-mints) the token if needed
4. Updates secure caches (execution-scoped and/or global derived-token cache)
5. Uses the fresh token to execute the tool task

This is executed **automatically** before each tool task that requires auth.

---

## 2) What playbooks reference

Canonical playbooks reference credentials by **name**, typically:

- `auth: pg_k8s`
- `auth: "{{ workload.openai_auth }}"`
- tool-specific fields such as `credential: ...` are allowed but should normalize to a credential reference

Playbooks should **not** reference `{{ keychain.*.token }}` as the primary mechanism.
If legacy playbooks do so, the runtime may support it for compatibility by treating it as a credential reference resolution step, but it is not the preferred canonical style.

---

## 3) Refresh threshold policy

Workers refresh tokens when remaining TTL is below a configurable threshold.

Recommended environment variable (unchanged concept):
- `NOETL_AUTH_REFRESH_THRESHOLD_SECONDS` (default: 300 seconds)

The threshold should be chosen based on:
- expected tool/task duration
- token mint/refresh latency
- network conditions and retry budget

---

## 4) Where refresh happens (worker tool runner)

Refresh occurs during **auth resolution**, not as a separate step/DSL feature.

Conceptual flow:

```
Worker begins task execution
  ↓
Resolve auth reference (credential name + usage policy)
  ↓
Fetch cached token material (hot cache → Postgres cache → provider)
  ↓
Check TTL vs threshold
  - TTL > threshold  → use token
  - TTL ≤ threshold  → refresh/re-mint token
  ↓
Update caches (encrypted) + return token in-memory
  ↓
Execute tool
```

---

## 5) Caching model (canonical)

Token refresh integrates with the canonical caching scopes:

### 5.1 Execution-scoped cache
- caches credential material for the current execution
- key includes `(execution_id, credential_name, credential_fingerprint)`

### 5.2 Global derived-token cache
- caches derived tokens across executions when safe
- key MUST include token derivation inputs (audience, scopes, client_id, tenant, etc.)

> See `credential_caching_v2.md` for full keying and security rules.

---

## 6) Error handling and retry

Token refresh failures are represented as structured tool outcomes, allowing task policy rules to decide:

- retry for transient failures (timeouts, 429, 5xx from token provider)
- fail fast for permanent auth failures (invalid_grant, invalid_client, 401)

Important:
- retries for refresh happen via task policy (`then.do: retry`) and/or tool-internal retry knobs (implementation-defined)
- the runtime should avoid repeated refresh storms (use jitter/backoff and global cache keys)

---

## 7) Security constraints (MUST)

- Decrypted tokens MUST exist only in worker memory for the duration of tool execution.
- Decrypted tokens MUST NOT be:
  - written to the event log
  - returned in `outcome.result`
  - written to `ctx` or `iter`
  - included in projections
- Logs MUST redact token values.
- Cache entries MUST be encrypted at rest and include metadata (fingerprint, expiry, key id).

---

## 8) Optional: “Keychain” registry compatibility

If your implementation uses a `keychain` section or a keychain service:
- treat it as a **registry/catalog** that maps `credential_name` → provider configuration
- the worker still resolves auth via the same materialization pipeline
- token refresh still occurs during tool execution

This preserves the conceptual “keychain” while keeping canonical semantics consistent.

---

## 9) Monitoring signals (recommended)

Emit non-sensitive operational metrics/logs:
- token cache hit/miss (by credential name)
- refresh count and refresh latency
- refresh failure rate (by provider)
- token age/TTL distribution at time of use (bucketed)

Example safe messages:
- `AUTH: refresh performed for credential X (ttl=120s < threshold=300s)`
- `AUTH: refresh failed for credential X (provider timeout); retrying…`

---

## 10) Best practices

1. Prefer `auth:` references over templated token injection.
2. Include all derivation inputs in global token cache keys (audience, scopes, tenant, client).
3. Refresh “ahead of expiry” with a threshold; do not wait for hard expiry.
4. Use idempotent tool calls or safe retries where possible.
5. Do not leak tokens into logs, events, or outputs—ever.

---

## See also
- `credential_caching_v2.md`
- `retry_mechanism_v2.md`
- `result_storage_v2.md`
