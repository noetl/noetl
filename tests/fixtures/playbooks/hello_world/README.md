# Hello World Test

This folder contains a simple "Hello World" playbook for testing basic NoETL functionality.

## Contents

- `hello_world.yaml` - Simple playbook that demonstrates basic workflow execution with Python action type
- `README.md` - This documentation file

## Playbook Overview

The `hello_world.yaml` playbook demonstrates:

1. **Basic Workflow Structure**: Shows the minimal required structure with start, action, and end steps
2. **Workload Variables**: Uses templated variables passed through the workflow
3. **Python Action Type**: Executes inline Python code with input data
4. **Event Logging**: Saves execution results to the event log

## Usage

### Register the Playbook

```bash
task test-register-hello-world
```

### Execute the Playbook

```bash
task test-execute-hello-world
```

### Full Test (Register + Execute)

```bash
task test-hello-world-full
```

## Expected Output

The playbook will:
1. Start with the message "Hello World" from workload
2. Execute a Python step that prints "HELLO_WORLD: Hello World"
3. Save the result to the event log
4. Complete successfully

This serves as a basic smoke test to verify that NoETL can:
- Register playbooks successfully
- Execute Python action types
- Handle variable templating
- Store execution results