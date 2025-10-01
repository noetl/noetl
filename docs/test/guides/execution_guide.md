# Test Execution Guide

This guide provides comprehensive instructions for running NoETL tests across all environments and scenarios.

## Quick Start

### Development Testing (Static Only)
```bash
# Quick validation during development
make test-control-flow-workbook        # Control flow validation
make test-http-duckdb-postgres        # Data pipeline structure  
make test-playbook-composition        # Orchestration logic

# Run all static tests
make test
```

### Integration Testing (Runtime)
```bash
# Start NoETL services
make noetl-restart

# Register test credentials  
make register-test-credentials

# Run runtime tests
make test-control-flow-workbook-runtime
make test-http-duckdb-postgres-runtime  
make test-playbook-composition-runtime
```

### Full System Testing
```bash
# Complete integration with infrastructure reset
make test-control-flow-workbook-full
make test-http-duckdb-postgres-full
make test-playbook-composition-full
```

## Test Target Reference

### Make Target Patterns
NoETL follows a consistent naming pattern for test targets:

```
make test-<scenario>           # Static tests only
make test-<scenario>-runtime   # Runtime tests (requires server)
make test-<scenario>-full      # Full integration (reset + test)
make test-<scenario>-k8s       # Kubernetes-friendly (no DB reset)
```

### Complete Target Matrix

| Target | Dependencies | Duration | Purpose |
|--------|-------------|----------|---------|
| `test-control-flow-workbook` | None | ~1s | Static validation of control flow logic |
| `test-control-flow-workbook-runtime` | Server + DB | ~10s | Runtime execution validation |
| `test-control-flow-workbook-full` | Services | ~30s | Complete reset and integration test |
| `test-http-duckdb-postgres` | None | ~1s | Static validation of data pipeline |
| `test-http-duckdb-postgres-runtime` | Server + DB + Creds | ~45s | Runtime with external services |
| `test-http-duckdb-postgres-full` | Full Stack | ~90s | Complete pipeline integration |
| `test-playbook-composition` | None | ~1s | Static validation of orchestration |
| `test-playbook-composition-runtime` | Server + DB + Creds | ~25s | Runtime sub-playbook execution |
| `test-playbook-composition-full` | Full Stack | ~60s | Complete orchestration test |
| `test-playbook-composition-k8s` | Services | ~30s | K8s-friendly (no DB reset) |

## Environment Configuration

### Required Environment Variables

#### Core Configuration
```bash
# Enable runtime and integration tests
export NOETL_RUNTIME_TESTS=true

# Server connection settings
export NOETL_HOST=localhost      # Default: localhost
export NOETL_PORT=8082          # Default: 8082

# Test behavior settings
export NOETL_TEST_TIMEOUT=300   # Test timeout in seconds
export NOETL_TEST_PARALLELISM=4 # Parallel test execution
```

#### Optional Configuration
```bash
# Custom server URLs
export NOETL_BASE_URL=http://localhost:8082

# Database settings (usually auto-configured)
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=noetl
export POSTGRES_USER=noetl
export POSTGRES_PASSWORD=noetl

# Cloud service settings (for integration tests)
export GCS_BUCKET=noetl-test-bucket
export AWS_REGION=us-west-2
```

### Environment Setup Scripts
```bash
# Development environment
./scripts/setup-dev-env.sh

# Test environment  
./scripts/setup-test-env.sh

# Production-like environment
./scripts/setup-prod-env.sh
```

## Infrastructure Requirements

### Minimal Setup (Static Tests)
-  Python 3.11+ with virtual environment
-  NoETL package installed (`pip install -e .`)
-  Test dependencies (`pip install -e .[dev]`)

### Runtime Test Setup  
-  All minimal setup requirements
-  PostgreSQL database running
-  NoETL server running (`make noetl-start`)
-  Test credentials registered

### Full Integration Setup
-  All runtime setup requirements  
-  Internet connectivity for external APIs
-  Cloud storage access (GCS credentials)
-  External service authentication

## Service Management

### Starting Services
```bash
# Start all services
make up

# Start individual services
make postgres-start      # Start PostgreSQL
make noetl-start        # Start NoETL server
make worker-start       # Start worker processes

# Restart with fresh state
make noetl-restart      # Stop + Start NoETL
make postgres-reset-schema  # Reset database schema
```

### Checking Service Status
```bash
# Check all service status
make status

# Check individual services  
make postgres-status    # PostgreSQL connection
make server-status      # NoETL server health
make worker-status      # Worker process status

# Health check endpoints
curl http://localhost:8082/health
curl http://localhost:8082/api/status
```

### Stopping Services
```bash
# Stop all services
make down

# Stop individual services
make noetl-stop        # Stop NoETL server
make worker-stop       # Stop worker processes
make postgres-stop     # Stop PostgreSQL
```

## Credential Management

### Test Credential Setup
```bash
# Register all test credentials at once
make register-test-credentials

# Register specific credentials
make register-credential FILE=tests/fixtures/credentials/pg_local.json
make register-credential FILE=tests/fixtures/credentials/gcs_hmac_local.json

# Verify credential registration
curl -s http://localhost:8082/api/credentials | jq '.items[].name'
```

### Required Credentials by Test

#### Control Flow Workbook
- **No credentials required** (internal logic only)

#### HTTP DuckDB Postgres
- **pg_local**: PostgreSQL database connection
- **gcs_hmac_local**: GCS HMAC authentication

#### Playbook Composition  
- **pg_local**: PostgreSQL database connection
- **gcs_hmac_local**: GCS HMAC authentication (optional)

### Credential File Locations
```
tests/fixtures/credentials/
├── pg_local.json              # PostgreSQL connection
├── gcs_hmac_local.json        # GCS HMAC credentials
├── aws_local.json             # AWS credentials (if needed)
└── example_credentials.json   # Template examples
```

## Test Execution Patterns

### Development Workflow
```bash
# 1. Quick validation during development
make test-control-flow-workbook

# 2. Test changes with runtime validation
make noetl-restart
make test-control-flow-workbook-runtime

# 3. Full validation before commit
make test-control-flow-workbook-full
```

### CI/CD Pipeline
```bash
# Stage 1: Static validation (fast)
make test

# Stage 2: Infrastructure setup  
make postgres-reset-schema
make noetl-restart
make register-test-credentials

# Stage 3: Runtime validation
NOETL_RUNTIME_TESTS=true make test

# Stage 4: Integration tests (optional)
make test-http-duckdb-postgres-full
make test-playbook-composition-full
```

### Production Validation
```bash
# Complete system validation
make test-control-flow-workbook-full
make test-http-duckdb-postgres-full  
make test-playbook-composition-full

# Performance validation
time make test-*-runtime

# Resource validation  
docker stats  # Monitor resource usage during tests
```

## Debugging Test Failures

### Common Issues and Solutions

#### Server Not Available
```bash
# Symptom: "NoETL server not available"
# Solution: Start the server
make noetl-restart
make server-status  # Verify server is running
```

#### Database Connection Errors
```bash
# Symptom: "could not connect to server"  
# Solution: Check PostgreSQL status
make postgres-status
make postgres-reset-schema  # Reset if corrupted
```

#### Credential Issues
```bash
# Symptom: "credential not found"
# Solution: Register required credentials
make register-test-credentials
curl http://localhost:8082/api/credentials  # Verify registration
```

#### Timeout Errors
```bash
# Symptom: "Test timed out"
# Solution: Increase timeout or check resource usage
export NOETL_TEST_TIMEOUT=600  # Increase to 10 minutes
docker stats  # Check resource usage
```

### Log Analysis
```bash
# Server logs
tail -f logs/server.log

# Worker logs  
tail -f logs/worker_*.log

# Event logs
tail -f logs/event.json

# Queue status
cat logs/queue.json | jq '.[] | select(.status == "leased")'
```

### Test-Specific Debugging
```bash
# Run individual test with verbose output
pytest -v -s tests/test_control_flow_workbook.py::test_specific_function

# Run with debugging
pytest --pdb tests/test_control_flow_workbook.py

# Run with coverage
pytest --cov=noetl tests/
```

## Performance Optimization

### Test Execution Performance
```bash
# Parallel test execution (where supported)
pytest -n 4 tests/  # Run with 4 parallel workers

# Test selection for faster feedback
pytest tests/ -k "not runtime"  # Skip runtime tests

# Cache test results
pytest --cache-clear  # Clear cache if stale
```

### Resource Optimization
```bash
# Monitor resource usage
htop  # System resources
docker stats  # Container resources  

# Optimize database performance
make postgres-reset-schema  # Clean state
make postgres-vacuum       # Database maintenance
```

### Service Optimization
```bash
# Optimize NoETL server
export NOETL_WORKER_COUNT=2  # Reduce workers for testing
export NOETL_LOG_LEVEL=WARNING  # Reduce log verbosity

# Optimize PostgreSQL
export POSTGRES_SHARED_BUFFERS=256MB
export POSTGRES_WORK_MEM=4MB
```

## Advanced Usage

### Custom Test Scenarios
```bash
# Run specific test with custom parameters
NOETL_HOST=remote-server make test-control-flow-workbook-runtime

# Run tests against different environments
NOETL_PORT=8083 make test-playbook-composition-runtime

# Run with custom timeout
NOETL_TEST_TIMEOUT=120 make test-http-duckdb-postgres-runtime
```

### Kubernetes Testing
```bash
# Kubernetes-friendly tests (no DB reset)
make test-control-flow-workbook-k8s
make test-playbook-composition-k8s

# Port forwarding for remote testing
kubectl port-forward svc/noetl-server 8082:8082 &
make test-control-flow-workbook-runtime
```

### Continuous Monitoring
```bash
# Watch test execution
watch -n 5 'make test-control-flow-workbook'

# Monitor test metrics
pytest --benchmark-autosave tests/

# Generate test reports
pytest --html=report.html tests/
```

## Troubleshooting Reference

### Exit Codes
- **0**: Success
- **1**: Test failures
- **2**: Test interrupted  
- **3**: Internal error
- **4**: Configuration error
- **5**: Missing dependencies

### Common Error Patterns
```bash
# Pattern: Import errors
# Fix: Check virtual environment activation

# Pattern: Connection refused
# Fix: Verify service status with make status

# Pattern: Permission denied
# Fix: Check file permissions and credentials

# Pattern: Timeout exceeded
# Fix: Increase timeout or optimize resources
```

## Related Documentation

- [Test Strategy Overview](../test_strategy_overview.md)
- [Test Types and Categories](../test_types_categories.md)
- [Playbook Test Documentation](../playbooks/README.md)
- [Infrastructure Setup Guide](../infrastructure/setup_guide.md)
