# Test Infrastructure Setup Guide

This guide covers the infrastructure components, setup procedures, and configuration requirements for the NoETL test environment.

## Infrastructure Overview

The NoETL test infrastructure consists of multiple interconnected components:

```
NoETL Test Infrastructure
├── Core Services
│   ├── NoETL Server (API Gateway)
│   ├── PostgreSQL Database (State Storage)
│   └── Worker Processes (Job Execution)
├── External Services (Integration Tests)
│   ├── Weather API (Open-Meteo)
│   ├── Google Cloud Storage (GCS)
│   └── Cloud Authentication Services
└── Development Tools
    ├── Docker Compose (Local Development)
    ├── Kubernetes (Production-like Testing)
    └── Make Automation (Build & Test)
```

## Component Architecture

### Core Services

#### NoETL Server
- **Purpose**: Main API gateway and workflow orchestration
- **Port**: 8082 (default)
- **Dependencies**: PostgreSQL database
- **Health Check**: `GET /health`
- **Configuration**: Environment variables and config files

#### PostgreSQL Database  
- **Purpose**: Persistent storage for workflow state, events, and results
- **Port**: 5432 (default)
- **Schema**: Auto-initialized with NoETL tables
- **Test Database**: `noetl` (can be reset for clean state)

#### Worker Processes
- **Purpose**: Asynchronous job execution and processing
- **Count**: Configurable (default: 2 CPU workers, 1 GPU worker)
- **Communication**: Database queue-based task distribution
- **Scaling**: Horizontal scaling supported

### External Services (Integration Testing)

#### Weather API (Open-Meteo)
- **Endpoint**: `https://api.open-meteo.com/v1/forecast`
- **Purpose**: Real HTTP API integration testing
- **Authentication**: None required (public API)
- **Rate Limits**: Reasonable for testing (no aggressive throttling)

#### Google Cloud Storage (GCS)
- **Purpose**: Cloud storage output validation
- **Authentication**: HMAC keys or Service Account
- **Bucket**: Test-specific bucket (`noetl-test-bucket`)
- **Format**: Parquet file uploads

## Setup Procedures

### 1. Local Development Setup

#### Prerequisites
```bash
# Required tools
- Python 3.11+
- Docker & Docker Compose
- Git
- Make
- curl & jq (for API testing)

# Optional tools (recommended)
- kind (Kubernetes in Docker)
- kubectl (Kubernetes CLI)
- pgcli (PostgreSQL CLI)
```

#### Quick Setup
```bash
# 1. Clone repository
git clone <repository-url>
cd noetl

# 2. Install dependencies
make install-uv          # Install uv package manager
make create-venv         # Create virtual environment  
make install-dev         # Install development dependencies

# 3. Start services
make up                  # Start all services via Docker Compose

# 4. Verify installation
make status              # Check all service status
make test               # Run static tests
```

#### Detailed Setup Steps
```bash
# Create and activate virtual environment
make create-venv
source .venv/bin/activate

# Install NoETL package in development mode
make install-dev

# Verify installation
.venv/bin/noetl --help

# Start PostgreSQL
make postgres-start

# Initialize database schema
make postgres-reset-schema

# Start NoETL server  
make noetl-start

# Start worker processes
make worker-start

# Verify all services are running
make server-status       # Should return health check
make postgres-status     # Should show connection success
```

### 2. Docker Compose Setup

#### Service Configuration
```yaml
# docker-compose.yaml (key services)
services:
  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: noetl
      POSTGRES_USER: noetl
      POSTGRES_PASSWORD: noetl
    ports:
      - "5432:5432"
    
  noetl-server:
    build: .
    depends_on:
      - postgres
    environment:
      DATABASE_URL: postgresql://noetl:noetl@postgres:5432/noetl
    ports:
      - "8082:8082"
```

#### Docker Commands
```bash
# Start all services
make up

# Start specific service
docker-compose up postgres
docker-compose up noetl-server

# View logs
docker-compose logs -f noetl-server
docker-compose logs -f postgres

# Reset environment
make down && make up
```

### 3. Kubernetes Setup (Advanced)

#### Kind Cluster Setup
```bash
# Create local Kubernetes cluster
make k8s-kind-create

# Verify cluster
kubectl cluster-info
kubectl get nodes

# Deploy NoETL services
make k8s-postgres-apply
make k8s-noetl-apply

# Port forward for testing
make postgres-port-forward    # PostgreSQL on localhost:5432
kubectl port-forward svc/noetl-server 8082:8082
```

#### Kubernetes Testing
```bash
# Kubernetes-friendly tests (no DB reset)
make test-control-flow-workbook-k8s
make test-playbook-composition-k8s

# Check pod status
kubectl get pods -n noetl

# View pod logs
kubectl logs -f deployment/noetl-server
```

## Configuration Management

### Environment Variables

#### Core Configuration
```bash
# Database connection
export DATABASE_URL=postgresql://noetl:noetl@localhost:5432/noetl
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5432
export POSTGRES_DB=noetl
export POSTGRES_USER=noetl
export POSTGRES_PASSWORD=noetl

# Server configuration  
export NOETL_HOST=0.0.0.0
export NOETL_PORT=8082
export NOETL_LOG_LEVEL=INFO
export NOETL_WORKER_COUNT=2

# Test configuration
export NOETL_RUNTIME_TESTS=true
export NOETL_TEST_TIMEOUT=300
```

#### Cloud Service Configuration
```bash
# Google Cloud Storage
export GCS_BUCKET=noetl-test-bucket
export GCS_PROJECT_ID=noetl-test-project
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json

# AWS (if using S3)
export AWS_ACCESS_KEY_ID=your-access-key
export AWS_SECRET_ACCESS_KEY=your-secret-key
export AWS_DEFAULT_REGION=us-west-2
export S3_BUCKET=noetl-test-bucket
```

### Configuration Files

#### NoETL Server Config
```yaml
# config/server.yaml
server:
  host: 0.0.0.0
  port: 8082
  workers: 2

database:
  url: ${DATABASE_URL}
  pool_size: 20
  max_overflow: 10

logging:
  level: INFO
  format: json
  
auth:
  enabled: false  # Disabled for testing
```

#### Test Configuration
```yaml
# config/test.yaml
test:
  timeout: 300
  parallel: true
  cleanup: true
  
database:
  reset_schema: true
  preserve_data: false

external_services:
  weather_api: true
  gcs_storage: true
  timeout: 60
```

## Credential Management

### Test Credentials Setup

#### PostgreSQL Credential
```json
// tests/fixtures/credentials/pg_local.json
{
  "name": "pg_local",
  "type": "postgres", 
  "connection_string": "postgresql://noetl:noetl@localhost:5432/noetl",
  "description": "Local PostgreSQL for testing"
}
```

#### GCS HMAC Credential
```json
// tests/fixtures/credentials/gcs_hmac_local.json
{
  "name": "gcs_hmac_local",
  "type": "gcs_hmac",
  "access_key": "GOOG1E...", 
  "secret_key": "your-secret-key",
  "bucket": "noetl-test-bucket",
  "description": "GCS HMAC for testing"
}
```

#### Credential Registration
```bash
# Register all test credentials
make register-test-credentials

# Register specific credential
make register-credential FILE=tests/fixtures/credentials/pg_local.json

# Verify registration
curl -s http://localhost:8082/api/credentials | jq '.items[].name'
```

### Cloud Service Setup

#### Google Cloud Storage
```bash
# 1. Create GCS bucket
gsutil mb gs://noetl-test-bucket

# 2. Generate HMAC keys
gsutil hmac create service-account@project.iam.gserviceaccount.com

# 3. Set bucket permissions
gsutil iam ch serviceAccount:service-account@project.iam.gserviceaccount.com:objectAdmin gs://noetl-test-bucket

# 4. Configure credential
# Use the HMAC keys in tests/fixtures/credentials/gcs_hmac_local.json
```

#### AWS S3 (Alternative)
```bash
# 1. Create S3 bucket
aws s3 mb s3://noetl-test-bucket

# 2. Create IAM user with S3 permissions
aws iam create-user --user-name noetl-test-user
aws iam attach-user-policy --user-name noetl-test-user --policy-arn arn:aws:iam::aws:policy/AmazonS3FullAccess

# 3. Generate access keys
aws iam create-access-key --user-name noetl-test-user
```

## Database Management

### Schema Management
```bash
# Reset database schema (clean slate)
make postgres-reset-schema

# Apply migrations
make postgres-migrate

# Backup test data
make postgres-backup

# Restore test data  
make postgres-restore
```

### Database Utilities
```bash
# Connect to database
make postgres-connect

# Run SQL query
make postgres-query SQL="SELECT * FROM executions LIMIT 5"

# Check database status
make postgres-status

# View database logs
docker-compose logs postgres
```

### Test Data Management
```sql
-- Clean test data
DELETE FROM executions WHERE name LIKE '%test%';
DELETE FROM queue_items WHERE created_at < NOW() - INTERVAL '1 hour';

-- Check test execution status
SELECT execution_id, name, status, created_at 
FROM executions 
WHERE name IN ('control_flow_workbook', 'http_duckdb_postgres', 'playbook_composition')
ORDER BY created_at DESC;

-- Monitor queue status
SELECT status, COUNT(*) 
FROM queue_items 
GROUP BY status;
```

## Monitoring and Debugging

### Health Checks
```bash
# Service health checks
curl http://localhost:8082/health          # Server health
curl http://localhost:8082/api/status      # API status
pg_isready -h localhost -p 5432           # PostgreSQL health

# Comprehensive status check
make status                               # All services
```

### Log Management
```bash
# Server logs
tail -f logs/server.log

# Worker logs
tail -f logs/worker_*.log

# Event logs (structured)
tail -f logs/event.json | jq .

# Error analysis
grep -i error logs/server.log
jq 'select(.level == "ERROR")' logs/event.json
```

### Performance Monitoring
```bash
# Resource usage
docker stats                              # Container resources
htop                                      # System resources
iotop                                     # I/O usage

# Database performance
make postgres-stats                       # Database statistics
EXPLAIN ANALYZE SELECT * FROM executions; # Query performance
```

### Debug Tools
```bash
# Interactive debugging
pytest --pdb tests/test_control_flow_workbook.py

# Verbose test output
pytest -v -s tests/

# Profile test performance
pytest --profile tests/

# Generate test coverage
pytest --cov=noetl --cov-report=html tests/
```

## Troubleshooting

### Common Issues

#### Port Conflicts
```bash
# Symptom: "Port 8082 already in use"
# Solution: Kill existing processes
lsof -ti:8082 | xargs kill -9
make noetl-restart
```

#### Database Connection Issues
```bash
# Symptom: "could not connect to server"
# Solution: Check PostgreSQL status
docker-compose ps postgres               # Check container status
make postgres-status                     # Test connection
make postgres-reset-schema               # Reset if corrupted
```

#### Missing Dependencies
```bash
# Symptom: "ModuleNotFoundError"
# Solution: Reinstall dependencies
make install-dev                         # Reinstall all dependencies
source .venv/bin/activate               # Ensure venv activated
```

#### Credential Issues
```bash
# Symptom: "credential 'pg_local' not found"
# Solution: Register credentials
make register-test-credentials           # Register all credentials
curl http://localhost:8082/api/credentials # Verify registration
```

### Recovery Procedures

#### Complete Environment Reset
```bash
# Nuclear option: reset everything
make down                               # Stop all services
docker system prune -af --volumes      # Clean Docker
make postgres-reset-schema              # Reset database
make up                                 # Restart services
make register-test-credentials          # Re-register credentials
make test                              # Verify functionality
```

#### Service-Specific Reset
```bash
# Reset NoETL server only
make noetl-restart

# Reset PostgreSQL only  
make postgres-restart
make postgres-reset-schema

# Reset workers only
make worker-restart
```

## Performance Tuning

### Database Optimization
```sql
-- PostgreSQL tuning for tests
-- Add to postgresql.conf or docker environment

shared_buffers = 256MB
work_mem = 4MB  
maintenance_work_mem = 64MB
checkpoint_completion_target = 0.9
wal_buffers = 16MB
default_statistics_target = 100
```

### Service Optimization
```bash
# Optimize for testing
export NOETL_WORKER_COUNT=1             # Reduce workers for testing
export NOETL_LOG_LEVEL=WARNING          # Reduce log verbosity
export NOETL_DB_POOL_SIZE=10            # Optimize connection pooling
```

### Test Performance
```bash
# Parallel test execution
pytest -n auto tests/                   # Auto-detect CPU cores
pytest -n 4 tests/                     # Specific parallel count

# Test result caching
pytest --cache-clear                    # Clear stale cache
pytest --lf                            # Run last failed tests only
```

## Related Documentation

- [Test Strategy Overview](../test_strategy_overview.md)
- [Test Execution Guide](../guides/execution_guide.md)
- [Test Types and Categories](../test_types_categories.md)
- [Playbook Test Documentation](../playbooks/README.md)
