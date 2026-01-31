---
sidebar_position: 9
title: NATS Tool
description: Interact with NATS JetStream, K/V Store, and Object Store
---

# NATS Tool

The NATS tool provides access to NATS JetStream, Key/Value Store, and Object Store operations for workflow state management, caching, and messaging.

## Basic Usage

```yaml
- step: store_value
  tool:
    kind: nats
    auth: nats_credential
    operation: kv_put
    bucket: sessions
    key: "{{ session_id }}"
    value:
      user_id: "{{ user_id }}"
      expires_at: "{{ expires_at }}"
  case:
    - when: "{{ event.name == 'call.done' }}"
      then:
        - next:
            - step: confirm_stored
```

## Configuration

### Authentication

The NATS tool uses the unified authentication system:

```yaml
- step: get_value
  tool:
    kind: nats
    auth: my_nats_creds
    operation: kv_get
    bucket: cache
    key: user_123
```

### Connection Parameters

When credentials are resolved, these connection parameters are available:

| Parameter | Description |
|-----------|-------------|
| `nats_url` | NATS server URL (e.g., `nats://localhost:4222`) |
| `nats_user` | NATS username (optional) |
| `nats_password` | NATS password (optional) |
| `nats_token` | NATS token auth (alternative to user/pass) |
| `tls_cert` | TLS client certificate path (optional) |
| `tls_key` | TLS client key path (optional) |
| `tls_ca` | TLS CA certificate path (optional) |

## Operations

### K/V Store Operations

The K/V Store provides a simple key-value interface backed by JetStream.

#### kv_get - Get Value

Retrieve a value from the K/V store:

```yaml
- step: get_session
  tool:
    kind: nats
    auth: nats_credential
    operation: kv_get
    bucket: sessions
    key: "{{ session_id }}"
```

**Response:**
```json
{
  "status": "success",
  "bucket": "sessions",
  "key": "user_123",
  "value": {"user_id": 42, "expires_at": "2024-01-15T10:00:00Z"},
  "revision": 5,
  "created": "2024-01-14T10:00:00Z"
}
```

If key not found:
```json
{
  "status": "not_found",
  "bucket": "sessions",
  "key": "user_123",
  "value": null
}
```

#### kv_put - Store Value

Store a value in the K/V store:

```yaml
- step: cache_result
  tool:
    kind: nats
    auth: nats_credential
    operation: kv_put
    bucket: cache
    key: "result_{{ execution_id }}"
    value:
      computed_at: "{{ now() }}"
      data: "{{ previous_step.result }}"
```

**Response:**
```json
{
  "status": "success",
  "bucket": "cache",
  "key": "result_abc123",
  "revision": 1
}
```

#### kv_delete - Delete Key

Delete a key from the K/V store:

```yaml
- step: cleanup_session
  tool:
    kind: nats
    auth: nats_credential
    operation: kv_delete
    bucket: sessions
    key: "{{ session_id }}"
```

#### kv_keys - List Keys

List all keys in a bucket, optionally filtered by pattern:

```yaml
- step: list_user_sessions
  tool:
    kind: nats
    auth: nats_credential
    operation: kv_keys
    bucket: sessions
    pattern: "user_42_*"
```

**Response:**
```json
{
  "status": "success",
  "bucket": "sessions",
  "keys": ["user_42_session_1", "user_42_session_2"],
  "count": 2
}
```

#### kv_purge - Purge Key History

Purge all historical values for a key (keeps current):

```yaml
- step: purge_history
  tool:
    kind: nats
    auth: nats_credential
    operation: kv_purge
    bucket: audit_log
    key: "old_entry"
```

### Object Store Operations

The Object Store handles larger binary objects with chunking support.

#### object_put - Store Object

Store an object (supports binary data via base64):

```yaml
- step: store_report
  tool:
    kind: nats
    auth: nats_credential
    operation: object_put
    bucket: reports
    name: "report_{{ date }}.json"
    data: "{{ report_data | tojson }}"
    encoding: utf-8
```

For binary data:
```yaml
- step: store_binary
  tool:
    kind: nats
    auth: nats_credential
    operation: object_put
    bucket: files
    name: "image.png"
    data: "{{ base64_encoded_image }}"
    encoding: base64
```

**Response:**
```json
{
  "status": "success",
  "bucket": "reports",
  "name": "report_2024-01-14.json",
  "size": 1024,
  "digest": "SHA-256=abc123..."
}
```

#### object_get - Retrieve Object

Retrieve an object from the store:

```yaml
- step: get_report
  tool:
    kind: nats
    auth: nats_credential
    operation: object_get
    bucket: reports
    name: "report_{{ date }}.json"
    encoding: utf-8
```

**Response:**
```json
{
  "status": "success",
  "bucket": "reports",
  "name": "report_2024-01-14.json",
  "data": "{\"summary\": \"...\"}",
  "size": 1024
}
```

#### object_delete - Delete Object

```yaml
- step: delete_old_report
  tool:
    kind: nats
    auth: nats_credential
    operation: object_delete
    bucket: reports
    name: "report_old.json"
```

#### object_list - List Objects

```yaml
- step: list_reports
  tool:
    kind: nats
    auth: nats_credential
    operation: object_list
    bucket: reports
```

**Response:**
```json
{
  "status": "success",
  "bucket": "reports",
  "objects": [
    {"name": "report_2024-01-14.json", "size": 1024, "mtime": "2024-01-14T10:00:00Z", "digest": "SHA-256=..."},
    {"name": "report_2024-01-13.json", "size": 980, "mtime": "2024-01-13T10:00:00Z", "digest": "SHA-256=..."}
  ],
  "count": 2
}
```

#### object_info - Get Object Metadata

```yaml
- step: check_report
  tool:
    kind: nats
    auth: nats_credential
    operation: object_info
    bucket: reports
    name: "report_{{ date }}.json"
```

**Response:**
```json
{
  "status": "success",
  "bucket": "reports",
  "name": "report_2024-01-14.json",
  "size": 1024,
  "mtime": "2024-01-14T10:00:00Z",
  "digest": "SHA-256=abc123...",
  "chunks": 1
}
```

### JetStream Operations

JetStream provides persistent messaging with at-least-once delivery.

:::caution No Subscription Operations
The NATS tool does not support pull/subscribe operations as they would block playbook execution. Use `js_get_msg` to retrieve specific messages by sequence number or subject.
:::

#### js_publish - Publish Message

Publish a message to a JetStream stream:

```yaml
- step: publish_event
  tool:
    kind: nats
    auth: nats_credential
    operation: js_publish
    stream: events
    subject: "events.user.created"
    data:
      user_id: "{{ user_id }}"
      email: "{{ email }}"
      timestamp: "{{ now() }}"
    headers:
      X-Correlation-ID: "{{ execution_id }}"
```

**Response:**
```json
{
  "status": "success",
  "stream": "events",
  "seq": 42,
  "duplicate": false
}
```

#### js_get_msg - Get Message

Retrieve a specific message from a stream:

By sequence number:
```yaml
- step: get_message
  tool:
    kind: nats
    auth: nats_credential
    operation: js_get_msg
    stream: events
    seq: 42
```

Get last message:
```yaml
- step: get_latest
  tool:
    kind: nats
    auth: nats_credential
    operation: js_get_msg
    stream: events
    last: true
```

Get last message for subject:
```yaml
- step: get_last_user_event
  tool:
    kind: nats
    auth: nats_credential
    operation: js_get_msg
    stream: events
    subject: "events.user.{{ user_id }}"
```

**Response:**
```json
{
  "status": "success",
  "stream": "events",
  "subject": "events.user.created",
  "seq": 42,
  "data": {"user_id": 123, "email": "user@example.com"},
  "time": "2024-01-14T10:00:00Z",
  "headers": {"X-Correlation-ID": "exec_abc123"}
}
```

#### js_stream_info - Get Stream Info

Get information about a JetStream stream:

```yaml
- step: check_stream
  tool:
    kind: nats
    auth: nats_credential
    operation: js_stream_info
    stream: events
```

**Response:**
```json
{
  "status": "success",
  "stream": "events",
  "config": {
    "name": "events",
    "subjects": ["events.>"],
    "retention": "limits",
    "max_msgs": 1000000,
    "max_bytes": 1073741824,
    "max_age": 604800000000000
  },
  "state": {
    "messages": 42000,
    "bytes": 5242880,
    "first_seq": 1,
    "last_seq": 42000,
    "consumer_count": 3
  }
}
```

## Template Variables

Use Jinja2 templates in all string values:

```yaml
- step: store_user_data
  tool:
    kind: nats
    auth: nats_credential
    operation: kv_put
    bucket: "{{ workload.bucket_name }}"
    key: "user_{{ workload.user_id }}"
    value:
      email: "{{ validate_token.email }}"
      name: "{{ validate_token.name }}"
      login_at: "{{ now() }}"
```

## Examples

### Session Management

```yaml
- step: create_session
  desc: Store user session in NATS K/V
  tool:
    kind: nats
    auth: nats_auth
    operation: kv_put
    bucket: sessions
    key: "{{ session_token }}"
    value:
      user_id: "{{ user_id }}"
      email: "{{ email }}"
      created_at: "{{ now() }}"
      expires_at: "{{ expires_at }}"
  case:
    - when: "{{ event.name == 'call.done' and result.status == 'success' }}"
      then:
        - next:
            - step: return_session
```

### Event Publishing Pipeline

```yaml
- step: publish_order_event
  desc: Publish order created event to JetStream
  tool:
    kind: nats
    auth: nats_auth
    operation: js_publish
    stream: orders
    subject: "orders.{{ order_type }}.created"
    data:
      order_id: "{{ order_id }}"
      customer_id: "{{ customer_id }}"
      items: "{{ order_items }}"
      total: "{{ order_total }}"
    headers:
      X-Correlation-ID: "{{ execution_id }}"
      X-Source: "checkout-playbook"
  case:
    - when: "{{ event.name == 'call.done' }}"
      then:
        - next:
            - step: notify_fulfillment
```

### Cache Pattern

```yaml
- step: check_cache
  desc: Check if result is cached
  tool:
    kind: nats
    auth: nats_auth
    operation: kv_get
    bucket: api_cache
    key: "{{ cache_key }}"
  case:
    - when: "{{ event.name == 'call.done' and result.status == 'success' }}"
      then:
        - next:
            - step: return_cached
    - when: "{{ event.name == 'call.done' and result.status == 'not_found' }}"
      then:
        - next:
            - step: compute_result

- step: compute_result
  desc: Compute and cache the result
  tool:
    kind: python
    code: |
      result = expensive_computation()
  case:
    - when: "{{ event.name == 'call.done' }}"
      then:
        - cache_result:
            tool:
              kind: nats
              auth: nats_auth
              operation: kv_put
              bucket: api_cache
              key: "{{ cache_key }}"
              value: "{{ result }}"
        - next:
            - step: return_result
```

### File Storage with Object Store

```yaml
- step: store_report
  desc: Store generated report in Object Store
  tool:
    kind: nats
    auth: nats_auth
    operation: object_put
    bucket: reports
    name: "{{ report_type }}/{{ date }}/report_{{ execution_id }}.json"
    data: "{{ report_data | tojson }}"
  case:
    - when: "{{ event.name == 'call.done' }}"
      then:
        - next:
            - step: notify_report_ready
```

## Error Handling

Use case blocks to handle errors:

```yaml
- step: get_value
  tool:
    kind: nats
    auth: nats_auth
    operation: kv_get
    bucket: sessions
    key: "{{ session_id }}"
  case:
    - when: "{{ event.name == 'call.error' }}"
      then:
        - next:
            - step: handle_nats_error
    - when: "{{ event.name == 'call.done' and result.status == 'not_found' }}"
      then:
        - next:
            - step: session_not_found
    - when: "{{ event.name == 'call.done' and result.status == 'success' }}"
      then:
        - next:
            - step: process_session
```

## Best Practices

1. **Use meaningful bucket names**: Organize data by domain (sessions, cache, events)
2. **Key naming conventions**: Use prefixes like `user_`, `order_` for easy filtering
3. **TTL consideration**: K/V buckets can have TTL configured at the bucket level
4. **Avoid subscriptions**: Use `js_get_msg` for specific message retrieval; subscriptions would block execution
5. **Handle not_found**: Always check for `status: not_found` in K/V operations
6. **Credential security**: Store NATS credentials in keychain, never in playbooks
7. **Binary data**: Use `encoding: base64` for binary objects in Object Store

## See Also

- [PostgreSQL Tool](/docs/reference/tools/postgres) - For relational data storage
- [HTTP Tool](/docs/reference/tools/http) - For webhook callbacks
- [Authentication Reference](/docs/reference/auth_and_keychain_reference) - Credential management
