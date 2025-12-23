# PostgreSQL Database Architecture

NoETL uses PostgreSQL as its primary data store for platform metadata, execution tracking, and runtime state management. The system employs a dual-database architecture to separate platform operations from playbook workspaces.

## Database Architecture

### Two-Database Design

NoETL uses two separate PostgreSQL databases with distinct purposes:

#### 1. NoETL Platform Database (`noetl`)

**Purpose**: Stores all NoETL platform metadata and operational data.

- **Database Name**: `noetl` (configurable via `NOETL_POSTGRES_DB`)
- **Schema**: `noetl` (configurable via `NOETL_SCHEMA`)
- **Owner**: `noetl` user (configurable via `NOETL_USER`)
- **Access**: Isolated - only accessible by the `noetl` user
- **Location**: `noetl/database/ddl/postgres/schema_ddl.sql`

**Contains**:
- Playbook catalog and versions
- Execution event logs and traces
- Runtime registrations (servers, workers, brokers)
- Credentials and keychain (encrypted)
- Schedules and cron jobs
- Transient execution variables

#### 2. Demo/Playbook Database (`demo_noetl`)

**Purpose**: Workspace for playbook operations and testing.

- **Database Name**: `demo_noetl` (configurable via `POSTGRES_DB`)
- **Schema**: `public` (configurable via `POSTGRES_SCHEMA`)
- **Owner**: `demo` user (configurable via `POSTGRES_USER`)
- **Access**: Used by playbooks for data operations
- **Extensions**: `plpython3u` for Python-based transformations

**Contains**:
- Playbook-created tables and data
- Demo and test datasets
- User-defined schemas and objects

### Security Model

The NoETL platform database is completely isolated:

- **NoETL User Privileges**:
  - `LOGIN` privilege only (no `CREATEDB`)
  - Full access to `noetl` database and schema only
  - No access to `demo_noetl` or any other database
  - All platform tables, sequences, and functions are owned by `noetl` user

- **Demo User Privileges**:
  - `LOGIN` and `CREATEDB` privileges
  - Full access to `demo_noetl` database
  - Can create additional databases for playbook testing
  - No access to `noetl` platform database

This separation ensures:
1. Platform metadata cannot be accidentally modified by playbooks
2. Playbook failures do not affect platform operations
3. Clear security boundaries between system and user data

## Database Schema

### Platform Tables (noetl schema)

#### catalog
Stores playbook definitions and versions.
