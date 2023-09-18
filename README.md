# NoETL Workflow Automation Framework

NoETL is a workflow automation framework designed to simplify the process of defining, managing, and executing complex workflows. It is especially well-suited for orchestrating data processing pipelines and task automation.

## Table of Contents
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Installation](#installation)
- [Configuration](#configuration)
  - [Configuration Rules](#configuration-rules)
  - [Referencing Data and Configuration](#referencing-data-and-configuration)
- [Usage](#usage)
- [Folder Structure](#folder-structure)
- [Contributing](#contributing)
- [License](#license)

Managing and orchestrating complex workflows is challenging, especially when dealing with data processing tasks, dependencies, and error handling. NoETL aims to address these challenges by providing the following benefits:

- **Flexibility**: NoETL allows you to define workflows using configuration files, making it easy to modify, extend, and adapt workflows as needed.

- **Scalability**: As your workflows grow in complexity, NoETL provides a structured way to manage tasks, dependencies, and transitions.

- **Automation**: NoETL automates the execution of tasks, reducing the need for manual intervention and streamlining data processing pipelines.

- **Error Handling**: NoETL includes error handling mechanisms, allowing you to define what happens when a task fails and how to proceed.

## Getting Started

### Prerequisites

Before using NoETL, make sure you have the following prerequisites installed on your system:

- Python 3.10 or later
- [pip](https://pip.pypa.io/en/stable/installation/)

### Installation

To install NoETL, you can use `pip`:

```bash
pip install noetl
```

## Configuration Rules

In the workflow configuration file, certain fields like `initialSettings.start` and `transitions` should follow specific rules for readability and flexibility.

### `initialSettings.start`

- In the configuration file, `initialSettings.start` should be defined as a comma-separated string.
- Example in the configuration file:
  ```yaml
  initialSettings:
    start: "check-repository, check-repository"
 
When reading this value in the source code using Config.get_value, it will be automatically converted to a list if it contains commas.
Example when reading the value in code:

```python
start_tasks = config.get_value("initialSettings.start")
# If the value in the configuration file is "check-repository, check-account",
# `start_tasks` will be ["check-repository", "check-account"] as a list.
```

### transitions
In the configuration file, transitions should be defined as a comma-separated string.
Example in the configuration file:
```yaml
transitions:
  ready: "running"
  running: "completed, failed, terminated"
```

When reading these values in the code by `Config.get_value`, they will be automatically converted to lists.
Example when reading the values in code:
```python
ready_transition = config.get_value("transitions.ready")
running_transition = config.get_value("transitions.running")
```

## Referencing Data and Configuration in Workflow using Placeholders

In NoETL workflow, we can refer both data and configuration settings using placeholders.

### Data Referencing

- If a placeholder starts with `{{data.`, the reference data comes from the event store.
- The convention is to extract the `blabla` part following `{{data.` and prepend it with the instanceId to form a key.
- This key is used to look up the data in the event store.

### Configuration Referencing

- If a placeholder does not start with `{{data.`, it refers to configuration data.
- When referencing configuration data, NoETL recursively searches through the configuration settings to find the requested value.
- You can reference configuration values starting with `spec` or `metadata`, and NoETL will navigate through the configuration structure to find the value.

### Example

#### Data Referencing
Suppose you have the following placeholder: `{{data.exampleField}}`.

- If the workflow instanceId is `test-instance`, it would look up `test-instance.exampleField` in the event store.

#### Configuration Referencing
Suppose we have the following placeholder: `{{spec.vars.GCP_PROJECT_ID}}`.

- NoETL will search through the configuration settings, starting with `spec`, to find the value of `GCP_PROJECT_ID`.

This convention allows to refer both data and configuration settings within NoETL to control workflows.

## Usage
NoETL automates workflow management and automation. 

1. Define Workflow Configuration: Create a configuration file that defines workflow. Use the configuration rules mentioned above to structure your workflow.

2. Initialize a Workflow: Use the Workflow.create() method to initialize a new workflow instance. Provide it with a workflow template and an event store.

```python
workflow_template = Config.create()
workflow = Workflow.create(workflow_template, EventStore("event_store"))
```

3. Run Workflow: Call the run_workflow() method on a workflow instance to start the execution of the workflow. This method will handle initializing tasks, managing transitions, and executing steps.
```python
asyncio.run(workflow.run_workflow())
```
4. Customize Your Workflow: Extend the functionality of NoETL by creating custom steps, tasks, and event handling logic to suit any specific workflow requirements.
5. Monitor and Debug: Use logging and event handling to monitor the progress of the workflow and handle errors gracefully.

## Folder Structure
The folder structure of your NoETL project might look like this:
```
.
├── LICENSE
├── README.md
├── noetl/
│   ├── __init__.py
│   ├── config.py
│   ├── event_store.py
│   ├── noetl.py
│   ├── step.py
│   └── task.py
├── requirements.txt
└── tests/
    ├── __init__.py
    ├── test_config.py
    ├── test_data/
    └── test_event_store.py
```

## License
This project is licensed under the MIT License - see the LICENSE file for details.
