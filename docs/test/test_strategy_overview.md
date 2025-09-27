# NoETL Test Strategy Overview

This document outlines the comprehensive testing strategy and philosophy for the NoETL workflow execution system.

## Testing Philosophy

NoETL implements a multi-layered testing approach designed to validate both structural integrity and runtime behavior of workflow execution. Our testing strategy follows the principle of **graduated verification**, where we progress from static validation to full integration testing.

### Core Testing Principles

1. **Separation of Concerns**: Static validation vs. runtime execution
2. **Progressive Complexity**: From unit tests to full integration scenarios
3. **Infrastructure Independence**: Tests that can run with or without external dependencies
4. **Real-world Validation**: Integration tests using actual external services
5. **Performance Awareness**: Tests that validate efficiency and resource usage

## Test Architecture Overview

```
NoETL Test Architecture
├── Static Tests
│   ├── Playbook Structure Validation
│   ├── Schema Compliance
│   ├── Planning Logic Verification
│   └── Template Rendering Tests
├── Runtime Tests (Optional)
│   ├── Server Integration Tests
│   ├── Database Interaction Tests
│   ├── Workflow Execution Tests
│   └── State Management Tests
└── Integration Tests (Full System)
    ├── External Service Integration
    ├── Multi-Service Coordination
    ├── End-to-End Workflow Validation
    └── Performance & Reliability Tests
```

## Test Categories

### 1. Static Tests (Default Execution)
- **Purpose**: Validate playbook structure, schema compliance, and planning logic
- **Dependencies**: None (no running services required)
- **Execution Speed**: Fast (< 1 second per test)
- **Coverage**: Syntax, structure, templates, planning algorithms

### 2. Runtime Tests (Optional)
- **Purpose**: Validate actual workflow execution through running services
- **Dependencies**: NoETL server, PostgreSQL database
- **Execution Speed**: Medium (5-15 seconds per test)
- **Coverage**: API integration, database operations, workflow state management

### 3. Integration Tests (Full System)
- **Purpose**: Validate complete end-to-end workflows with external services
- **Dependencies**: All NoETL services + external APIs (weather, GCS, etc.)
- **Execution Speed**: Slow (15-60 seconds per test)
- **Coverage**: Real-world scenarios, performance, reliability

## Test Control Mechanisms

### Environment Variables
- `NOETL_RUNTIME_TESTS=true`: Enables runtime and integration tests
- `NOETL_HOST`: Target server hostname (default: localhost)
- `NOETL_PORT`: Target server port (default: 8082)

### Make Target Patterns
- `make test-<name>`: Static tests only
- `make test-<name>-runtime`: Runtime tests (requires running server)
- `make test-<name>-full`: Full integration (reset DB, restart server, run all tests)
- `make test-<name>-k8s`: Kubernetes-friendly tests (restart server, skip DB reset)

## Test Data Strategy

### Fixture Organization
```
tests/fixtures/
├── playbooks/          # Test playbook scenarios
│   ├── control_flow_workbook/
│   ├── http_duckdb_postgres/
│   └── playbook_composition/
├── credentials/        # Test authentication data
└── data/              # Test datasets
```

### Test Isolation
- **Execution Caching**: Shared results between related tests to prevent duplicates
- **Database Separation**: Test-specific schemas and cleanup procedures
- **State Management**: Proper setup/teardown for each test scenario

## Quality Assurance Metrics

### Coverage Targets
- **Static Tests**: 100% of playbook parsing and planning logic
- **Runtime Tests**: 90% of API endpoints and database operations
- **Integration Tests**: 80% of real-world workflow scenarios

### Performance Benchmarks
- **Static Test Suite**: < 10 seconds total execution
- **Runtime Test Suite**: < 60 seconds total execution
- **Integration Test Suite**: < 300 seconds total execution

### Reliability Standards
- **Test Stability**: 99% pass rate on clean environments
- **Flake Tolerance**: < 1% false failure rate
- **Resource Cleanup**: 100% cleanup success rate

## Test Execution Workflows

### Developer Workflow (Static)
```bash
# Quick validation during development
make test-control-flow-workbook
make test-http-duckdb-postgres  
make test-playbook-composition
```

### Integration Workflow (Runtime)
```bash
# Full system validation
make test-control-flow-workbook-full
make test-http-duckdb-postgres-full
make test-playbook-composition-full
```

### CI/CD Pipeline Integration
```bash
# Staged execution for automated testing
make test                           # All static tests
make noetl-restart                 # Start services
make register-test-credentials     # Setup test data
make test-*-runtime               # All runtime tests
```

## Key Testing Scenarios

### 1. Control Flow Validation
- **Conditional Branching**: Temperature-based routing logic
- **Parallel Execution**: Multiple simultaneous step execution
- **Workbook Resolution**: Action lookup and execution

### 2. Data Pipeline Integration  
- **HTTP Integration**: External API consumption
- **Database Operations**: PostgreSQL storage and retrieval
- **Analytics Processing**: DuckDB cross-database queries
- **Cloud Storage**: GCS output with authentication

### 3. Workflow Composition
- **Iterator Patterns**: Sub-playbook execution loops
- **Data Flow**: Context passing between parent and child playbooks
- **Result Validation**: Comprehensive output verification

## Related Documentation

- [Test Types and Categories](./test_types_categories.md)
- [Playbook Test Documentation](./playbooks/README.md)
- [Test Execution Guide](./guides/execution_guide.md)
- [Test Infrastructure Setup](./infrastructure/setup_guide.md)
