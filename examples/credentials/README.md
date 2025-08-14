# Credentials Examples

This folder contains a minimal, end‑to‑end example of how to register an encrypted credential (secret) and use it in a playbook.

What’s included:
- secret_bearer.yaml — a manifest to register a simple bearer token credential.
- http_bearer_example.yaml — a playbook that calls https://httpbin.org/bearer and injects the stored bearer token automatically.

For a comprehensive guide, see docs/credentials_and_secrets.md.


## Prerequisites
- A running NoETL server with encryption enabled:
  - Set NOETL_ENCRYPTION_KEY before starting the server (required to store/decrypt credentials):
    ```bash
    export NOETL_ENCRYPTION_KEY=change-me
    noetl server start --host 0.0.0.0 --port 8084
    ```
- Postgres available and reachable by the NoETL server (the server initializes tables automatically).
- noetl CLI available in your PATH.

Note on ports:
- The examples below use port 8084 for consistency with the repo docs. If you run the server on a different port, adjust --port accordingly.


## Step 1: Register the bearer credential
There are two easy ways to register the credential.

Option A) Register via manifest
```bash
# Edit the token value if you want to customize it (any non-empty token is fine for httpbin)
# examples/credentials/secret_bearer.yaml

./bin/register-secret.sh --file examples/credentials/secret_bearer.yaml --port 8084
```

Option B) Register via CLI (inline JSON)
```bash
noetl secret register \
  --name my-bearer-token \
  --type httpBearerAuth \
  --data '{"token":"XYZ"}' \
  --host localhost \
  --port 8084
```

Verify it’s stored:
```bash
curl -sS http://localhost:8084/api/credentials | jq .
# or fetch by name
curl -sS http://localhost:8084/api/credentials/my-bearer-token | jq .
```


## Step 2: Run the playbook that uses the credential
Register playbook:
```bash
noetl catalog register examples/credentials/http_bearer_example.yaml --port 8084
```

Execute the example playbook:
```bash
noetl execute examples/credentials/http_bearer_example --host localhost --port 8084
```

What happens:
- The HTTP task targets https://httpbin.org/bearer
- NoETL looks up the stored credential named "my-bearer-token"
- It decrypts the data and sets the header: `Authorization: Bearer <token>`
- httpbin returns a JSON response like:
  ```json
  {
    "authenticated": true,
    "token": "XYZ"    
  }
  ```
Note: httpbin does not validate the token; it just checks for the header.


## Troubleshooting
- Error: NOETL_ENCRYPTION_KEY is not set
  - Ensure you exported NOETL_ENCRYPTION_KEY before starting the server.
- Credential not found
  - Confirm registration succeeded and the credential name in http_bearer_example.yaml matches what you registered (default: my-bearer-token).
- Port/host mismatch
  - If your server runs on a different port/host, include matching --host/--port in the noetl commands.
- Database issues
  - Ensure Postgres is reachable from the server. The server logs will show initialization status.


## Related
- Full guide with advanced options (GCP tokens, OIDC, etc.): docs/credentials_and_secrets.md
- Helper scripts:
  - ./bin/register-secret.sh
  - ./bin/test-gcp-token.sh (GCP token endpoint tester)
