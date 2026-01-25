# Rhai Tool

Run Rhai scripts for lightweight transformations or token resolution.

## Basic Usage

```yaml
- step: compute_token
  tool:
    kind: rhai
    code: |
      let token = "abc";
      #{ auth_token: token }
```

## Notes

- Use Rhai for small, fast expressions.
- Return values with a map literal like `#{ key: value }`.
