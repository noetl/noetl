# Test Types and Categories

This document provides detailed information about the different types of tests in the NoETL system, their characteristics, and when to use each type.

## Test Type Matrix

| Test Type | Dependencies | Speed | Coverage | Use Case |
|-----------|-------------|--------|----------|-----------|
| **Static** | None | Fast (< 1s) | Structure & Logic | Development |
| **Runtime** | NoETL Server + DB | Medium (5-15s) | API & Execution | Integration |
| **Integration** | Full Stack + External | Slow (15-60s) | End-to-End | Production Validation |

## 1. Static Tests

### Characteristics
- **No External Dependencies**: Run without any services
- **Fast Execution**: Complete in milliseconds to seconds
- **Structural Focus**: Validate playbook syntax, schema compliance, and logic
- **Developer Friendly**: Suitable for rapid development cycles

### What Static Tests Validate
-  YAML syntax and structure
-  Schema compliance with playbook specification
-  Template rendering and Jinja expressions
-  Planning algorithm correctness
-  Step dependency resolution
-  Workbook action definitions
-  Configuration parameter validation

### Example Static Test Flow
```python
def test_playbook_structure():
    """Test basic playbook structure and validation."""
    with open(PB_PATH, "r", encoding="utf-8") as f:
        pb = ordered_yaml_load(f)
    
    # Validate required fields
    assert "name" in pb
    assert "steps" in pb
    assert len(pb["steps"]) > 0
    
    # Validate step structure
    for step in pb["steps"]:
        assert "step" in step
        assert "type" in step
```

### When to Use Static Tests
-  During playbook development
-  Pre-commit validation
-  Quick feedback loops
-  CI/CD pipeline early stages
-  Syntax and structure verification

## 2. Runtime Tests

### Characteristics
- **Service Dependencies**: Requires NoETL server and PostgreSQL
- **API Integration**: Tests actual HTTP endpoints and database operations
- **State Validation**: Verifies workflow execution state management
- **Credential Management**: Tests authentication and authorization

### What Runtime Tests Validate
-  Playbook registration via API
-  Workflow execution through server
-  Database state changes
-  Queue management
-  Event logging
-  Step transition logic
-  Parallel execution handling
-  Error handling and recovery

### Example Runtime Test Flow
```python
@pytest.mark.skipif(not RUNTIME_ENABLED, reason="Runtime tests disabled")
def test_workflow_execution():
    """Test actual workflow execution through API."""
    if not check_server_health():
        pytest.skip("NoETL server not available")
    
    # Execute playbook through API
    result = execute_playbook_runtime(playbook_path, playbook_name)
    
    # Validate execution completed successfully
    assert result["status"] == "success"
    assert result["execution_id"] is not None
    
    # Verify database state
    execution_id = result["execution_id"]
    final_status = wait_for_execution_completion(execution_id)
    assert final_status["status"] == "completed"
```

### Runtime Test Requirements
-  **NoETL Server**: Running on localhost:8082
-  **PostgreSQL**: Database connection available
-  **Environment**: `NOETL_RUNTIME_TESTS=true`
-  **Credentials**: Test authentication configured

### When to Use Runtime Tests
-  API endpoint validation
-  Database integration testing
-  Workflow execution verification
-  Service integration validation
-  Performance testing

## 3. Integration Tests (Full System)

### Characteristics
- **Complete Stack**: All NoETL services + external dependencies
- **Real-world Scenarios**: Actual external API calls and service integration
- **End-to-End Validation**: Complete workflow from start to finish
- **Performance Testing**: Resource usage and timing validation

### What Integration Tests Validate
-  External API integration (weather services, cloud storage)
-  Authentication with external services
-  Data format transformations (JSON → SQL → Parquet)
-  Cross-database operations (PostgreSQL ↔ DuckDB)
-  Cloud storage operations (GCS uploads)
-  Error handling with external service failures
-  Performance under realistic loads
-  Resource cleanup and management

### Example Integration Test Flow
```python
def test_complete_pipeline():
    """Test complete data pipeline with external services."""
    # Setup credentials and services
    setup_credentials()
    
    # Execute complex workflow
    result = execute_playbook_runtime(pipeline_playbook, "http_duckdb_postgres")
    
    # Validate external API calls succeeded
    verify_external_api_calls()
    
    # Validate data transformations
    verify_database_results()
    
    # Validate cloud storage outputs
    verify_gcs_outputs()
    
    # Validate performance metrics
    assert result["execution_time"] < 60  # seconds
```

### Integration Test Requirements
-  **All NoETL Services**: Server, workers, database
-  **External APIs**: Weather services, cloud providers
-  **Credentials**: Production-like authentication
-  **Network Access**: Internet connectivity
-  **Storage Access**: Cloud storage permissions

### When to Use Integration Tests
-  Production readiness validation
-  Release testing
-  Performance benchmarking
-  External service compatibility
-  End-to-end workflow validation

## Test Control and Configuration

### Environment Variables
```bash
# Enable runtime and integration tests
export NOETL_RUNTIME_TESTS=true

# Configure target server
export NOETL_HOST=localhost
export NOETL_PORT=8082

# Test-specific settings
export NOETL_TEST_TIMEOUT=300
export NOETL_TEST_PARALLELISM=4
```

### Test Markers (pytest)
```python
# Static test (default)
def test_structure():
    pass

# Runtime test (requires services)
@pytest.mark.skipif(not RUNTIME_ENABLED, reason="Runtime tests disabled")
def test_execution():
    pass

# Integration test (requires external services)
@pytest.mark.integration
@pytest.mark.skipif(not INTEGRATION_ENABLED, reason="Integration tests disabled")
def test_full_pipeline():
    pass
```

## Test Execution Patterns

### Make Target Patterns
```bash
# Pattern: make test-<scenario>-<type>
make test-control-flow-workbook           # Static only
make test-control-flow-workbook-runtime   # Runtime only  
make test-control-flow-workbook-full      # Full integration
make test-control-flow-workbook-k8s       # Kubernetes-friendly
```

### Test Selection Strategy
```bash
# Development: Static tests for quick feedback
make test-control-flow-workbook

# Integration: Runtime tests for API validation
make test-control-flow-workbook-runtime

# Release: Full integration tests for production readiness
make test-control-flow-workbook-full
```

## Performance Characteristics

### Expected Execution Times

| Test Type | Single Test | Full Suite | Parallelizable |
|-----------|-------------|------------|----------------|
| **Static** | < 1s | < 10s | Yes |
| **Runtime** | 5-15s | < 60s | Limited |
| **Integration** | 15-60s | < 300s | No |

### Resource Requirements

| Test Type | Memory | CPU | Network | Storage |
|-----------|--------|-----|---------|---------|
| **Static** | < 100MB | Low | None | Minimal |
| **Runtime** | < 500MB | Medium | Local | < 1GB |
| **Integration** | < 1GB | High | External | < 5GB |

## Test Quality Metrics

### Coverage Expectations
- **Static Tests**: 100% of parsing and planning logic
- **Runtime Tests**: 90% of API endpoints and workflows
- **Integration Tests**: 80% of real-world scenarios

### Reliability Targets
- **Static Tests**: 100% reliability (deterministic)
- **Runtime Tests**: 99% reliability (service-dependent)
- **Integration Tests**: 95% reliability (external-dependent)

## Related Documentation

- [Test Strategy Overview](./test_strategy_overview.md)
- [Test Execution Guide](./guides/execution_guide.md)
- [Playbook Test Scenarios](./playbooks/README.md)
- [Infrastructure Setup](./infrastructure/setup_guide.md)
