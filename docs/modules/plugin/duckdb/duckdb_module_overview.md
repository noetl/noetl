# DuckDB Plugin Module Overview

## Introduction

The DuckDB plugin (`noetl/noetl/noetl/plugin/duckdb`) provides DuckDB integration for NoETL, enabling SQL query execution against DuckDB databases with support for multiple data sources, cloud storage, and various authentication methods.

## Module Structure

The DuckDB plugin is organized into a modular architecture with the following components:

```
noetl/plugin/duckdb/
├── __init__.py              # Main plugin entry point and task execution
├── config.py                # Configuration and parameter processing
├── connections.py           # Connection management and pooling
├── extensions.py            # DuckDB extension management
├── types.py                 # Type definitions and data structures
├── errors.py                # Custom exception classes
├── auth/                    # Authentication and credential management
│   ├── __init__.py
│   ├── resolver.py          # Credential resolution logic
│   ├── secrets.py           # DuckDB secrets generation
│   └── legacy.py            # Legacy credential compatibility
├── cloud/                   # Cloud storage integration
│   ├── __init__.py
│   ├── credentials.py       # Cloud credential configuration
│   └── scopes.py            # URI scope detection and validation
└── sql/                     # SQL processing utilities
    ├── __init__.py
    ├── rendering.py         # SQL template rendering and processing
    └── execution.py         # SQL command execution and result handling
```

## Core Components

### Main Plugin (`__init__.py`)

The main entry point provides the primary task execution function:

- **`execute_duckdb_task()`**: Main task execution function that orchestrates the entire DuckDB task workflow
- Handles backwards compatibility for deprecated credential fields
- Integrates all module components for complete task processing
- Supports event logging and task tracking

**Key Features:**
- Modular task execution pipeline
- Authentication setup and secret management
- Extension installation and management
- SQL command rendering and execution
- Result serialization and task completion tracking

### Configuration Management (`config.py`)

Handles task and connection configuration:

- **`create_connection_config()`**: Creates connection configuration from task parameters
- **`create_task_config()`**: Processes task configuration and validates parameters
- **`preprocess_task_with()`**: Preprocesses task 'with' parameters and handles template rendering

**Configuration Types:**
- Connection configuration for database paths and execution context
- Task configuration for commands, authentication, and options
- Parameter preprocessing for template rendering and validation

### Connection Management (`connections.py`)

Provides connection pooling and management:

- **`get_duckdb_connection()`**: Context manager for shared DuckDB connections
- **`create_standalone_connection()`**: Creates isolated connections for specific use cases
- Global connection pool with thread-safe access
- Connection reuse to maintain database attachments and extensions

**Features:**
- Thread-safe connection pooling
- Connection lifecycle management
- Database attachment preservation
- Resource cleanup and error handling

### Extension Management (`extensions.py`)

Handles DuckDB extension installation and loading:

- **`get_required_extensions()`**: Determines required extensions based on authentication configuration
- **`install_and_load_extensions()`**: Installs and loads extensions in DuckDB
- **`install_database_extensions()`**: Installs database-specific extensions

**Supported Extensions:**
- PostgreSQL connector (`postgres`)
- MySQL connector (`mysql`)
- HTTP filesystem for cloud storage (`httpfs`)
- Automatic extension detection based on auth types

### Type Definitions (`types.py`)

Defines data structures and enums:

**Enums:**
- **`AuthType`**: Supported authentication types (postgres, mysql, sqlite, gcs, s3, etc.)
- **`DatabaseType`**: Supported database types for attachment

**Data Classes:**
- **`ConnectionConfig`**: Database path and execution context
- **`TaskConfig`**: Task parameters, commands, and authentication settings
- **`CloudScope`**: Cloud storage scope definitions

**Type Aliases:**
- `JinjaEnvironment`: Jinja2 template environment
- `ContextDict`: Execution context dictionary
- `CredentialData`: Credential information structure

### Error Handling (`errors.py`)

Custom exception hierarchy for specific error types:

- **`DuckDBPluginError`**: Base exception class
- **`ConnectionError`**: Database connection issues
- **`AuthenticationError`**: Credential and authentication problems
- **`ConfigurationError`**: Invalid task or plugin configuration
- **`SQLExecutionError`**: SQL command execution failures
- **`CloudStorageError`**: Cloud storage access issues
- **`ExtensionError`**: Extension installation/loading problems

## Authentication System (`auth/`)

### Credential Resolution (`auth/resolver.py`)

Handles both unified and legacy authentication systems:

- **`resolve_unified_auth()`**: Processes modern unified authentication configuration
- **`resolve_credentials()`**: Handles legacy credential configurations
- Supports multiple authentication methods and automatic credential resolution
- Integrates with NoETL's central authentication system

**Supported Auth Types:**
- Database connections (PostgreSQL, MySQL, SQLite)
- Cloud storage (Google Cloud Storage, Amazon S3)
- HMAC-based authentication for cloud services

### Secret Generation (`auth/secrets.py`)

Creates DuckDB secrets for authenticated access:

- **`generate_duckdb_secrets()`**: Generates DuckDB secret configurations
- Converts resolved credentials into DuckDB-compatible secret syntax
- Supports multiple authentication backends and cloud providers

### Legacy Compatibility (`auth/legacy.py`)

Maintains compatibility with deprecated credential formats:

- **`build_legacy_credential_prelude()`**: Converts legacy credentials to modern format
- Provides migration path for existing configurations
- Handles deprecated field mappings and transformations

## Cloud Storage Integration (`cloud/`)

### Scope Detection (`cloud/scopes.py`)

Analyzes SQL commands and configurations for cloud storage requirements:

- **`detect_uri_scopes()`**: Identifies cloud storage URIs in SQL commands
- **`infer_object_store_scope()`**: Determines required cloud storage scope
- **`validate_cloud_output_requirement()`**: Validates cloud output configurations

**Supported Schemes:**
- Google Cloud Storage (`gs://`)
- Amazon S3 (`s3://`)
- HTTP/HTTPS endpoints for cloud access

### Cloud Credentials (`cloud/credentials.py`)

Configures cloud storage authentication:

- **`configure_cloud_credentials()`**: Sets up cloud storage authentication
- Handles service account keys, HMAC credentials, and environment-based auth
- Integrates with DuckDB's httpfs extension for cloud access

## SQL Processing (`sql/`)

### Template Rendering (`sql/rendering.py`)

Processes SQL templates and commands:

- **`render_commands()`**: Renders SQL command templates using Jinja2
- **`clean_sql_text()`**: Cleans and normalizes SQL text
- **`render_deep()`**: Performs deep template rendering on nested structures
- **`escape_sql()`**: Provides SQL injection protection and escaping

**Features:**
- Jinja2 template rendering with context injection
- SQL text normalization and cleanup
- Nested template resolution
- Security through SQL escaping

### Command Execution (`sql/execution.py`)

Executes SQL commands and handles results:

- **`execute_sql_commands()`**: Executes multiple SQL commands sequentially
- **`serialize_results()`**: Converts query results to JSON-serializable format
- **`create_task_result()`**: Creates standardized task result structures

**Result Handling:**
- Query result serialization with custom JSON encoding
- Error handling and rollback support
- Command execution tracking and logging
- Performance metrics and timing information

## Usage Patterns

### Basic Task Execution

The plugin supports standard DuckDB task execution with:
- SQL command execution (single command or command list)
- Template rendering with context variables
- Automatic extension management
- Connection pooling and reuse

### Multi-Database Integration

Connect to multiple database types simultaneously:
- PostgreSQL attachment for relational data
- Cloud storage access for data lakes
- SQLite for local file processing
- MySQL for legacy system integration

### Authentication Flexibility

Supports multiple authentication methods:
- Unified auth system with credential resolution
- Legacy credential compatibility
- Environment variable integration
- Service account and key-based authentication

### Cloud Storage Operations

Enable cloud data processing:
- Direct cloud storage queries
- Data export to cloud destinations
- Mixed local and cloud data operations
- Automatic credential and extension setup

## Integration Points

The DuckDB plugin integrates with several NoETL core systems:

- **Authentication System**: Uses NoETL's central credential resolution
- **Template Engine**: Leverages NoETL's Jinja2 rendering capabilities
- **Event Logging**: Integrates with task execution tracking and event logging
- **Error Reporting**: Uses NoETL's logging and error reporting infrastructure
- **Configuration Management**: Follows NoETL's configuration patterns and validation
