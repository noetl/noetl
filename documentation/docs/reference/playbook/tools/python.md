# Python Plugin

## Overview

The Python plugin executes user-provided Python code inside a step. It is designed to be flexible with function signatures and straightforward in how step `data` is passed to your `main()` function. It also powers the `sink: { storage: python }` storage mode.

Key behaviors:
- Step `data` is rendered via Jinja2 before execution.
- The plugin inspects your `main()` function signature to decide how to pass arguments.
- A framework `context` object is available during execution.

---

## How **kwargs works in type: python steps
How **kwargs Works in type: python Steps
When you define a step like this:
```yaml
- step: initialize_test_data
  desc: "Generate initial test data"
  tool: python
  code: |
    def main(**kwargs):
        # Your Python code here
  data:
    execution_id: "{{ execution_id }}"
    workload: "{{ workload }}"
```

Here's what happens:
1. Data Collection and Passing
The NoETL engine collects all the key-value pairs from the data section and passes them as keyword arguments to your main() function. So:
```python
def main(**kwargs):
    # kwargs will contain:
    # {
    #   'execution_id': 'actual_execution_id_value',
    #   'workload': {...workload_object...}
    # }
```

2. Accessing the Arguments
Inside your function, you can access these arguments in several ways:
```python
def main(**kwargs):
    # Method 1: Direct access via kwargs dictionary
    execution_id = kwargs.get("execution_id", "unknown")
    workload = kwargs.get("workload", {})
    
    # Method 2: Extract specific arguments (Python 3.5+)
    execution_id = kwargs.get("execution_id")
    
    # Method 3: Use context (if available in the framework)
    execution_id = context.get("execution_id", "unknown")
```

3. Context vs kwargs
In your code, I notice you're using both approaches:
```python
def main(**kwargs):
    # Using context object (framework-provided)
    "execution_id": context.get("execution_id", "unknown"),
    
    # You could also use kwargs:
    # "execution_id": kwargs.get("execution_id", "unknown"),
```

The context object appears to be a global framework object that contains execution context, while **kwargs contains the specific data passed from the data section of your step.
4. Alternative Function Signatures
You could also define your function with explicit parameters:
```python
# Instead of **kwargs, you could use:
def main(execution_id=None, workload=None, **other_kwargs):
    # Direct access to named parameters
    test_data = {
        "execution_id": execution_id or "unknown",
        "workload_data": workload,
        # ...
    }
```

5. Data Flow Example
Here's how the data flows in your specific case:
```yaml
data:
  execution_id: "{{ execution_id }}"  # Template renders to actual ID
  workload: "{{ workload }}"          # Template renders to workload object
```

Becomes:
```python
# NoETL calls your function like this:
main(
    execution_id="abc123-execution-id", 
    workload={
        "test_name": "save_storage_comprehensive_test",
        "base_data": {...}
    }
)
```

6. Best Practice
For clarity and robustness, you might want to use both approaches:
```yaml
    code: |
      def main(**kwargs):
          import json
          from datetime import datetime
          
          # Extract data from kwargs with fallbacks
          execution_id = kwargs.get("execution_id") or context.get("execution_id", "unknown")
          workload = kwargs.get("workload", {})
          
          # Generate comprehensive test dataset
          test_data = {
              "execution_id": execution_id,
              "test_suite": "save_storage_types",
              "generated_at": datetime.now().isoformat(),
# ... existing code ...
```

This way, you have explicit access to the parameters passed via the data section while maintaining flexibility with **kwargs for any additional parameters the framework might pass.

## Definition and executor implementation

This section describes what “type: python” means and how the executor runs your code behind the scenes.

1) Step definition
- A Python step is defined with:
  - type: python
  - code: a Python source string that must define a callable named main
  - data: an optional mapping of inputs (templated via Jinja2)
  - assert (optional): expects/returns interface checks
  - save (optional): an instruction to persist results; when storage: python is used, the same executor runs the provided code with the step result payload

Typical shape:
- Workflow step with inline code:
  type: python
  data: {...}            # Inputs rendered before execution
  code: |
    def main(...):
        ...

- Workbook task aliased by name:
  type: workbook
  name: <python_task_name>  # The task defines type: python and code: main(...)

2) Execution pipeline (implemented by the Python executor)
- Prepare context:
  - The engine assembles a context object containing execution metadata (e.g., execution_id, workload, previous step outputs, and other runtime values).
  - A Jinja environment is prepared for template rendering.

- Render templates:
  - All string values under data are rendered via Jinja2 with access to execution_id, workload, prior step data, and other context variables.
  - The rendered mapping (dictionary) becomes the “input payload” for main.

- Load and locate main:
  - The executor evaluates your code string in a fresh module-like namespace.
  - The symbol main must be present and callable; otherwise an error is raised.

- Inspect function signature and bind arguments:
  - The executor inspects main’s signature to determine how to pass inputs:
    - If main accepts **kwargs, all keys from the rendered data mapping are passed as keyword arguments.
    - If main has exactly one non-variadic parameter (commonly named input_data), the entire rendered data mapping is passed as a single argument to that parameter.
    - Otherwise, the executor matches keys by parameter name and passes those as named arguments. Missing required parameters cause a validation error; extra keys cause a TypeError unless main defines **kwargs.
    - A main() with no parameters runs without inputs (you can use context inside).

- Invoke and capture output:
  - The executor calls main with the chosen argument mapping.
  - Stdout/stderr are captured by the engine’s logging facilities where applicable.

- Normalize return:
  - If your function returns a dict that already contains a top-level status key, it is preserved as-is.
  - Otherwise, any return value is wrapped as:
    {"status": "success", "data": <returned_value>}
  - Exceptions are caught and returned as:
    {"status": "error", "error": "<message>"}

- Apply assertions (if provided):
  - expects: Verifies that the rendered data contains all required input keys before execution.
  - returns: Verifies that the function output (data payload) contains specified keys after execution.

- Save (if configured):
  - If the step includes save, the normalized result is forwarded to the save subsystem.
  - When save.storage.type is python, the storage code is executed using the same executor, typically with def main(data): receiving the result payload from the step. You can also use **kwargs or named params; the executor applies the same signature rules.

- Logging and redaction:
  - Sensitive values are redacted in logs where applicable.
  - Errors are surfaced through the normalized error payload.

3) Supported function signatures recap
- def main(): no inputs; use context if needed.
- def main(input_data): the entire rendered data mapping is passed as a single dict.
- def main(**kwargs): each key from data becomes a keyword argument.
- def main(a, b, *, c=None, **rest): named parameters matched from data by name; extra keys land in **rest if declared.

4) Error scenarios
- Missing required input:
  - A required parameter has no value in data and no default. Fix by adding the key in data, providing a default in your signature, or switching to def main(input_data) or **kwargs.
- Unexpected input:
  - main doesn’t accept a provided key and has no **kwargs. Fix by aligning parameter names or using **kwargs.
- main not found or not callable:
  - Ensure your code defines def main(...): at top level.
- Exception during execution:
  - The executor returns {"status": "error", "error": "<message>"} and logs the stack trace.

5) Practical tips
- Prefer explicit arguments or **kwargs over relying solely on context for testability and clarity.
- Keep returned payloads structured; downstream steps consume result.data.
- Use assertions (expects/returns) for clearer contracts between steps.
- Make steps idempotent where possible.


When you define a step like this:
- Return values are normalized so downstream steps can consume results consistently.

How **kwargs Works in NoETL Python Plugin
From the documentation and code patterns I can see, here's how the NoETL framework handles **kwargs in type: python steps:
1. Function Signature Processing
The NoETL Python plugin supports multiple function signatures for the main() function:
```python
# Option 1: Single input_data parameter
def main(input_data):
    return {"result": "processed"}

# Option 2: **kwargs parameter (your case)
def main(**kwargs):
    return {"result": "processed"}

# Option 3: Named parameters
def main(execution_id, workload):
    return {"result": "processed"}
```

2. Data Preparation and Injection
When you define a step like this:
```yaml
- step: initialize_test_data
  tool: python
  data:
    execution_id: "{{ execution_id }}"
    workload: "{{ workload }}"
  code: |
    def main(**kwargs):
        # Your code here
```

The NoETL framework:
Renders the data section using Jinja2 templates
Inspects your main() function signature to determine how to call it
Passes the data appropriately based on the signature
3. **kwargs Implementation
For def main(**kwargs):, the framework:
Takes all key-value pairs from the rendered data section
Passes them as keyword arguments to your function
Your function receives them as kwargs dictionary
So this:
```yaml
data:
  execution_id: "{{ execution_id }}"
  workload: "{{ workload }}"
```

Becomes this function call:
```python
main(execution_id="actual_execution_id", workload={...workload_object...})
```

4. Context Object
The context object you're using in your code (context.get("execution_id", "unknown")) is likely a global object that the NoETL framework injects into the execution environment, separate from the **kwargs parameters.
5. Best Practice Implementation
Here's how you should handle both approaches:
```python
def main(**kwargs):
    import json
    from datetime import datetime
    
    # Get from kwargs (data section)
    execution_id_from_data = kwargs.get("execution_id")
    workload_from_data = kwargs.get("workload", {})
    
    # Get from context (framework globals)
    execution_id_from_context = context.get("execution_id", "unknown")
    
    # Use whichever is available (prioritize data section)
    execution_id = execution_id_from_data or execution_id_from_context
    
    test_data = {
        "execution_id": execution_id,
        "test_suite": "save_storage_types",
        "generated_at": datetime.now().isoformat(),
        # ... rest of your code
    }
```

6. Framework Flexibility
The NoETL Python plugin likely uses Python's inspect module to determine your function signature and calls it appropriately:
If you use def main(input_data):, it passes all data as a single dict
If you use def main(**kwargs):, it passes individual keys as keyword arguments
If you use def main(execution_id, workload):, it maps specific parameters
This design allows maximum flexibility in how you structure your Python functions within NoETL playbooks.



