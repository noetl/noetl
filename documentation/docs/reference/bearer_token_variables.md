# Bearer Tokens and Execution Context (Canonical v10)

Canonical v10 separates **secrets/tokens** from general execution state:

- **Secrets/tokens:** resolved via root `keychain` and referenced via `auth:` (preferred) or `keychain.*` (read-only templating).
- **Execution state:** stored in `ctx` (execution scope) and `iter` (iteration scope) via task policy patches (`set_ctx`, `set_iter`).

## Hard rule (security)

Decrypted bearer tokens MUST NOT be written to:
- the event log
- `outcome.result`
- `ctx` or `iter`

Prefer `auth:` references so the runtime can inject credentials into tools without exposing token bytes.

---

## Canonical variable scopes (reminder)

- `workload.*` — immutable merged input
- `ctx.*` — mutable execution-scoped state (non-secret)
- `iter.*` — mutable iteration-scoped state (non-secret)
- `args.*` — token payload from `next.arcs[].args`

See `documentation/docs/reference/variables_v2.md` and `documentation/docs/reference/dsl/step_spec.md`.

---

## Recommended pattern: OAuth/keychain + HTTP auth reference

Declare credentials in root `keychain`, then reference them from HTTP tasks:

- prefer `auth: <credential_name>` (runtime injects token)
- or template read-only `keychain.*` into headers when necessary (ensure redaction)

See:
- `documentation/docs/reference/auth_and_keychain_reference.md`
- `documentation/docs/reference/tools/http.md`

---

## Legacy note: “execution variables” / `/api/vars/*`

Older runtimes supported execution-scoped variables and patterns like:
- `auth.bearer: true`
- `variable: my_token`

Canonical v10 deprecates this as a user-facing feature:
- for **non-secret** values, treat it as a compatibility layer for `ctx` patches
- for **secrets/tokens**, do not persist them in variables at all (use keychain/auth)
