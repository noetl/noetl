# NoETL Playbook Structure Guide

This guide explains the structure and components of NoETL playbooks.

## Overview

NoETL playbooks are YAML files that define workflows for data processing and automation. A playbook consists of several main sections:

- **Metadata**: Information about the playbook itself
- **Workload**: Input data and parameters for the workflow
- **Workflow**: The steps and tasks that make up the workflow

## Basic Structure

Here's the basic structure of a NoETL playbook:

```yaml
# Metadata
version: "1.0.0"
path: "workflows/example/playbooks"
description: "Example playbooks"

# Workload (input data and parameters)
workload:
  param1: "value1"
  param2: "value2"

# Workflow (steps)
workflow:
  - step: start
    type: start
    next:
      - step: step1

  - step: step1
    call:
      name: step1
      type: some_task
      with:
        param1: "value1"
    next:
      - step: end

  - step: end
    type: end
```

## Metadata

The metadata section contains information about the playbook itself:

- **version**: The version of the playbook
- **path**: The path of the playbook in the catalog (e.g., "workflows/example/playbook")
- **description**: A description of what the playbook does

Example:

```yaml
version: "1.0.0"
path: "workflows/example/playbooks"
description: "Example playbooks of basic functionality"
author: "John Doe"
tags:
  - "example"
  - "basic"
```

## Workload

The workload section contains input data and parameters for the workflow. This can include any data that the workflow needs to process, as well as configuration parameters.

Example:

```yaml
workload:
  name: "John Doe"
  age: 30

  address:
    street: "123 Main St"
    city: "Anytown"
    state: "CA"
    zip: "12345"

  items:
    - name: "Item 1"
      price: 10.99
    - name: "Item 2"
      price: 20.99
```

## Workflow

The workflow section defines the steps and tasks that make up the workflow. Each step has a unique name and properties that define what it does and what happens next.

### Steps


### Start Step

The start step is the entry point of the workflow. It must have a `next` property that points to the next step.

Example:

```yaml
workflow:
  - step: start
    type: start
    next: fetch_data
```

### Task Step

A task step performs a specific task, such as fetching data, transforming data, or sending a notification. It has a `task` property that specifies the task to perform, and a `params` property that provides parameters for the task.

Example:

```yaml
- step: fetch_data
  call:
    name: fetch_data
    type: http
    method: GET
    endpoint: "https://api.example.com/data"
    headers:
      Authorization: "Bearer {{ workload.api_key }}"
  next: process_data
```

### Condition Step

A condition step evaluates a condition and branches the workflow based on the result. It uses `when` and `then` clauses to specify the condition and the next steps to execute when the condition is true or false.

Example:

```yaml
- step: check_status
  next:
    - when: "{{ fetch_data.response.status_code == 200 }}"
      then:
        - step: process_data
    - else:
        - step: handle_error
```

Tip (exact-match OR): to match any of several exact values (complete match), prefer list membership:

```yaml
- step: choose_file_branch
  next:
    - when: "{{ workload.filename in ['error_log.json', 'event_log.json', 'queue.json'] }}"
      then:
        - step: handle_known_file
    - else:
        - step: handle_other_file
```

See also: [Query Conditions: Exact/Complete Match with OR](query_conditions.md)



- [Workflow Tasks](action_type.md) - Learn about available tasks and their parameters
- [CLI Usage Guide](cli_usage.md) - Learn how to use the NoETL command-line interface
- [API Usage Guide](api_usage.md) - Learn how to use the NoETL REST API
- [Examples](examples.md) - See more examples of NoETL playbooks
