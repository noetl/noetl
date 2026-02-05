---
sidebar_position: 32
title: Credential Caching (Canonical v2)
description: Secure, reference-first credential materialization and caching for NoETL runtime (execution + global token caches)
---

# Credential Caching (Canonical v2)

This document updates `credential_caching.md` to align with the **canonical NoETL v2** execution model:

- Root playbook sections: `metadata`, `executor`, `workload`, `workflow`, `workbook`
- Step executes `tool` pipelines; control flow uses tool-level `eval`
- Results are reference-first; “sink” is a pattern, not a tool kind
- NATS KV is an **optional coordination/hot-cache layer**, not an authoritative store for bulk values

Credential caching is a **runtime concern**. Credentials are referenced by name in the playbook (typically from `workload`), **materialized at execution time**, and cached securely to reduce load on external secret providers and reduce tail latency.

---

## 1) Goals and Non-Goals

### Goals
- Reduce secret-manager / IdP calls during high-volume runs
- Support **fast per-task auth resolution** on workers
- Keep secrets out of event logs, step outputs, and projections
- Provide both:
  - **execution-scoped cache** (per execution instance)
  - **global derived-token cache** (shared, policy-keyed)

### Non-Goals
- Storing plaintext secrets anywhere
- Using `ctx` as a general secret store
- Making NATS KV the authoritative secret database

---

## 2) Terminology

- **Credential**: a named auth source (e.g., OAuth client, API key, service account)
- **Materialization**: resolving credential name → concrete secret/token material for a tool call
- **Derived token**: short-lived token minted from a base credential (OAuth access token, ID token, signed JWT)
- **Fingerprint**: stable hash identifying the effective credential version + inputs

---

## 3) High-level model

### 3.1 Playbook usage (reference only)
Playbooks reference credentials by name (example patterns):
- `auth: pg_k8s`
- `auth: "{{ workload.openai_auth }}"`

Credential names and provider configuration live in your runtime’s keychain/registry (implementation-defined). **The playbook does not embed credential material.**

### 3.2 Runtime materialization path
1. Tool task requests auth material: `(credential_ref, usage_policy)`
2. Worker checks hot cache(s) for a matching entry
3. If missing/expired → resolve from provider (secret manager / OAuth / STS / etc.)
4. Cache encrypted material (bounded TTL)
5. Provide decrypted material to tool **in-memory only**
6. Emit events with metadata only (no secret bytes)

---

## 4) Canonical scopes for credential caching

Credential caching is not general runtime state (`ctx/vars/iter`). It is a **specialized secure cache** used during tool execution.

Two caching scopes are supported:

### 4.1 Execution-scoped cache
Purpose: reuse material within the same playbook execution.
Examples:
- resolved API key value
- decoded service account JSON
- session token used across multiple tasks within one execution

**Keying (recommended):**
- `exec_cache_key = (execution_id, credential_name, credential_fingerprint)`

Where `credential_fingerprint` includes:
- credential version (e.g., secret version, rotation id)
- provider identity (project/tenant)
- any inputs that affect resulting materialization

### 4.2 Global derived-token cache
Purpose: reuse derived tokens **across executions** when safe.
Examples:
- OAuth access tokens for identical `(client_id, audience, scopes)`
- STS tokens for identical `audience` and policy

**Keying (MUST include token derivation inputs):**
- `global_key = (credential_name, token_type, client_id, audience, scope_hash, tenant, additional_claims_hash)`

> Global caching is safe only if the cache key fully captures all inputs that affect token output.

---

## 5) Storage layers

### 5.1 Authoritative cache store (recommended): Postgres
Postgres (or equivalent durable store) is recommended as the authoritative cache store for encrypted blobs, with TTL and indexing.

### 5.2 Optional hot cache: NATS KV or ValKey/Redis
NATS KV / ValKey can be used as a **hot cache** layer in front of Postgres if:
- values remain small and encrypted
- TTL is enforced
- cache misses fall back to Postgres
- the system remains correct if hot cache is empty

> KV/Redis are optional performance layers. Postgres remains authoritative for cache durability (in this model).

---

## 6) Cache records (conceptual)

Each cached entry should capture:

- `cache_scope`: `execution | global`
- `cache_key`: serialized composite key
- `credential_name`
- `fingerprint`
- `data_encrypted`: encrypted blob
- `expires_at`
- `created_at`, `updated_at`
- `metadata`: small info (token_type, provider, subject, aud, scopes hash)

### 6.1 Encryption requirements
- Encryption MUST be at rest for `data_encrypted`
- Keys MUST be managed outside the database (KMS/secret manager)
- Decryption MUST occur only in worker memory during tool execution
- Rotating encryption keys should be supported via key id/version in metadata

---

## 7) Resolution policies

### 7.1 Execution cache policy
- Prefer execution cache if fingerprint matches and entry not expired
- If credential rotates mid-execution, fingerprint mismatch forces refresh
- Execution cache entries can be short-lived (e.g., 15m–2h) depending on credential type

### 7.2 Global token cache policy
- Use only for derived tokens
- Include refresh-ahead window (e.g., refresh when `< 10% TTL` left)
- Never share tokens across incompatible audiences/scopes/tenants

---

## 8) Integration with tool execution

### 8.1 Where auth is resolved
Auth resolution happens inside the worker tool runner, per task:

- tool receives decrypted auth material in-memory
- tool output (`outcome.result`) MUST NOT include secret bytes
- events MUST NOT include decrypted auth material

### 8.2 Event log safety
Events may include only:
- credential name (not value)
- fingerprint (hash)
- token type (metadata)
- cache hit/miss indicator (optional)

Example safe metadata:
- `auth.cache: hit|miss`
- `auth.credential: openai_token`
- `auth.fingerprint: sha256:...`
- `auth.token_type: bearer`

---

## 9) Failure and retry interaction

Credential resolution failures should be represented as structured errors in `outcome.error` so tool-level `eval` can decide policy:

- retry on transient provider failures (timeouts, 429, 5xx)
- fail fast on auth invalid/denied (401, invalid_grant, etc.)

> Retry is still expressed via tool-level `eval`. Credential resolution is part of the tool execution outcome.

---

## 10) Recommended API shapes (runtime/internal)

These are runtime internal interfaces (not DSL):

- `resolve_credential(credential_name, usage_policy, execution_id) -> material`
- `derive_token(material, token_policy) -> token`
- `cache_get(scope, key) -> encrypted_entry|None`
- `cache_put(scope, key, encrypted_entry)`

Where `usage_policy` / `token_policy` include:
- token type
- audience
- scopes
- tenant/realm
- custom claims
- max TTL

---

## 11) Operational guidance

- Keep cache entries small; store only what tools need
- Use stable fingerprints to avoid stale credential reuse
- Make all caches rebuildable (Postgres is durable; hot caches can be wiped)
- Audit and redact logs:
  - never log decrypted blobs
  - never include decrypted creds in projections
- Periodic TTL cleanup jobs for Postgres
- Optional metrics:
  - cache hit rate by credential name
  - provider call latency
  - token refresh rates

---

## 12) Summary

Canonical v2 credential caching is a secure runtime system:
- Playbooks reference credential names only
- Workers materialize creds and cache encrypted artifacts
- Postgres is the recommended durable cache store
- NATS KV / ValKey are optional hot-cache layers
- Cache keys must include credential fingerprints and token derivation inputs
- Secrets never appear in event logs or tool outputs
