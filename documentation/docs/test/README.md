# NoETL Test Suite Documentation

Welcome to the comprehensive documentation for the NoETL test suite. This documentation provides structured guidance for understanding, running, and extending the test infrastructure that validates NoETL's workflow execution capabilities.

## Documentation Index

### Core Documentation
- **[Test Strategy Overview](./test_strategy_overview.md)** - Philosophy, architecture, and approach
- **[Test Types and Categories](./test_types_categories.md)** - Static, runtime, and integration test classifications
- **[Test Execution Guide](./guides/execution_guide.md)** - Complete guide to running tests
- **[Infrastructure Setup Guide](./infrastructure/setup_guide.md)** - Environment setup and configuration

### Test Playbooks
- **[Playbook Test Documentation](./playbooks/README.md)** - Overview of all test scenarios
- **[Control Flow Workbook](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/control_flow_workbook)** - Conditional branching and parallel execution
- **[HTTP DuckDB Postgres](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/examples)** - Data pipeline integration  
- **[Playbook Composition](https://github.com/noetl/noetl/tree/master/tests/fixtures/playbooks/playbook_composition)** - Sub-playbook orchestration

##  Quick Start

### For Developers (Static Tests)
```bash
# Validate playbook structure and logic
make test-control-flow-workbook
make test-http-duckdb-postgres
make test-playbook-composition
```

### For Integration Testing (Runtime)
```bash
# Start services and run comprehensive tests
make noetl-restart
make register-test-credentials
make test-control-flow-workbook-runtime
make test-http-duckdb-postgres-runtime
make test-playbook-composition-runtime
```

### For Full System Validation
```bash
# Complete end-to-end testing with infrastructure reset
make test-control-flow-workbook-full
make test-http-duckdb-postgres-full
make test-playbook-composition-full
```

##  Test Architecture Overview

The NoETL test suite implements a multi-layered approach:

```
Test Architecture
├── Static Tests (Structure & Logic)
│   ├── Playbook parsing validation
│   ├── Schema compliance checking
│   ├── Template rendering verification
│   └── Planning algorithm testing
├── Runtime Tests (Service Integration)
│   ├── API endpoint validation
│   ├── Database operation testing
│   ├── Workflow execution verification
│   └── State management validation
└── Integration Tests (Full System)
    ├── External service integration
    ├── Multi-service coordination
    ├── End-to-end workflow validation
    └── Performance & reliability testing
```

##  Test Coverage Matrix

| Test Scenario | Focus Area | Technologies | Complexity | Dependencies |
|---------------|------------|--------------|------------|--------------|
| **Control Flow Workbook** | Execution Logic | Conditional routing, Parallel execution | Low | None |
| **HTTP DuckDB Postgres** | Data Pipeline | HTTP APIs, Multi-DB, Cloud storage | High | External APIs, GCS |
| **Playbook Composition** | Orchestration | Sub-playbooks, Iterators, Data flow | Medium | PostgreSQL |

##  Test Categories

### Static Tests (Fast Feedback)
-  **No dependencies** - Run anywhere, anytime
-  **Fast execution** - Complete in seconds
-  **Structure validation** - YAML syntax, schema compliance
-  **Logic verification** - Template rendering, planning algorithms

### Runtime Tests (Service Integration)
-  **Requires services** - NoETL server + PostgreSQL
-  **API validation** - HTTP endpoints, database operations  
-  **State management** - Queue operations, event logging
-  **Workflow execution** - End-to-end process validation

### Integration Tests (Full System)
-  **External services** - Weather APIs, cloud storage
-  **Real-world scenarios** - Complete data pipelines
-  **Performance testing** - Resource usage, timing
-  **Production validation** - Reliability, error handling

##  Environment Setup

### Prerequisites
- Python 3.11+
- Docker & Docker Compose  
- PostgreSQL (via Docker or local)
- Internet access (for integration tests)

### Quick Environment Setup
```bash
# 1. Install dependencies
make install-uv && make create-venv && make install-dev

# 2. Start services
make up

# 3. Verify setup
make status && make test
```

### Test Execution Patterns
```bash
# Development workflow
make test-<scenario>              # Static validation
make test-<scenario>-runtime      # Runtime validation  
make test-<scenario>-full         # Full integration
make test-<scenario>-k8s          # Kubernetes-friendly
```

##  Test Playbook Details

### 1. Control Flow Workbook
**Purpose**: Validates execution control mechanisms
- **Conditional branching** with `when:` clauses
- **Parallel execution** of multiple workflow paths  
- **Workbook action** resolution and execution
- **Temperature-based routing** for dynamic logic

**Quick Test**: `make test-control-flow-workbook-runtime`

### 2. HTTP DuckDB Postgres  
**Purpose**: Demonstrates data pipeline integration
- **HTTP API integration** with weather services
- **Multi-database analytics** (PostgreSQL + DuckDB)
- **Cloud storage output** with GCS authentication
- **Async iterator processing** for parallel data collection

**Quick Test**: `make test-http-duckdb-postgres-runtime`

### 3. Playbook Composition
**Purpose**: Validates workflow orchestration
- **Parent-child playbook** relationships
- **Iterator-driven** sub-playbook execution
- **Data flow** between playbook layers
- **Business logic composition** with scoring algorithms

**Quick Test**: `make test-playbook-composition-runtime`

##  Debugging and Troubleshooting

### Common Issues
```bash
# Server not available
make noetl-restart && make server-status

# Database connection errors  
make postgres-status && make postgres-reset-schema

# Missing credentials
make register-test-credentials

# Test timeouts
export NOETL_TEST_TIMEOUT=600
```

### Log Analysis
```bash
# Server logs
tail -f logs/server.log

# Event logs  
tail -f logs/event.json | jq .

# Queue status
cat logs/queue.json | jq '.[] | select(.status == "leased")'
```

##  Performance Expectations

### Execution Times
- **Static Tests**: < 10 seconds total
- **Runtime Tests**: < 60 seconds total  
- **Integration Tests**: < 300 seconds total

### Resource Requirements
- **Memory**: 500MB - 1GB depending on test type
- **CPU**: 2-4 cores recommended for parallel execution
- **Storage**: < 5GB for complete test environment
- **Network**: Required for integration tests

##  Continuous Integration

### CI/CD Pipeline Integration
```bash
# Stage 1: Quick validation
make test

# Stage 2: Service preparation
make postgres-reset-schema && make noetl-restart
make register-test-credentials  

# Stage 3: Runtime validation
NOETL_RUNTIME_TESTS=true make test

# Stage 4: Integration testing  
make test-*-full
```

##  Related Documentation

### Core NoETL Documentation
- [Introduction](/docs/intro)
- [DSL Specification](/docs/reference/dsl/dsl_spec)
- [API Usage](/docs/reference/api_usage)
- [CLI Reference](/docs/reference/noetl_cli_usage)

### Advanced Topics
- [Features Overview](/docs/features/variables)
- [Playbook Structure](/docs/features/playbook_structure)
- [Retry Mechanism](/docs/features/retry_mechanism)
- [Variables Feature](/docs/features/variables)

##  Contributing

### Adding New Tests
1. Create test playbook in `tests/fixtures/playbooks/<name>/`
2. Add README with comprehensive documentation
3. Implement static and runtime test classes
4. Add Make targets following naming conventions
5. Update this documentation with cross-references

### Test Documentation Standards
- **Comprehensive README** for each test playbook
- **Cross-references** between related documents
- **Make target documentation** with examples
- **Troubleshooting sections** with common issues
- **Performance expectations** and benchmarks

##  Documentation Structure

```
docs/test/
├── README.md                           # This navigation index
├── test_strategy_overview.md           # Testing philosophy and approach
├── test_types_categories.md           # Test classification and characteristics
├── guides/
│   └── execution_guide.md             # Complete execution instructions
├── infrastructure/
│   └── setup_guide.md                 # Environment setup and configuration
└── playbooks/
    └── README.md                      # Test playbook documentation
```

##  Version Information

**Documentation Version**: 1.0.0  
**NoETL Version**: 1.0.0  
**Last Updated**: September 26, 2025  

---

##  Support and Questions

For questions about the test suite or to report issues:

1. **Check troubleshooting sections** in relevant documentation
2. **Review log files** for error details
3. **Verify environment setup** following the infrastructure guide
4. **Consult playbook README** files for specific test scenarios
