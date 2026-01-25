# HTTP Tool

Call HTTP endpoints with optional auth and retries.

## Basic Usage

```yaml
- step: fetch
  tool:
    kind: http
    method: GET
    url: "https://api.example.com/v1/health"
```

## Notes

- Use `headers`, `params`, and `body` to control requests.
- For pagination, use the `loop.pagination` block.
