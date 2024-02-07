# NoETL Workflow Execution System Documentation

NoETL ("Not Only ETL") is a workflow automation library and framework to simplify the process of defining, managing, and executing complex workflows. Particularly well-suited for orchestrating data processing pipelines, it extends beyond just ETL tasks and is designed for task automation in distributed runtime environments.

## Introduction

This repository contains the `noetl` library which is available on pip [here](https://pypi.org/project/noetl/). 

The actual runtime applications are located in other repositories:
- [API](https://github.com/noetl/noetl-api)
- [Plugins](https://github.com/noetl/noetl-plugins)
- [NATS Kubernetes dependencies](https://github.com/noetl/k8s)

The NoETL system is a workflow execution engine designed to automate the execution of tasks defined in a playbook or just deployed as services. It employs a publisher-subscriber pattern for `command` transmission and `event` reception using the NATS messaging system. Inspired by Erlang's architecture, NoETL leverages a plugin-based approach, enabling a scalable, resilient, and efficient execution environment.

## Architecture Overview

At its core, NoETL is built around a publisher-subscriber model that utilizes the NATS messaging system. This system is designed for the automated execution of tasks as defined by a specific playbook, incorporating an Erlang-inspired, plugin-based architecture.

## Plugin-Based Workflow and Erlang Design Principles

NoETL's architecture draws heavily from several key concepts of Erlang:

- **Everything as a Plugin:** All functional units in NoETL are treated as plugins, similar to Erlang's process encapsulation. These plugins are Docker images that can be executed as services or jobs within a Kubernetes environment. In playbooks, the term 'plugin' refers to an alias to Docker images.
- **Strong Isolation:** Each plugin operates independently and in isolation, akin to Erlang's process isolation.
- **Lightweight Plugin Management:** Dynamic and efficient creation and destruction of plugin instances are central to NoETL, enabling a scalable architecture.
- **Message Passing Interaction:** Plugins communicate through message passing via NATS streams, ensuring targeted and accurate messaging.
- **No Shared Resources:** Plugins operate without shared resources, fostering isolated execution and reduced contention.
- **Resilience and Reliability:** Each plugin is designed to perform effectively or fail gracefully, ensuring the robustness of the system.

## Workflow

In NoETL, workflows are defined as playbooks – YAMLs declarations to direct the execution of tasks. Each playbook describes a series of steps within tasks, where each step corresponds to a specific plugin implementation.

## Tasks and Steps

Tasks are the primary operational elements within a playbook, consisting of multiple sequential steps:

- **Parallel Task Execution:** Tasks can be executed concurrently, enhancing playbook efficiency.
- **Sequential Step Execution:** Steps within a task are executed in order, with each step needing to complete before the next begins.
- **Atomic Operation - Step:** The most atomic operation in NoETL is the 'step,' referring to the execution of a plugin module.

## Events and Commands

Events and commands drive the operation of NoETL:

- **Commands:** Trigger the execution of a step in the task.
- **Events:** Published upon step and task completion, signaling its end.

This model maintains a decoupled and fault-tolerant playbook execution.

## NATS Communication Subjects

Subjects in NoETL provide contextual information:

- **Command Subjects:** `command.<plugin_service_name>.<workflow_instance_id>`
- **Event Subjects:** `event.<plugin_service_name>.<workflow_instance_id>`
 
**N.B.** Error handling is a part of event subjects.

## Microservice-Plugin Architecture

NoETL includes several core service plugins:

- **NoETL GraphQL API plugin service:** Provides an interface for querying and interacting with NoETL using GraphQL.
- **Dispatcher plugin service:** Responsible for dispatch actions, steps' output, task queue management, and creating commands for the next steps to be executed by actual plugins.
- **Registrar plugin service:**  Manages playbook, plugin, and command reception and registration.

Plugins communicate using NATS messaging, driven by YAML playbooks specifying task sequences. The Kubernetes environment serves as the execution platform.  

### Prerequisites

- Python 3.11 or later
- [pip](https://pip.pypa.io/en/stable/installation/)
- Docker Desktop's Kubernetes cluster, for local development

### Installation

To install NoETL use `pip`:

```bash
pip install noetl
```
