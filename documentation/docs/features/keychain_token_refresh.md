---
sidebar_position: 15
title: Keychain Token Refresh
---

# Keychain Token Refresh

NoETL automatically manages token expiration for credentials used in keychain entries, ensuring tools never fail due to expired tokens.

## Overview

When tools reference keychain entries (e.g., `{{ keychain.gcp_token.token }}`), the worker automatically:

1. **Checks token expiration** - Inspects remaining TTL (time-to-live) before passing to tool
2. **Proactively refreshes** - Renews tokens that are expired or expiring soon
3. **Updates keychain** - Stores refreshed token for future use
4. **Prevents failures** - Eliminates tool execution errors due to expired credentials

This happens **automatically before every tool execution** that uses keychain references.

## Configuration

Configure the refresh threshold via environment variable:

```bash
# Refresh tokens if TTL is below this threshold (in seconds)
# Default: 300 seconds (5 minutes)
export NOETL_KEYCHAIN_REFRESH_THRESHOLD=300
```

### Kubernetes ConfigMap

```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: noetl-config
  namespace: noetl
data:
  NOETL_KEYCHAIN_REFRESH_THRESHOLD: "300"  # 5 minutes
```

## How It Works

### 1. Keychain Definition

Define credentials with auto-renewal configuration:

```yaml
keychain:
  - name: gcp_token
    kind: bearer
    scope: global
    credential: google_oauth
```

### 2. Token Resolution Process

Before tool execution:

```
Worker receives command
  ↓
Scans config for {{ keychain.* }} references
  ↓
Fetches token from keychain API (includes TTL)
  ↓
Checks remaining TTL:
  - TTL > threshold → Use existing token
  - TTL ≤ threshold → Refresh token
  ↓
Passes fresh token to tool
```

### 3. Refresh Logic

```python
# Example: Token with 240s remaining TTL, threshold 300s
if ttl_seconds < refresh_threshold_seconds:
    logger.warning(
        f"Token '{keychain_name}' expiring soon "
        f"(TTL: {ttl_seconds}s < threshold: {refresh_threshold_seconds}s)"
    )
    # Proactively refresh token
    renewed_token = await renew_token()
    # Update keychain with new token
    await update_keychain_entry(renewed_token)
```

## Renewal Configuration

Tokens with `auto_renew: true` and `renew_config` are eligible for automatic refresh:

### OAuth2 Client Credentials

```yaml
POST /api/keychain/{catalog_id}/{keychain_name}
{
  "token_data": {
    "access_token": "...",
    "token_type": "Bearer",
    "expires_in": 3600
  },
  "auto_renew": true,
  "renew_config": {
    "endpoint": "https://oauth2.googleapis.com/token",
    "method": "POST",
    "headers": {
      "Content-Type": "application/x-www-form-urlencoded"
    },
    "data": {
      "grant_type": "client_credentials",
      "client_id": "...",
      "client_secret": "..."
    },
    "token_field": "access_token",
    "ttl_field": "expires_in"
  }
}
```

## Benefits

### Eliminates Tool Failures

**Before (without auto-refresh):**
```
[ERROR] HTTP request failed: 401 Unauthorized
[ERROR] Token expired, tool execution failed
[INFO] Retrying step with exponential backoff...
```

**After (with auto-refresh):**
```
[WARNING] Token 'gcp_token' expiring soon (TTL: 240s < threshold: 300s)
[INFO] Proactively refreshing 'gcp_token' before use
[INFO] Successfully refreshed 'gcp_token' (was expiring soon)
[INFO] Tool execution started with fresh token
```

### Reduces Retry Overhead

- **No failed attempts** - Tools receive fresh tokens from the start
- **No exponential backoff** - Avoids retry delays (seconds to minutes)
- **No wasted resources** - Eliminates unnecessary re-execution of expensive operations

### Improves Reliability

- **Consistent execution** - Playbooks run smoothly without token-related interruptions
- **Long-running workflows** - Multi-step processes continue without credential issues
- **Production stability** - Reduces operational incidents from expired tokens

## Example: Script Tool with GCP

```yaml
keychain:
  - name: gcp_token
    kind: bearer
    scope: global
    credential: google_oauth

workflow:
  - step: run_data_processor
    tool:
      kind: script
      script:
        uri: gs://bucket/scripts/processor.py
        source:
          type: gcs
          auth: google_oauth
      job:
        image: python:3.11-slim
        env:
          # Token is automatically refreshed if expiring
          GCP_TOKEN: "{{ keychain.gcp_token.token }}"
          GCS_BUCKET: "{{ workload.output_bucket }}"
```

**Worker Log Output:**
```
[INFO] KEYCHAIN: Found 1 keychain references: {'gcp_token'}
[INFO] KEYCHAIN: Resolving 'gcp_token' from http://noetl.noetl.svc.cluster.local:8082/api/keychain/123/gcp_token
[WARNING] KEYCHAIN: Token 'gcp_token' expiring soon (TTL: 180s < threshold: 300s)
[INFO] KEYCHAIN: Proactively refreshing 'gcp_token' before use
[INFO] KEYCHAIN: Renewing token via POST https://oauth2.googleapis.com/token
[INFO] KEYCHAIN: Successfully updated 'gcp_token' with renewed token (TTL: 3600s)
[INFO] KEYCHAIN: Successfully refreshed 'gcp_token' (was expiring soon)
[INFO] KEYCHAIN: Populated context with 1 keychain entries
[INFO] WORKER: Executing script tool with fresh credentials
```

## Monitoring

### Successful Refresh
```
[INFO] KEYCHAIN: Successfully refreshed 'token_name' (was expiring soon)
```

### Failed Refresh
```
[ERROR] KEYCHAIN: Failed to refresh 'token_name', using existing token (may be expired)
```

### No Renewal Config
```
[WARNING] KEYCHAIN: Auto-renewal not configured for 'token_name'
```

## Refresh Threshold Tuning

Choose threshold based on:

- **Average tool execution time** - Set threshold higher than typical tool duration
- **Token refresh latency** - Account for time to obtain new token from OAuth provider
- **Network conditions** - Add buffer for potential delays
- **Risk tolerance** - Balance between refresh frequency and token expiration risk

### Recommended Values

| Scenario | Threshold | Rationale |
|----------|-----------|-----------|
| **Default** | 300s (5min) | Safe for most tools, prevents last-minute expiration |
| **Long-running jobs** | 600s (10min) | Ensures token remains valid throughout execution |
| **Fast API calls** | 180s (3min) | Reduces unnecessary refreshes for quick operations |
| **High-latency networks** | 900s (15min) | Adds buffer for slow OAuth provider responses |

## Best Practices

1. **Always enable auto_renew** for OAuth tokens used in production playbooks
2. **Set appropriate TTL** when storing tokens (match OAuth provider's expiry)
3. **Monitor refresh logs** to identify tokens that refresh frequently (may need longer TTL)
4. **Use global scope** for tokens shared across multiple executions
5. **Test token refresh** in development environment before production deployment

## See Also

- [Authentication & Keychain Reference](/docs/reference/auth_and_keychain_reference)
- [Credential Caching](./credential_caching)
- [OAuth Examples](/docs/examples/authentication/)
