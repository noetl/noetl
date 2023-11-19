# NoETL Plugin-Based Workflow Architecture

## Introduction of Erlang-Inspired Design

The NoETL framework adopts Erlang's fundamental concepts in process management as a plugin-centric approach, leveraging NATS for message passing. This design enables efficient, reliable, and scalable workflows, perfectly aligning with Joe Armstrong's vision of building enduring and fault-tolerant systems, adapted here for NoETL's specific requirements.

## Principles

The design of the NoETL framework is guided by several key principles:

### Everything is a Plugin

- In NoETL, operational units are treated as plugins. This mirrors Erlang's concept where every operation is encapsulated within a process.

### Strong Isolation of Plugins

- Each plugin in NoETL operates independently and is isolated from others, akin to Erlang's process isolation. This isolation ensures that plugins run in their own domain without interference.

### Lightweight Plugin Management

- The framework allows for dynamic and efficient creation and destruction of plugins, facilitating a scalable system architecture.

### Message Passing as Core Interaction

- Communication between plugins is exclusively conducted through message passing via NATS streams, reflecting Erlang's principle where message passing is the only method of interaction between processes.

### Unique Naming for Plugin Communication

- Plugins communicate through dedicated NATS subjects, formatted as `command.<plugin name>` for listening and `event.<destination plugin name>` for responding. This ensures accurate and directed messaging.

### No Shared Resources Between Plugins

- Plugins in NoETL operate without shared resources, promoting isolated execution and reducing resource contention.

### Decentralized Error Handling

- Error management is handled non-locally, allowing plugins to fail without affecting the overall stability of the system.

### Resilience and Reliability

- Inspired by Erlang's philosophy, NoETL is designed to be robust and reliable, with plugins performing designated tasks effectively or failing gracefully.
