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

-- Hierarchical Labels / Chats
+----------------+       +----------------+       +----------------+
|     label      | 1:N   |      chat      | 1:N   |     member     |
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

## 3. Conversation System

### Tables

| Table | Description |
|-------|-------------|
| `label` | Hierarchical container (folder/namespace) for chats. Supports `parent_id`. |
| `chat` | Chat under a label. Each chat has an owner. |
| `member` | Maps profiles to chats with a role (`owner`, `admin`, `member`). |
| `message` | Stores messages in chats (`sender_type`: user, bot, AI, system). |
| `attachment` | Files attached to labels or chats. Tracks uploader. |

### Relationships

- `label.parent_id → label.id` (recursive)
- `chat.label_id → label.id`
- `chat.owner_id → profile.id`
- `member.chat_id → chat.id`
- `member.profile_id → profile.id`
- `message.chat_id → chat.id`
- `message.sender_id → profile.id` (optional)
- `attachment.label_id → label.id` (optional)
- `attachment.chat_id → chat.id` (optional)
- `attachment.uploaded_by → profile.id`

### Constraints

- Unique (`chat_id`, `profile_id`) in `member`.
- Member roles limited to: `owner`, `admin`, `member`.
- Message sender types: `user`, `bot`, `ai`, `system`.

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

## 7. Snowflake ID Generation

- Function `noetl.snowflake_id()` generates globally unique IDs:
  - Millisecond timestamp
  - Shard ID
  - Sequence number

- Used for tables: `role`, `profile`, `session`, `label`, `chat`, `member`, `message`, `attachment`.

---

## 8. Hierarchy & Navigation

- Labels form a **tree structure** via `parent_id`.
- Chats reside under labels.
- Messages reside under chats.
- Attachments can attach to either labels or chats.
- Members define **who can participate** in chats and their role.

---

## 9. Indexes & Constraints

- Unique constraints:
  - `label(parent_id, name)`
  - `member(chat_id, profile_id)`

- Indexes for performance:
  - `message(chat_id, created_at)`
  - `attachment(chat_id, created_at)`
  - `label(parent_id)`
  - `chat(label_id)`
  - `error_log(execution_id)`
  - `runtime(component_type, name)`
  - `schedule(next_run_at)` (enabled only)

---

## 10. ERD 

## Identity & Collaboration

ROLE  
└─< PROFILE  
      └─< SESSION  
      └─< CHAT  
            └─< MEMBER  
      └─< ATTACHMENT (uploads)  

## Conversation & Hierarchy

LABEL  
├─< LABEL (parent_id, recursive)  
└─< CHAT  
      ├─< MEMBER  
      ├─< MESSAGE  
      └─< ATTACHMENT  

MEMBER  
├─ references PROFILE  
└─ references CHAT  

MESSAGE  
├─ belongs_to CHAT  
└─ sender PROFILE (optional)  

ATTACHMENT  
├─ belongs_to CHAT (optional)  
├─ belongs_to LABEL (optional)  
└─ uploaded_by PROFILE  

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