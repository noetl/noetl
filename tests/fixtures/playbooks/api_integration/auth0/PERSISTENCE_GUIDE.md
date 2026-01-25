# Auth0 Integration Persistence Guide

This guide explains how the Auth0 OAuth integration persists across kind cluster rebuilds.

## What Was Fixed

### Issue Summary
After implementing Auth0 OAuth implicit flow, discovered multiple issues:
1. Postgres tool case conditions checking `response is defined` (always false)
2. Result references using `stepname[0].field` instead of `stepname.command_0.rows[0].field`
3. UI treating postgres execute API result as array of objects instead of array of arrays
4. Session token appearing as `undefined` despite session existing in database

### Solution Implemented
1. Updated all case conditions in auth0_login.yaml to check `result.command_0 is defined` (v15)
2. Fixed all result references to use proper postgres tool format: `.command_0.rows[0].field`
3. Changed UI from `result[0].session_token` to `result[0][0]` for array-of-arrays access
4. Regenerated ConfigMap and restarted gateway-ui deployment
5. Added comprehensive Quick Start documentation to README.md

### Verified Working
- Execution 535423222926278790 completed successfully (2026-01-08 17:50:22)
- All steps completed: start -> validate_token -> upsert_user -> create_session -> success -> end
- Session created in database: token=8d472a783af421d2e40d34f4b909d43b, user_id=2
- UI successfully retrieved session token and completed login flow

## Files Committed

### Core Playbook (Final Working Version)
- `tests/fixtures/playbooks/api_integration/auth0/auth0_login.yaml` (v15)
  - Line 105: Case condition `result.command_0 is defined`
  - Line 132: Case condition `result.command_0 is defined`
  - Line 124: User ID reference `upsert_user.command_0.rows[0].user_id`
  - Lines 141-143: Success step args using `create_session.command_0.rows[0].field`

### UI Files (Fixed Array Parsing)
- `tests/fixtures/gateway_ui/login.html`
  - Line 399: Changed to `sessionData.result[0][0]` for array-of-arrays access
  - Session polling with connection_string for cluster-internal access
  - Uses `payload` field in API call with auth0_token and client_ip
- `tests/fixtures/gateway_ui/config.js` - Auth0 configuration
- `tests/fixtures/gateway_ui/dashboard.html` - Dashboard page
- `tests/fixtures/gateway_ui/auth.js` - Authentication utilities
- `tests/fixtures/gateway_ui/app.js` - Main application logic
- `tests/fixtures/gateway_ui/index.html` - Main page
- `tests/fixtures/gateway_ui/styles.css` - Shared styles

### Kubernetes Manifests
- `ci/manifests/gateway/configmap-ui-files.yaml` - Generated ConfigMap with UI files
  - Generated with: `kubectl create configmap gateway-ui-files --from-file=tests/fixtures/gateway_ui/ --namespace=gateway --dry-run=client -o yaml`
  - Applied with: `kubectl apply -f ci/manifests/gateway/configmap-ui-files.yaml`

### Scripts (Executable)
- `tests/scripts/test_auth0_integration.sh` (chmod +x) - Test setup script
- `ci/manifests/gateway/regenerate-ui-configmap.sh` (chmod +x) - ConfigMap regeneration

### Documentation
- `tests/fixtures/playbooks/api_integration/auth0/README.md`
  - Lines 1-170: New Quick Start section with:
    * OAuth Implicit Flow implementation details
    * JWT decoding without external libraries
    * Session token generation using md5()
    * Postgres tool result format explanation
    * Case condition patterns
    * NoETL V2 API payload vs workload distinction
    * Troubleshooting common errors

## Persistence After Cluster Rebuild

### What Persists Automatically
All files are now in git and will be restored after cluster rebuild:
- Playbook YAML files (auth0_login.yaml v15)
- UI source files (tests/fixtures/gateway_ui/*)
- ConfigMap manifest (ci/manifests/gateway/configmap-ui-files.yaml)
- Setup scripts (tests/scripts/test_auth0_integration.sh)
- Documentation (README.md with Quick Start)

### What Needs to Be Redeployed

After rebuilding kind cluster, run these commands:

```bash
# 1. Rebuild and deploy NoETL
noetl run automation/setup/bootstrap.yaml

# 2. Register playbooks
curl -X POST http://localhost:8082/api/catalog/register \
  -H 'Content-Type: application/json' \
  -d "{\"content\": \"$(cat tests/fixtures/playbooks/api_integration/auth0/auth0_login.yaml)\"}"

# 3. Verify UI is accessible
curl http://localhost:8080/login.html

# 4. Test login flow (if needed)
bash tests/scripts/test_auth0_integration.sh
```

### Testing Persistence

To verify everything works after cluster rebuild:

```bash
# 1. Delete cluster
kind delete cluster

# 2. Recreate cluster
kind create cluster

# 3. Deploy all components
noetl run automation/setup/bootstrap.yaml

# 4. Test Auth0 login
# Open browser: http://localhost:8080/login.html
# Click "Sign In with Auth0"
# Login as kadyapam@gmail.com
# Verify redirect to dashboard with session token
```

## Updating UI Files

If you modify UI files in `tests/fixtures/gateway_ui/`, regenerate the ConfigMap:

```bash
# Method 1: Using the script
bash ci/manifests/gateway/regenerate-ui-configmap.sh

# Method 2: Manual
kubectl create configmap gateway-ui-files \
  --from-file=tests/fixtures/gateway_ui/ \
  --namespace=gateway \
  --dry-run=client \
  -o yaml > ci/manifests/gateway/configmap-ui-files.yaml

# Apply changes
kubectl apply -f ci/manifests/gateway/configmap-ui-files.yaml

# Restart gateway-ui
kubectl rollout restart deployment/gateway-ui -n gateway
```

## Database Schema

The auth schema must be provisioned after cluster rebuild:

```bash
# Register and execute schema provisioning
curl -X POST http://localhost:8082/api/catalog/register \
  -H 'Content-Type: application/json' \
  -d "{\"content\": \"$(cat tests/fixtures/playbooks/api_integration/auth0/provision_auth_schema.yaml)\"}"

curl -X POST http://localhost:8082/api/execute \
  -H 'Content-Type: application/json' \
  -d '{"path": "api_integration/auth0/provision_auth_schema", "payload": {}}'
```

## Credentials

After cluster rebuild, you must re-register credentials:

```bash
# Method 1: Register all test credentials
noetl run automation/test/register-test-credentials.yaml

# Method 2: Register Auth0 credential specifically
curl -X POST http://localhost:8082/api/credentials \
  -H 'Content-Type: application/json' \
  -d @tests/fixtures/credentials/auth0_client.json

# Method 3: Use test script
export AUTH0_USER_PASSWORD='your_password'
bash tests/scripts/test_auth0_integration.sh --use-file
```

## Architecture Notes

### NoETL V2 DSL Patterns Used
- **Keychain**: `keychain: [{name: auth0_credentials, kind: credential, credential: "{{ workload.auth0_credential }}"}]`
- **HTTP Tool V2**: `tool: {kind: http, endpoint: "{{ url }}", payload: {...}, params: {...}}`
- **Postgres Tool Result Format**: `{command_0: {rows: [...], status: "success", columns: [...]}}`
- **Case Conditions**: `when: "{{ result.command_0 is defined }}"` (NOT `response is defined`)
- **Result References**: `stepname.command_0.rows[0].fieldname` (NOT `stepname[0].field`)

### Postgres Execute API Format
- Returns: `{status: "ok", result: [["value1"], ["value2"]], error: null}`
- Access: `result[0][0]` for first row first column (array indexing)
- NOT: `result[0].field` (object property access)

### Session Token Generation
- Uses: `md5(random()::text || clock_timestamp()::text)`
- No pgcrypto extension required
- Random but predictable for debugging

### JWT Decoding
- Python base64: `base64.urlsafe_b64decode(token.split('.')[1] + '==')`
- No external libraries (jwt, pyjwt, etc.)
- Extracts sub, email, name, email_verified

## Troubleshooting

### Issue: "Session token not found after login"
**Cause**: UI accessing result as object instead of array of arrays
**Solution**: Already fixed in login.html line 399 (`result[0][0]`)

### Issue: "Execution stuck at upsert_user step"
**Cause**: Case condition checking `response is defined` instead of `result.command_0 is defined`
**Solution**: Already fixed in auth0_login.yaml v15 lines 105, 132

### Issue: "undefined user_id"
**Cause**: Result reference using `stepname[0].field` instead of `stepname.command_0.rows[0].field`
**Solution**: Already fixed in auth0_login.yaml v15 line 124

### Issue: "ConfigMap changes lost after cluster rebuild"
**Cause**: ConfigMap not in git
**Solution**: ci/manifests/gateway/configmap-ui-files.yaml is now committed

## Version History

- **v15** (2026-01-08): Fixed all postgres tool case conditions and result references, UI array parsing
- **v14**: Fixed session token generation with md5()
- **v13**: Fixed JWT validation step
- **v12**: Fixed workload vs payload parameter passing
- **v11-v1**: Earlier iterations with various bugs

## Commit Details

```
Commit: 6bc40235
Date: 2026-01-08 18:05:22
Message: chore: fix Auth0 OAuth integration with postgres tool V2 DSL and UI array parsing

Files Changed:
- auth0_login.yaml: Fixed case conditions and result references
- login.html: Fixed UI result parsing (result[0][0])
- README.md: Added Quick Start section with troubleshooting
- configmap-ui-files.yaml: Regenerated with fixed login.html
- Scripts: Made executable

Verified Working:
- Execution 535423222926278790 completed successfully
- Session created: token=8d472a783af421d2e40d34f4b909d43b
- Full end-to-end login flow tested
```

## Contact

For issues or questions:
- Review NoETL logs: `kubectl logs -n noetl deployment/noetl-server`
- Check execution status: `curl http://localhost:8082/api/executions`
- Test postgres API: `curl -X POST http://localhost:8082/api/postgres/execute -H 'Content-Type: application/json' -d '{"query": "SELECT session_token FROM auth.sessions LIMIT 1", "connection_string": "postgresql://demo:demo@localhost:54321/demo_noetl"}'`
