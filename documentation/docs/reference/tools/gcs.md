---
sidebar_position: 7
title: GCS Tool (Canonical v10)
description: Upload local files to Google Cloud Storage as pipeline tasks (Canonical v10)
---

# GCS Tool (Canonical v10)

The `gcs` tool uploads a local file to Google Cloud Storage (`gs://...`).

> Note: this tool is for explicit file uploads. For **reference-first** step outputs (ResultRef), see `documentation/docs/reference/result_storage_canonical_v10.md`.

---

## Basic usage

```yaml
- step: upload_file
  tool:
    - upload:
        kind: gcs
        source: "/tmp/output.csv"
        destination: "gs://my-bucket/data/output.csv"
        credential: gcp_service_account
        spec:
          policy:
            rules:
              - when: "{{ outcome.status == 'error' }}"
                then: { do: fail }
              - else:
                  then: { do: break }
```

---

## Common fields

| Field | Type | Meaning |
|---|---|---|
| `source` | string | Local file path |
| `destination` | string | GCS URI (`gs://bucket/path`) |
| `credential` | string | Credential/keychain reference name |
| `content_type` | string | Optional MIME type |
| `metadata` | mapping | Optional object metadata |

---

## See also
- Result storage (reference-first): `documentation/docs/reference/result_storage_canonical_v10.md`
- Auth & keychain: `documentation/docs/reference/auth_and_keychain_reference.md`
