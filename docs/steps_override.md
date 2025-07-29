# Steps override


- `workload.steps`:
A dictionary mapping step names to booleans/flags (e.g., pass/skip logic per step). Used for controlling which steps are skipped (via the pass attribute in workflow steps).


- `workload.steps_override`:
If present, it takes full control: only the steps listed here are executed in order, with no workflow logic, transitions, or pass checks.  
It can be a list (just step names) or a dict (step name -> with params).

```yaml
workload:
  steps:
    create_results_table: false
    get_openai_api_key: true
  steps_override:
    - get_openai_api_key
    - get_amadeus_api_key
    # OR
    # get_openai_api_key: {param1: value1}
    # get_amadeus_api_key: {}
```

## Behavior:

- If `steps_override` is present, only those steps are executed, ignoring all workflow logic and pass flags.
- If only `steps` is present, workflow runs as normal, but steps with `pass: true` are skipped.