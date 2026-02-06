---
sidebar_position: 9
title: NATS Tool (Canonical v10)
description: Interact with NATS JetStream, K/V Store, and Object Store as pipeline tasks (Canonical v10)
---

# NATS Tool (Canonical v10)

The `nats` tool provides access to NATS JetStream, Key/Value store, and Object Store operations for caching, messaging, and lightweight state.

Canonical reminders:
- No step-level `case`/`eval`/`expr`. Use `when` in task policy and router arcs.
- Use `task.spec.policy.rules` for retry/fail/jump/break/continue.

---

## Basic usage

```yaml
- step: cache_value
  tool:
    - put:
        kind: nats
        auth: nats_credential
        operation: kv_put
        bucket: sessions
        key: "{{ workload.session_id }}"
        value:
          user_id: "{{ workload.user_id }}"
          expires_at: "{{ workload.expires_at }}"
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: break }
```

---

## Operations (selection)

K/V store:
- `kv_get`, `kv_put`, `kv_delete`, `kv_keys`, `kv_purge`

Object store:
- `object_get`, `object_put`, `object_delete`, `object_list`, `object_info`

JetStream:
- `js_publish`, `js_get_msg`, `js_stream_info`

Operation inputs are tool-specific (bucket/key/value/name/subject/etc).

---

## See also
- Auth & keychain: `documentation/docs/reference/auth_and_keychain_reference.md`
