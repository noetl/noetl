# NoETL Documentation
__NoETL__ ("Not Only ETL") is an _Agentic AI automation framework_ designed for MLOps orchestration and processing data in distributed runtime environments.

  - [NoETL Playbook Specification](wiki/playbook_specification.md)
  - [NoETL Playbook Weather Example](data/catalog/playbooks/weather_example.yaml)

---

## Introduction

This repository contains the `noetl` Python library, available on PyPI:  
- [__NoETL on PyPI__](https://pypi.org/project/noetl/)
- NoETL is a workflow execution engine designed to automate tasks defined in [YAML-based playbooks](wiki/playbook_specification.md). 
- The architecture draws inspiration from Erlang's resilience and modular design principles.

---

## Architecture Overview

- Workflows are executed according to [declarative playbooks](wiki/playbook_specification.md)  
- [Execution Model](wiki/execution_model.md)

### Process-Based Design Inspired by Erlang

#### Key Principles:

- **Everything is a Process:** Every unit of execution whether a task, step, are treated as an isolated, addressable process with its own lifecycle and context. These processes may be short-lived (jobs) or long-lived (services), and they communicate asynchronously through messages.
- **Strong Isolation:** Each process runs independently, with no shared state. Failures are contained and localized.
- **Dynamic Scaling:** Processes can be created and terminated on demand, allowing the system to scale fluidly.
- **Asynchronous Messaging:** Data is passing only via explicit context/messages between tasks and steps, inspired by Erlang's process model.
- **Fail-Fast & Resilient:** Each process is designed to either complete its task or fail gracefully.


#### Benefits for Data Processing:

- __Isolation:__ Each task operates on its own data, reducing side effects and making debugging easier.
- __Composability:__ Chain and nest tasks flexibly, as each task only needs its input.
- __Parallelism:__ Isolated tasks can be run in parallel for streaming data processing pipelines.
- __Determinism:__ No hidden state, data flows are explicit and traceable.
- __Error Handling:__ Failures are contained and routed to error handlers, just like Erlang's "let it crash".

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