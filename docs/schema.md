# NoETL Database Schema
```
--Identity & Collaboration
+----------------+        +----------------+
|      role      |        |    profile     |
|----------------|        |----------------|
| id (PK)        |<-------| role_id (FK)   |
| name           |        | id (PK)        |
| description    |        | username       |
+----------------+        | email          |
                          | password_hash  |
                          | type           | ('user','bot')
                          | created_at     |
                          +----------------+
                                 |
                                 | 1:N
                                 |
                          +----------------+
                          |    session     |
                          |----------------|
                          | id (PK)        |
                          | profile_id(FK) |
                          | session_type   | ('user','bot','ai')
                          | connected_at   |
                          | disconnected_at|
                          | metadata       |
                          +----------------+

-- Hierarchical Labels
+----------------+       +----------------+       +----------------+
|     label      |       |                |       |                |
|----------------|-------|----------------|-------|----------------|
| id (PK)        |       | id (PK)        |       | id (PK)        |
| parent_id (FK) |       | label_id (FK)  |       | chat_id (FK)   |
| name           |       | name           |       | profile_id(FK) |
| owner_id (FK)  |       | owner_id(FK)   |       | role           | ('owner','admin','member')
| created_at     |       | created_at     |       | joined_at      |
+----------------+       +----------------+       +----------------+
        |                        |
        | 1:N                    | 1:N
        |                        |
        |                  +----------------+
        |                  |    message     |
        |                  |----------------|
        |                  | id (PK)        |
        |                  | chat_id (FK)   |
        |                  | sender_type    | ('user','bot','ai','system')
        |                  | sender_id      |
        |                  | role           |
        |                  | content        |
        |                  | metadata       |
        |                  | created_at     |
        |                  +----------------+
        |
        |
        |
        +------------------+
                           |
                           | 1:N
                           |
                     +----------------+
                     |   attachment   |
                     |----------------|
                     | id (PK)        |
                     | label_id (FK)  |
                     | chat_id (FK)   |
                     | filename       |
                     | filepath       |
                     | uploaded_by(FK)|
                     | created_at     |
                     +----------------+

-- Catalog & Resource System
+----------------+        +-------------------------------------+
|    resource    | 1:N    |    catalog                          |
|----------------|--------|-------------------------------------|
| name (PK)      |        | resource_path                       |
|                |        | resource_type(FK) -> resource(name) |
|                |        | resource_version (PK)               |
|                |        | source                              |
|                |        | resource_location                   |
|                |        | content                             |
|                |        | payload (JSONB)                     |
|                |        | meta (JSONB)                        |
|                |        | template                            |
|                |        | timestamp                           |
+----------------+        | credential_id                       |
                          +-------------------------------------+

-- Runtime & Schedule
+----------------+        +-----------------+
|    runtime     |        |    schedule     |
|----------------|        |-----------------|
| runtime_id (PK)|        | schedule_id(PK) |
| name           |        | playbook_path   |
| component_type |        | playbook_version|
| base_url       |        | cron            |
| status         |        | interval_sec    |
| labels (JSONB) |        | enabled         |
| capabilities   |        | timezone        |
| capacity       |        | next_run_at     |
| runtime (JSONB)|        | last_run_at     |
| last_heartbeat |        | last_status     |
| created_at     |        | input_payload   |
| updated_at     |        | created_at      |
+----------------+        | updated_at      |
                          | meta (JSONB)    |
                          +-----------------+

-- Workload / Workflow / Event Log
+----------------+       +----------------+       +----------------+
|   workload     |       |    workflow    |       |   event_log    |
|----------------|       |----------------|       |----------------|
| execution_id PK|       | execution_id PK|       | execution_id PK|
| timestamp      |       | step_id (PK)   |       | event_id PK    |
| data           |       | step_name      |       | parent_event_id|
+----------------+       | step_type      |       | timestamp      |
                         | description    |       | event_type     |
+----------------+       | raw_config     |       | node_id        |
|   workbook     |       +----------------+       | node_name      |
|----------------|                                | node_type      |
| execution_id PK|                                | status         |
| task_id (PK)   |                                | duration       |
| task_name      |                                | input_context  |
| task_type      |                                | output_result  |
| raw_config     |                                | metadata       |
+----------------+                                | ...            |
                                                  +----------------+

-- Transition & Error Log
+----------------+       +---------------------+
|   transition   |       |   error_log         |
|----------------|       |---------------------|
| execution_id PK|       | error_id (PK)       |
| from_step PK   |       | timestamp           |
| to_step PK     |       | error_type          |
| condition PK   |       | error_message       |
| with_params    |       | execution_id        |
+----------------+       | step_id             |
                         | step_name           |
                         | template_string     |
                         | context_data        |
                         | stack_trace         |
                         | severity            |
                         | resolved            |
                         | resolution_notes    |
                         | resolution_timestamp|
                         +---------------------+
```
## 1. Overview

The **NoETL database schema** supports:

- Workflow orchestration: execution tracking of tasks, workbooks, workflows.
- Resource management: cataloging data assets with versioning, payloads, and templates.
- Runtime monitoring: servers, workers, and brokers with capabilities and status.
- Identity & collaboration: managing users, bots, sessions, chats, hierarchical labels.
- Conversation system: hierarchical "folders" (labels), chats, messages, attachments, and members.
- Scheduling and automation: playbook schedules (cron or interval-based).
- Event logging and error tracking: detailed execution events and error information.

All **IDs are Snowflake-style globally unique integers**.

---

## 2. Identity & Collaboration

### Tables

| Table | Description |
|-------|-------------|
| `role` | Defines roles for profiles: `admin`, `user`, `bot`. |
| `profile` | Users and bots with references to roles. |
| `session` | Tracks active connections, session type, and metadata. |

### Relationships

- `profile.role_id → role.id` (1:N)
- `session.profile_id → profile.id` (1:N)

---

## 3. Hierarchy (Dentry)

Inspired by Linux VFS dentries, this models hierarchical name lookups as directory entries.

### Tables

| Table | Description |
|-------|-------------|
| `dentry` | Directory entries that map a name to a target under a parent. Supports recursion via `parent_id`. Can represent positive or negative entries. |

### Columns (dentry)

- `id BIGINT PRIMARY KEY`
- `parent_id BIGINT REFERENCES dentry(id) ON DELETE CASCADE`
- `name TEXT NOT NULL`
- `type TEXT NOT NULL` (e.g., `folder`)
- `resource_type TEXT NULL` (optional logical target type)
- `resource_id BIGINT NULL` (optional logical target id)
- `is_positive BOOLEAN DEFAULT TRUE` (false indicates a cached negative lookup)
- `metadata JSONB NULL`
- `created_at TIMESTAMPTZ DEFAULT now()`
- `UNIQUE(parent_id, name)`

### Indexes

- `dentry(parent_id)`
- `dentry(type)`

---

## 4. Resources & Catalog

| Table | Description |
|-------|-------------|
| `resource` | Master table of resource types. |
| `catalog` | Resource instances, versions, payloads, templates, optionally linked to credentials. |
| `credential` | Stores secrets and access credentials. |

### Relationships

- `catalog.resource_type → resource.name`
- `catalog.credential_id → credential.id` (optional)

---

## 5. Runtime & Scheduling

| Table | Description |
|-------|-------------|
| `runtime` | Tracks servers, worker pools, brokers with status, capacity, labels, and capabilities. |
| `schedule` | Playbook schedules with cron or interval execution, enabled/disabled flag. |

---

## 6. Workflow & Execution Logging

| Table | Description |
|-------|-------------|
| `workload` | Stores payloads and execution data per execution_id. |
| `workflow` | Workflow steps for an execution. |
| `workbook` | Tasks executed in an execution. |
| `event_log` | Event tracking per execution step/task. |
| `transition` | Workflow transitions with conditions and parameters. |
| `error_log` | Execution error tracking, stack traces, and resolution information. |

### Relationships

- `workflow.execution_id → workload.execution_id`
- `workbook.execution_id → workload.execution_id`
- `event_log.execution_id → workload.execution_id`
- `transition.execution_id → workflow.execution_id`
- `error_log.execution_id → workflow.execution_id`

---

## 6. Snowflake ID Generation

- Function `noetl.snowflake_id()` generates globally unique IDs:
  - Millisecond timestamp
  - Shard ID
  - Sequence number

- Used for tables: `role`, `profile`, `session`, `dentry`.
---

## 7. Indexes & Constraints

- Unique constraints:
  - `dentry(parent_id, name)`

- Indexes for performance:
  - `dentry(parent_id)`
  - `runtime(component_type, name)`
  - `schedule(next_run_at)` (enabled only)

---

## 8. ERD (Identity & Hierarchy)

ROLE  
└─< PROFILE  
      └─< SESSION  

ENTRY (DENTRY)  
├─< DENTRY (parent_id, recursive)  
└─ maps names to logical targets (resource_type/resource_id)

## Resources & Catalog

RESOURCE  
└─< CATALOG  
      └─ CREDENTIAL (optional)  

## Workflow & Execution

WORKLOAD  
├─< WORKFLOW  
│     └─< TRANSITION   
├─< WORKBOOK  
├─< EVENT_LOG  
└─< ERROR_LOG  

## Runtime & Scheduling

RUNTIME  
SCHEDULE  

---

## 11. Notes
- Hierarchical labels allow recursive navigation.
- Chats, messages, attachments, and members maintain conversation structure.
- Workflow, runtime, and schedule tables track system execution and automation.
- Supports **bots, users, and AI agents** with session tracking.
- Snowflake IDs ensure **distributed scalability**.
- Recursive label hierarchy enables **filesystem-like conversation navigation**.
- Attachments linked to labels or chats.
- Members table enforces **role-based permissions**.
---
