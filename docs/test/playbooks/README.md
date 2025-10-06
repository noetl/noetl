# NoETL Test Playbooks

This directory contains detailed documentation for the three primary test playbooks that demonstrate different aspects of NoETL's workflow execution capabilities.

## Overview

Our test playbooks are designed to validate different core functionalities of the NoETL system:

1. **Control Flow Workbook** - Conditional branching and parallel execution
2. **HTTP DuckDB Postgres** - Data pipeline integration with external services  
3. **Playbook Composition** - Sub-playbook orchestration with iterators

Each playbook serves as both a test case and a reference implementation for specific workflow patterns.

## Test Playbook Matrix

| Playbook | Primary Focus | Key Technologies | Complexity | External Dependencies |
|----------|---------------|------------------|------------|----------------------|
| [Control Flow](#control-flow-workbook) | Execution Logic | Conditional routing, Parallel steps | Low | None |
| [HTTP DuckDB Postgres](#http-duckdb-postgres) | Data Integration | HTTP APIs, Multi-DB, Cloud Storage | High | Weather API, GCS |
| [Playbook Composition](#playbook-composition) | Workflow Orchestration | Sub-playbooks, Iterators, Data Flow | Medium | PostgreSQL |

## Control Flow Workbook

**Location**: `tests/fixtures/playbooks/control_flow_workbook/`  
**README**: [`./tests/fixtures/playbooks/control_flow_workbook/README.md`](../../../tests/fixtures/playbooks/control_flow_workbook/README.md)

### Purpose
Validates the core execution control mechanisms of NoETL:
- Conditional branching based on runtime data
- Parallel execution of multiple workflow paths
- Workbook action resolution and execution

### Key Features Tested
- **Conditional Routing**: `when:` clauses with Jinja template evaluation
- **Parallel Fanout**: Multiple `next` steps without conditions
- **Workbook Actions**: `type: workbook` step resolution by action name
- **Temperature-based Logic**: Dynamic routing based on `workload.temperature_c`

### Test Scenarios
```yaml
# Conditional branching example
- step: check_temperature
  type: workbook
  name: evaluate_temperature
  next:
    - step: hot_weather_path
      when: "{{ workload.temperature_c >= 25 }}"
    - step: cold_weather_path  
      when: "{{ workload.temperature_c < 25 }}"

# Parallel execution example  
- step: parallel_processing
  type: workbook
  name: process_data
  next:
    - step: process_logs        # No 'when' = always execute
    - step: process_metrics     # No 'when' = always execute
    - step: process_alerts      # No 'when' = always execute
```

### Make Targets
```bash
# Static validation
make test-control-flow-workbook

# Runtime execution (requires server)
make test-control-flow-workbook-runtime

# Full integration (reset + restart + test)
make test-control-flow-workbook-full
```

### Expected Results
- **Hot Path** (temp ≥ 25°C): Executes hot weather processing steps
- **Cold Path** (temp < 25°C): Executes cold weather processing steps
- **Parallel Steps**: All parallel steps execute simultaneously
- **Execution Complete**: Workflow reaches final state with success status

---

## HTTP DuckDB Postgres

**Location**: `tests/fixtures/playbooks/http_duckdb_postgres/`  
**README**: [`./tests/fixtures/playbooks/http_duckdb_postgres/README.md`](../../../tests/fixtures/playbooks/http_duckdb_postgres/README.md)

### Purpose
Demonstrates comprehensive data pipeline integration across multiple technologies:
- External API consumption with HTTP requests
- Multi-database analytics (PostgreSQL + DuckDB)
- Cloud storage output with authentication
- Async iterator processing for parallel data collection

### Architecture Overview
```
External Weather API
        ↓
   HTTP Iterator Step (Async)
        ↓
   PostgreSQL Storage (Upsert)
        ↓
   DuckDB Analytics Engine
        ↓
   Cross-Database Queries
        ↓
   GCS Cloud Storage (Parquet)
```

### Key Features Tested
- **HTTP Integration**: Open-Meteo weather API consumption
- **Async Processing**: Parallel city data collection via iterators
- **Database Operations**: PostgreSQL upsert with conflict resolution
- **Cross-Database Analytics**: DuckDB queries against PostgreSQL data
- **Cloud Storage**: GCS output with unified authentication
- **Data Transformations**: JSON → SQL → Parquet format conversions

### Pipeline Flow
1. **Setup Phase**: Create PostgreSQL table with proper schema
2. **Collection Phase**: Fetch weather data for multiple cities (London, Paris, Berlin)
3. **Storage Phase**: Save raw HTTP responses with upsert mode
4. **Analytics Phase**: Use DuckDB to flatten and aggregate data
5. **Export Phase**: Generate Parquet files and upload to GCS
6. **Metrics Phase**: Record pipeline performance metrics

### Required Credentials
```json
// pg_local credential
{
  "name": "pg_local",
  "type": "postgres",
  "connection_string": "postgresql://user:pass@localhost:5432/noetl"
}

// gcs_hmac_local credential  
{
  "name": "gcs_hmac_local",
  "type": "gcs_hmac", 
  "access_key": "GOOG...",
  "secret_key": "...",
  "bucket": "noetl-test-bucket"
}
```

### Make Targets
```bash
# Static validation
make test-http-duckdb-postgres

# Runtime execution (requires credentials)
make test-http-duckdb-postgres-runtime

# Full integration (reset + credentials + test)
make test-http-duckdb-postgres-full
```

### Expected Results
- **API Calls**: Successfully fetch weather data for 3 cities
- **Database Storage**: 3 records inserted/updated in PostgreSQL
- **DuckDB Processing**: Cross-database queries execute successfully
- **GCS Upload**: Parquet files uploaded to cloud storage
- **Performance Metrics**: Pipeline metrics recorded in database

---

## Playbook Composition

**Location**: `tests/fixtures/playbooks/playbook_composition/`  
**README**: [`./tests/fixtures/playbooks/playbook_composition/README.md`](../../../tests/fixtures/playbooks/playbook_composition/README.md)

### Purpose
Validates advanced workflow orchestration capabilities:
- Parent-child playbook relationships
- Iterator-driven sub-playbook execution
- Data flow between playbook layers
- Complex business logic composition

### Architecture Overview
```
Main Playbook (playbook_composition.yaml)
├── Setup PostgreSQL Storage
├── Iterator Step: Process Users
│   ├── For each user in workload.users:
│   │   ├── Call: user_profile_scorer.yaml
│   │   ├── Pass: user data + execution context
│   │   ├── Receive: profile score + category
│   │   └── Save: result to PostgreSQL
│   └── Collect: all results
├── Validation Step: Validate Results
└── End Step: Display completion

Sub-Playbook (user_profile_scorer.yaml)
├── Extract: input user data validation
├── Calculate: weighted scoring components
│   ├── Experience Score (40% weight)
│   ├── Performance Score (35% weight) 
│   ├── Department Score (15% weight)
│   └── Age Factor (10% weight)
├── Compute: total weighted score
├── Determine: category assignment
└── Return: structured result
```

### Key Features Tested
- **Iterator with Playbook Task**: `type: iterator` calling sub-playbooks
- **Context Passing**: Data flow from parent to child playbooks
- **Result Collection**: Aggregating sub-playbook outputs
- **Business Logic**: Complex scoring algorithms with weighted factors
- **Data Validation**: Result verification and constraint checking

### Iterator Configuration
```yaml
- step: process_users
  type: iterator
  collection: "{{ workload.users }}"
  element: user
  task:
    type: playbook
    path: tests/fixtures/playbooks/playbook_composition/user_profile_scorer
    pass:
      user_data: "{{ user }}"
      execution_context: "{{ execution_id }}"
```

### Sub-Playbook Workflow
```yaml
# Input validation
- step: extract_user_data
  type: workbook
  name: validate_input

# Scoring calculations  
- step: calculate_scores
  type: workbook
  name: compute_weighted_scores

# Category determination
- step: assign_category
  type: workbook  
  name: determine_user_category

# Result formatting
- step: format_result
  type: workbook
  name: prepare_output
```

### Make Targets
```bash
# Static validation
make test-playbook-composition

# Runtime execution (requires credentials)
make test-playbook-composition-runtime

# Full integration (reset + credentials + test)
make test-playbook-composition-full

# Kubernetes-friendly (restart + credentials + test)
make test-playbook-composition-k8s
```

### Expected Results
- **User Processing**: 5 users processed through sub-playbooks
- **Score Calculation**: Valid scores (0-100) for all users
- **Category Assignment**: Appropriate categories (Junior/Mid/Senior/Executive)
- **Database Storage**: All results saved to PostgreSQL
- **Validation Success**: All business rules verified

---

## Cross-References and Relationships

### Complexity Progression
1. **Control Flow** → Basic execution logic and routing
2. **Playbook Composition** → Orchestration and data flow  
3. **HTTP DuckDB Postgres** → Full integration with external services

### Feature Coverage Matrix

| Feature | Control Flow | Composition | HTTP DuckDB |
|---------|-------------|-------------|-------------|
| Conditional Logic | ✅ Primary | ✅ Validation | ✅ Error Handling |
| Parallel Execution | ✅ Primary | ❌ Sequential | ✅ Async Iterator |
| Sub-Playbooks | ❌ N/A | ✅ Primary | ❌ N/A |
| External APIs | ❌ N/A | ❌ N/A | ✅ Primary |
| Database Operations | ❌ N/A | ✅ Results | ✅ Primary |
| Cloud Integration | ❌ N/A | ✅ Optional | ✅ Primary |
| Iterator Patterns | ❌ N/A | ✅ Primary | ✅ Async Mode |

### Learning Path Recommendation
1. Start with **Control Flow Workbook** to understand basic execution
2. Progress to **Playbook Composition** for orchestration patterns
3. Complete with **HTTP DuckDB Postgres** for real-world integration

## Common Testing Patterns

### Test Structure Pattern
```python
class TestPlaybook:
    """Static validation tests (always run)"""
    
    def test_structure(self):
        # Validate YAML structure
        pass
        
    def test_planning(self):  
        # Validate execution planning
        pass

class TestPlaybookRuntime:
    """Runtime execution tests (optional)"""
    
    @pytest.mark.skipif(not RUNTIME_ENABLED, reason="Runtime disabled")
    def test_execution(self):
        # Test actual execution
        pass
        
    def test_results_validation(self):
        # Validate execution results
        pass
```

### Shared Utilities
- `execute_playbook_runtime()`: Common execution helper
- `check_server_health()`: Server availability validation
- `wait_for_execution_completion()`: Async execution waiting
- `_execution_result_cache`: Result sharing between tests

## Related Documentation

- [Test Strategy Overview](../test_strategy_overview.md)
- [Test Types and Categories](../test_types_categories.md)
- [Test Execution Guide](../guides/execution_guide.md)
- [Infrastructure Setup Guide](../infrastructure/setup_guide.md)
