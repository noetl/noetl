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
- [License](#license)

Managing and orchestrating complex workflows is challenging, especially when dealing with data processing tasks, dependencies, and error handling. NoETL aims to address these challenges by providing the following benefits:

- **Flexibility**: NoETL allows you to define workflows using configuration files, making it easy to modify, extend, and adapt workflows as needed.

- **Scalability**: As your workflows grow in complexity, NoETL provides a structured way to manage tasks, dependencies, and transitions.

- **Automation**: NoETL automates the execution of tasks, reducing the need for manual intervention and streamlining data processing pipelines.

- **Error Handling**: NoETL includes error handling mechanisms, allowing you to define what happens when a task fails and how to proceed.

## Getting Started

### Prerequisites
- Python 3.10 or later
- [pip](https://pip.pypa.io/en/stable/installation/)

### Installation

To install NoETL use `pip`:

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
Suppose we have the following placeholder: `{{data.exampleField}}`.

- If the workflow instanceId is `test-instance`, it would look up `test-instance.exampleField` in the event store.

#### Configuration Referencing
Suppose we have the following placeholder: `{{spec.vars.GCP_PROJECT_ID}}`.

- NoETL will search through the configuration settings, starting with `spec`, to find the value of `GCP_PROJECT_ID`.

This convention allows us to refer both data and configuration settings within NoETL to control workflows.

## Usage
NoETL automates workflow management and automation. 

1. Define Workflow Configuration: Create a configuration file that defines workflow. Use the configuration rules mentioned above to structure your workflow.
Configuration File: Example of configuration file named `create-artifact-repository.yaml` in the `workflows/gcp` project folder.
2. To execute the noetl.py script, run the following command: 
```python
python noetl.py CONFIG=${WORKFLOW_DIR}/create-artifact-repository.yaml GCP_PROJECT_ID=test GCP_REGION=us-west1 REPOSITORY_NAME=test
```
- CONFIG: Path to the workflow configuration file.
- GCP_PROJECT_ID: Google Cloud Platform (GCP) project ID.
- GCP_REGION: The GCP region of the artifact repository.
- REPOSITORY_NAME: The name of the artifact repository to be created.


## License
This project is licensed under the MIT License - see the LICENSE file for details.


## CLI 
```bash
 python -m spacy download en_core_web_sm
```
