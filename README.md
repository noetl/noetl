# NoETL Documentation
__NoETL__ ("Not Only ETL") is a workflow automation framework designed for processing data in distributed runtime environments.

  - [NoETL Playbook Specification](wiki/playbook_specification.md)

Originally built for data pipelines and MLOps orchestration, NoETL supports advanced use cases in __Agentic AI automation__ of dynamic, plugin-based task execution at scale.

---

## Introduction

This repository contains the `noetl` Python library, available on PyPI:  
- [__NoETL on PyPI__](https://pypi.org/project/noetl/)
- NoETL is a workflow execution engine designed to automate tasks defined in [YAML-based playbooks](wiki/playbook_specification.md). 
- The architecture draws inspiration from Erlang's resilience and modular design principles.

---

## Architecture Overview

Tasks are executed according to [declarative playbooks](wiki/playbook_specification.md), and plugins are treated as isolated services.

### Process-Based Design Inspired by Erlang

#### Key Principles:

- **Everything is a Process:** Every unit of execution whether a task, step, or plugin—is treated as an isolated, addressable process with its own lifecycle and context. These processes may be short-lived (jobs) or long-lived (services), and they communicate asynchronously through messages.
- **Strong Isolation:** Each process runs independently, with no shared state. Failures are contained and localized.
- **Dynamic Scaling:** Processes can be created and terminated on demand, allowing the system to scale fluidly.
- **Asynchronous Messaging:** Processes interact through targeted, decoupled message passing, not shared memory or direct function calls.
- **Fail-Fast & Resilient:** Each process is designed to either complete its task or fail gracefully.

---

## Workflow

Workflows are defined using [YAML-based playbooks](wiki/playbook_specification.md). 

### Tasks and Steps

- **Task:** A named set of units that can be executed in parallel or sequentially.  
- **Step:** A state of the system transaction, representing a transition invocation.

---

## Events and Commands

The runtime is event-driven:

- **Command:** trigger a specific plugin or step execution.  
- **Event:** emitted after step or task completion, used to signal readiness or failure.

---


## Prerequisites

- Python 3.12+
- [pip](https://pip.pypa.io/en/stable/installation/)
- Docker (for local plugin development and testing)

---

## Installation

Install NoETL with:

```bash
make install-uv        # Install uv pip
make create-venv       # Create a Python virtual environment
source .venv/bin/activate
make install           # Install dependencies
make build             # Initialize environment (PostgreSQL, NoETL server)
make up                # Start docker services
noetl server           # Run the NoETL server
```
## License
NoETL is open source and available under the MIT License.