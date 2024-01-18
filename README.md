# NoETL Workflow Execution System Documentation

NoETL is a workflow automation framework designed to simplify the process of defining, managing, and executing complex workflows. It is especially well-suited for orchestrating data processing pipelines and task automation.

## Introduction

This repository contains the `noetl` library which is available on pip [here](https://pypi.org/project/noetl/). 

The actual runtime applications are located in other repositories:
- [API](https://github.com/noetl/noetl-api)
- [Plugins](https://github.com/noetl/noetl-plugins)
- [NATS Kubernetes dependencies](https://github.com/noetl/k8s)

The NoETL system is a workflow execution engine designed to automate the execution of tasks defined in a playbook or just deployed as a services. It employs a publisher-subscriber pattern for command transmission and event reception using the NATS messaging system. Inspired by Erlang's architecture, NoETL leverages a plugin-based approach, enabling a scalable, resilient, and efficient execution environment.

## Architecture Overview

At its core, NoETL is built around a publisher-subscriber model that utilizes the NATS messaging system. This system is designed for the automated execution of tasks as defined by a specific playbook, incorporating an Erlang-inspired, plugin-based architecture.

## Plugin-Based Workflow and Erlang Design Principles

NoETL's architecture draws heavily from several key concepts of Erlang:

- **Everything as a Plugin:** All functional units in NoETL are treated as plugins, similar to Erlang's process encapsulation. These plugins are Docker images that can be executed as services or jobs within a Kubernetes environment. In playbooks, the term 'plugin' refers to these Docker images.
- **Strong Isolation:** Each plugin operates independently and in isolation, akin to Erlang's process isolation.
- **Lightweight Plugin Management:** Dynamic and efficient creation and destruction of plugin instances are central to NoETL, enabling a scalable architecture.
- **Message Passing Interaction:** Plugins communicate through message passing via NATS streams, ensuring targeted and accurate messaging.
- **No Shared Resources:** Plugins operate without shared resources, fostering isolated execution and reduced contention.
- **Resilience and Reliability:** Each plugin is designed to perform effectively or fail gracefully, ensuring the robustness of the system.

## Workflow

In NoETL, workflows are defined as playbooks – YAML scripts that orchestrate the execution of tasks in a predefined sequence. Each playbook describes a series of steps within tasks, where each step corresponding to a specific plugin.

## Tasks and Steps

Tasks are the primary operational elements within a playbook, consisting of multiple sequential steps:

- **Parallel Task Execution:** Tasks can be executed concurrently, enhancing playbook efficiency.
- **Sequential Step Execution:** Steps within a task are executed in order, with each step needing to complete before the next begins.
- **Atomic Operation - Step:** The most atomic operation in NoETL is the 'step,' referring to the execution of a plugin module.

## Events and Commands

Events and commands drive the operation of NoETL:

- **Commands:** Trigger the execution of step in the task.
- **Events:** Published upon step and task completion, signaling its end.

This model maintains a decoupled and fault-tolerant playbook execution.

## NATS Communication Subjects

Subjects in NoETL provide contextual information:

- **Command Subjects:** `command.<plugin_name>.<workflow_id>.<step_id>`
- **Event Subjects:** `event.<plugin_name>.<workflow_id>.<step_id>`

## Mini-Plugin Architecture

NoETL includes several service plugins:

- **Command API Plugin:** Manages playbook, plugin, and command reception and registration.
- **Event API Plugin:** Tracks events and manages event data.
- **Dispatcher API Plugin:** Responsible for dispatch actions, task queue management, and command execution.

These plugins communicate using NATS messaging, driven by YAML playbooks specifying task sequences. The Kubernetes environment serves as the execution platform for these plugins.

## Conclusion

NoETL's architecture, embodying scalability, robustness, and fault-tolerance, is key to a reliable workflow execution system. Its distributed nature, combined with the efficiency of the plugin system and the resilience of its components, makes NoETL a great solution for complex workflow automation.

### Prerequisites

- Python 3.11 or later
- [pip](https://pip.pypa.io/en/stable/installation/)
- Docker Desktop's Kubernetes cluster, for local development

### Installation

To install NoETL use `pip`:

```bash
pip install noetl
