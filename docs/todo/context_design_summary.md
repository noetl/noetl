# Context Design Summary

**Date:** November 11, 2025  
**Status:** Design Complete

---

## Overview

The DSL v2 refactoring introduces explicit context management with a structured dictionary pattern:

```python
context = {
  "workload": {...},      # Immutable: set at playbook initialization
  "var1": value1,         # Dynamic: runtime state
  "var2": value2,         # Mutable: updated by context sinks
  ...
}
```

---

## Key Design Decisions

### 1. Explicit Context Reference

All Python tools receive a `context` object as their main parameter:

```python
def main(context):
  # Access immutable workload
  api_key = context.workload.get('api_key')
  pg_auth = context.workload.get('pg_auth')
  
  # Access dynamic context state
  items = context.get('items', [])
  count = context.get('count', 0)
  
  return result
```

**Rationale:**
- Clear separation between immutable initialization data (`context.workload`) and dynamic runtime state
- Explicit access patterns prevent confusion about data source
- Type-safe: `context` is always a dict with known structure

### 2. Context Structure

**Mandatory Attribute:**
- `context.workload`: Immutable dict assigned during playbook initialization

**Dynamic Attributes:**
- All other keys are runtime state
- Updated via context sinks
- Accessible via `context.get(key, default)`

### 3. Jinja Template Access Patterns

```yaml
# Workload (immutable)
"{{ context.workload.api_key }}"
"{{ context.workload.pg_auth }}"

# Dynamic context variables
"{{ context.items }}"
"{{ context.count }}"

# Loop element variables (direct access)
"{{ item }}"
"{{ user }}"

# Step results (by step name)
"{{ previous_step.data }}"
"{{ fetch_config.response }}"
```

**Rationale:**
- Explicit `context.` prefix for clarity
- Loop variables don't need prefix (they're temporary)
- Step results accessible by step name

---

## Python Tool Pattern

### Standard Pattern

```yaml
- step: process_data
  tool:
    kind: python
    code: |
      def main(context):
        # Access workload
        auth = context.workload.get('pg_auth')
        
        # Access context state
        items = context.get('items', [])
        count = context.get('count', 0)
        
        # Process
        result = process(items, count)
        
        return result
    args:
      items: "{{ context.items }}"
      count: "{{ context.count }}"
```

### With Loop Element

```yaml
- step: process_items
  loop:
    collection: "{{ context.workload.items }}"
    element: item
  tool:
    kind: python
    code: |
      def main(context):
        # Access current loop element
        item = context.get('item')
        
        # Access workload
        api_key = context.workload.get('api_key')
        
        # Process
        return transform(item, api_key)
    args:
      item: "{{ item }}"  # Loop element passed via args
```

---

## Context Sink Pattern

Context sinks update the dynamic context state:

```yaml
sink:
  - kind: context
    assignment:
      # Append to array
      item_ids:
        mode: append
        value: "{{ item.id }}"
      
      # Increment counter
      total_count:
        mode: increment
        value: "{{ chunk.size }}"
      
      # Merge into dict
      metadata:
        mode: merge
        value:
          chunk_{{ chunk.index }}:
            rows: "{{ chunk.size }}"
      
      # Set/replace value
      latest_id:
        mode: set
        value: "{{ result.id }}"
```

---

## Access Comparison

### OLD (Ambiguous)

```python
def main(input_data):
  # Where does this come from?
  api_key = input_data.get('api_key')
  items = input_data.get('items')
  return result
```

```yaml
args:
  # Is this workload or context?
  api_key: "{{ api_key }}"
  items: "{{ items }}"
```

### NEW (Explicit)

```python
def main(context):
  # Clear: from immutable workload
  api_key = context.workload.get('api_key')
  
  # Clear: from dynamic context
  items = context.get('items')
  
  return result
```

```yaml
args:
  # Explicit source
  api_key: "{{ context.workload.api_key }}"
  items: "{{ context.items }}"
```

---

## Migration Guide

### Pattern 1: Simple Python Tool

**Before:**
```yaml
tool:
  kind: python
  code: |
    def main(input_data):
      return transform(input_data)
```

**After:**
```yaml
tool:
  kind: python
  code: |
    def main(context):
      # Access whatever you need from context
      data = context.get('data')
      return transform(data)
  args:
    data: "{{ context.my_data }}"
```

### Pattern 2: Workload Access

**Before:**
```yaml
tool:
  kind: http
  url: "{{ api_url }}"
  auth: "{{ pg_auth }}"
```

**After:**
```yaml
tool:
  kind: http
  url: "{{ context.workload.api_url }}"
  auth: "{{ context.workload.pg_auth }}"
```

### Pattern 3: Context Variables

**Before:**
```yaml
args:
  items: "{{ my_items }}"
  count: "{{ counter }}"
```

**After:**
```yaml
args:
  items: "{{ context.my_items }}"
  count: "{{ context.counter }}"
```

---

## Benefits

1. **Clarity:** Explicit distinction between immutable workload and dynamic state
2. **Type Safety:** `context` is always a dict with `workload` key
3. **Debugging:** Clear trace of where data originates
4. **Consistency:** All Python tools use same signature
5. **Flexibility:** Easy to add new context variables via sinks
6. **Isolation:** Workload can never be accidentally modified

---

## Implementation Notes

### Context Object Structure

```python
class ExecutionContext:
    def __init__(self, workload: dict):
        self._data = {"workload": workload}
    
    @property
    def workload(self) -> dict:
        """Immutable workload access"""
        return self._data["workload"]
    
    def get(self, key: str, default=None):
        """Get dynamic context value"""
        return self._data.get(key, default)
    
    def set(self, key: str, value):
        """Set dynamic context value"""
        if key == "workload":
            raise ValueError("Cannot modify workload")
        self._data[key] = value
```

### Jinja Environment Setup

```python
jinja_env.globals.update({
    "context": execution_context
})
```

This allows templates to access `{{ context.workload.* }}` and `{{ context.* }}`.

---

## Examples

See:
- `/docs/todo/01_dsl_refactoring_overview.md` - Complete DSL specification
- `/tests/fixtures/playbooks/v2api/v2_api_design_proposal.yaml` - Structured case examples

**Case Examples:**
- `case01_python_context` - Basic context access
- `case02_http_with_chunk` - HTTP with context sinks
- `case03_loop_sequential` - Loop with context accumulation
- `case07_context_accumulation` - All context sink modes
- `case08_summary` - Accessing accumulated context
