# Validation: Schema Fragments

This page documents the JSON Schema fragments relevant to the credential model. These are illustrative and may be composed into the full playbook schema.

## Common Types

```json
{
  "$defs": {
    "credentialBinding": {
      "type": "object",
      "properties": {
        "key": { "type": "string" }
      },
      "required": ["key"],
      "additionalProperties": false
    },
    "credentialsMap": {
      "type": "object",
      "additionalProperties": { "$ref": "#/$defs/credentialBinding" }
    }
  }
}
```

## Postgres Step

```json
{
  "type": "object",
  "properties": {
    "type": { "const": "postgres" },
    "auth": { "type": "string" },
    "with": { "type": "object" }
  },
  "required": ["type", "auth"],
  "additionalProperties": true
}
```

## DuckDB Step

`auth` vs `credentials` are mutually exclusive here (DuckDB typically needs multiple bindings; use `credentials`).

```json
{
  "type": "object",
  "properties": {
    "type": { "const": "duckdb" },
    "credentials": { "$ref": "#/$defs/credentialsMap" },
    "commands": { "type": ["string", "array"] }
  },
  "required": ["type"],
  "allOf": [
    {
      "not": {
        "required": ["auth"]
      }
    }
  ],
  "additionalProperties": true
}
```

## HTTP Step

`secret` references are used inside templates at runtime, not as a top-level key. Example:

```yaml
headers:
  Authorization: "Bearer {{ secret.api_service_token }}"
```

