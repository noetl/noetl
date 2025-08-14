# NoETL Credentials and Secrets Guide

This guide explains how to register, encrypt, store, and use credentials and secrets in NoETL. It covers API, CLI, manifest-based registration, and how to use credentials inside playbooks, including bearer tokens and Google service account tokens.


## Overview

- Secrets are stored in Postgres in the `credential` table.
- Data is encrypted at-rest using AES-256-GCM with a key derived via SHA-256 from `NOETL_ENCRYPTION_KEY`.
- The server exposes endpoints to create, list, and fetch credentials.
- HTTP tasks can inject Authorization headers using stored credentials.
- GCP access tokens can be obtained via local endpoint or by a `secrets` task provider.


## Prerequisites

- Ensure the NoETL server has `NOETL_ENCRYPTION_KEY` set (required to encrypt/decrypt secrets). For Kubernetes, it’s already set in `k8s/noetl/noetl-configmap.yaml`. For local dev, set it in the environment before starting the server:

  ```bash
  export NOETL_ENCRYPTION_KEY=dfgdfgsdgsd
  noetl server start --port 8082
  ```

- Verify the database is reachable and initialized; NoETL automatically creates the `credential` table.


## Ways to Register Credentials

You can register secrets/credentials in several ways:

### 1) Via CLI

```bash
# JSON inline
noetl secret register \
  --name my-bearer-token \
  --type httpBearerAuth \
  --data '{"token":"XYZ"}' \
  --description "Example token" \
  --tags env=dev,team=integration

# From file
noetl secret register \
  -n my-bearer-token \
  -t httpBearerAuth \
  --data-file token.json
```

Options:
- `--name, -n`: Unique credential name
- `--type, -t`: Credential type (e.g., `httpBearerAuth`, `googleServiceAccount`)
- `--data`: JSON string payload
- `--data-file`: Path to JSON file payload
- `--meta/--meta-file`: Optional metadata
- `--tags`: Comma-separated tags
- `--description`: Optional description
- `--host/--port`: NoETL server host/port (defaults to env).


### 2) Via Manifest (similar to playbook catalog registration)

Create a manifest like `examples/credentials/secret_bearer.yaml`:

```yaml
apiVersion: noetl.io/v1
kind: Secret
name: my-bearer-token
path: examples/credentials/secret_bearer
version: 0.1.0
description: Example bearer token

tags:
  - example
  - http
  - bearer

type: httpBearerAuth

data:
  token: "REPLACE_ME_WITH_REAL_TOKEN"
```

Register it:

```bash
noetl catalog register secret examples/credentials/secret_bearer.yaml --host localhost --port 8084
```

You can also use the helper script:

```bash
./bin/register-secret.sh --file examples/credentials/secret_bearer.yaml
```


### 3) Via REST API (automation)

```bash
curl -sS -H 'Content-Type: application/json' -X POST \
  -d '{
    "name": "my-bearer-token",
    "type": "httpBearerAuth",
    "data": {"token": "XYZ"},
    "description": "Example token",
    "tags": ["example","http"]
  }' \
  http://localhost:8084/api/credentials | jq .
```

Helper script variant (supports cli and manifest modes):

```bash
./bin/register-secret.sh --name my-bearer --type httpBearerAuth --data '{"token":"XYZ"}'
```


## Managing Credentials

- List:
  ```bash
  curl -sS http://localhost:8084/api/credentials | jq .
  ```

- Filter by type:
  ```bash
  curl -sS 'http://localhost:8084/api/credentials?ctype=httpBearerAuth' | jq .
  ```

- Get by name or ID:
  ```bash
  # Without data
  curl -sS http://localhost:8084/api/credentials/my-bearer-token | jq .

  # Include decrypted data (server must have NOETL_ENCRYPTION_KEY set)
  curl -sS 'http://localhost:8084/api/credentials/my-bearer-token?include_data=true' | jq .
  ```

Note: `include_data=true` returns decrypted JSON; handle carefully.


## Using Credentials in Playbooks (HTTP Bearer example)

NoETL HTTP tasks can inject a stored bearer token similar to n8n’s HTTP Request node.

Example playbook (already in repo at `examples/credentials/http_bearer_example.yaml`):

```yaml
apiVersion: noetl.io/v1
kind: Playbook
name: http_bearer_example
path: examples/credentials/http_bearer_example
version: 0.1.0

authentication: genericCredentialType
workbook:
  - name: call_api_task
    type: http
    method: GET
    endpoint: "https://httpbin.org/bearer"
    headers:
      Content-Type: application/json
    payload:
      message: "hello"
    authentication: genericCredentialType
    genericAuthType: httpBearerAuth
    credentials:
      httpBearerAuth:
        name: "my-bearer-token"
    timeout: 10
```

Run it:

```bash
# Ensure credential exists (see registration steps above)
noetl execute examples/credentials/http_bearer_example --host localhost --port 8084
```

The engine will look up `my-bearer-token` in the `credential` table, decrypt it, and set:

```
Authorization: Bearer <token>
```


## Google Service Account (GCP) Tokens

You can obtain GCP access tokens via:

1) Local NoETL endpoint `/api/gcp/token` (HTTP task or curl)
2) `secrets` task with provider `gcp_token` (no external HTTP call)

Supported inputs:
- `scopes`: string or list (default: https://www.googleapis.com/auth/cloud-platform)
- `use_metadata`: true/false (try ADC/metadata)
- `credentials_path`: path to a service account JSON file
- `service_account_secret`: Google Secret Manager resource path `projects/.../secrets/.../versions/...`
- `credentials_info`: full service account JSON object (or JSON string)

### Quick tests with helper script

```bash
# From file
./bin/test-gcp-token.sh --port 8084 \
  --scopes https://www.googleapis.com/auth/cloud-platform \
  --credentials-path .secrets/noetl-service-account.json

# Using GSM
./bin/test-gcp-token.sh --port 8084 \
  --service-account-secret projects/123456/secrets/noetl-service-account/versions/1

# Embedding credentials info from a file into the request body
./bin/test-gcp-token.sh --port 8084 \
  --credentials-info-file .secrets/noetl-service-account.json

# Try metadata/ADC
./bin/test-gcp-token.sh --port 8084 --use-metadata true
```

### Use in a playbook (HTTP task)

```yaml
workbook:
  - name: get_gcp_token_http_task
    type: http
    endpoint: "{{ workload.noetl_base_url }}/gcp/token"  # or /api/gcp/token depending on routing
    method: POST
    headers:
      Content-Type: application/json
    payload:
      scopes:
        - "https://www.googleapis.com/auth/cloud-platform"
      credentials_path: "/opt/noetl/.secrets/noetl-service-account.json"
      use_metadata: false
    timeout: 10
```

Note: The engine may short-circuit the internal call to avoid loopback overhead when targeting localhost/127.0.0.1.

### Use in a playbook (secrets task)

```yaml
workbook:
  - name: get_gcp_token_adc_task
    type: python
    with:
      credentials_path: "{{ credentials_path }}"
      scopes: "{{ scopes }}"
    code: |
      def main(credentials_path=None, scopes=None):
          from google.oauth2 import service_account
          from google.auth.transport.requests import Request
          import google.auth
          import os, os.path
          scope_list = [scopes] if isinstance(scopes, str) and scopes else ["https://www.googleapis.com/auth/cloud-platform"]
          sa_path = credentials_path or os.getenv('GOOGLE_APPLICATION_CREDENTIALS')
          creds = None
          if sa_path and os.path.exists(sa_path):
              creds = service_account.Credentials.from_service_account_file(sa_path, scopes=scope_list)
              creds.refresh(Request())
          else:
              creds, _ = google.auth.default(scopes=scope_list)
              creds.refresh(Request())
          return {
              "access_token": creds.token,
              "token_expiry": getattr(creds, 'expiry', None).isoformat() if getattr(creds, 'expiry', None) else None,
              "used_sa_file": bool(sa_path and os.path.exists(sa_path))
          }
```

Or directly via the dedicated `secrets` task provider `gcp_token` (no HTTP):

```yaml
workbook:
  - name: gcp_token_via_provider
    type: secrets
    task: get_gcp
    with:
      provider: gcp_token
      scopes:
        - "https://www.googleapis.com/auth/cloud-platform"
      credentials_path: "/opt/noetl/.secrets/noetl-service-account.json"
      use_metadata: false
```


## How to register Google service account credentials from files

Given file like:
- `.secrets/noetl-service-account.json`

there are two practical paths:

1) Use the file directly in playbooks (`credentials_path`) or export `GOOGLE_APPLICATION_CREDENTIALS` and rely on ADC.

2) Optionally store the same JSON encrypted in NoETL for central management:

```bash
noetl secret register \
  --name gcp-sa-noetl \
  --type googleServiceAccount \
  --data-file .secrets/noetl-service-account.json
```

Current playbooks expect the SA JSON via `credentials_path`, `service_account_secret` (GSM), or `credentials_info`. If you store SA JSON in NoETL, you can retrieve it on-demand from an external script or service via:

```bash
curl -sS 'http://localhost:8084/api/credentials/gcp-sa-noetl?include_data=true' | jq .
```

Then pass the `credentials_info` into a playbook invocation payload or an HTTP task to `/api/gcp/token`.


## End-to-End Bearer Token Example

1) Register a bearer token (choose one):
   - CLI: `noetl secret register -n my-bearer-token -t httpBearerAuth --data '{"token":"XYZ"}'`
   - Manifest: `noetl catalog register secret examples/credentials/secret_bearer.yaml`
   - API: `POST /api/credentials` with `{name, type, data}`

2) Execute the example playbook:

```bash
noetl execute examples/credentials/http_bearer_example.yaml --host localhost --port 8084
```

3) Verify the request reached https://httpbin.org/bearer with Authorization header applied.


## Security Notes

- Never commit real secrets to version control. Use env vars, K8s Secrets, or out-of-repo files.
- Rotate `NOETL_ENCRYPTION_KEY` carefully; old secrets encrypted with a previous key will not decrypt with a new key.
- Limit access to `GET /api/credentials/{name}?include_data=true`. Consider network/policy-level protections.


## Troubleshooting

- "NOETL_ENCRYPTION_KEY is not set": The server must have this env var at startup.
- "Credential not found": Confirm registration succeeded and the name matches.
- HTTP task fails with timeout to localhost in K8s: Ensure `NOETL_BASE_URL`/`NOETL_INTERNAL_URL` are correctly set or rely on the internal short-circuit for the GCP token endpoint. K8s manifests in `k8s/noetl` include examples.
- GCP token failures: Validate SA JSON path, GSM resource path, scopes, and that the container can reach Google APIs.


## Related Files

- Examples
  - `examples/credentials/secret_bearer.yaml`
  - `examples/credentials/http_bearer_example.yaml`
- Helper scripts
  - `bin/register-secret.sh`
  - `bin/test-gcp-token.sh`
- Server endpoints
  - `POST /api/credentials`
  - `GET /api/credentials`
  - `GET /api/credentials/{name|id}`
  - `POST /api/gcp/token`

This document reflects features available as of 2025-08-13.



## Using OIDC (GCP Service Account) in HTTP tasks

You can have an HTTP task automatically obtain a Google access token using a stored Service Account credential and inject it as a Bearer token via a simple auth block.

Example:

```yaml
# In the workload you can keep a secret name to reference
workload:
  gcp_credentials_secret: "gcp-sa-noetl"
  gcp_scopes: "https://www.googleapis.com/auth/cloud-platform"

workbook:
  - name: list_zones_http_task
    type: http
    method: GET
    endpoint: "https://compute.googleapis.com/compute/v1/projects/{{ workload.project }}/zones"
    auth:
      type: OIDC          # or oauth2/gcp/google (case-insensitive)
      provider: gcp
      credential:
        name: "{{ workload.gcp_credentials_secret }}"  # stored via: noetl secret register -n gcp-sa-noetl -t googleServiceAccount --data-file .secrets/noetl-service-account.json
      scopes:
        - "{{ workload.gcp_scopes }}"
    timeout: 10
```

Engine behavior:
- Loads Service Account JSON from the credential table (by name or id), decrypts it, calls the internal token helper, and sets `Authorization: Bearer <access_token>`.
- Supports `scopes` as a string or a list; defaults to `cloud-platform` if omitted.
- If `credential` is omitted, the engine tries `workload.gcp_credentials_secret`.

This enables calling Google REST APIs directly from HTTP tasks.
