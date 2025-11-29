#!/bin/bash
set -euo pipefail

# init_schema.sh - Initialize PostgreSQL schema via container
# This script demonstrates credential passing from NoETL to container jobs
# Environment variables are injected by the container tool runtime

echo "==================================================="
echo "NoETL Container Job: Schema Initialization"
echo "==================================================="
echo "Execution ID: ${EXECUTION_ID:-unknown}"
echo "Timestamp: $(date -u +"%Y-%m-%d %H:%M:%S UTC")"
echo "Database: ${PGDATABASE}"
echo "Host: ${PGHOST}:${PGPORT}"
echo "User: ${PGUSER}"
echo "==================================================="

# Verify required environment variables
required_vars=("PGHOST" "PGPORT" "PGDATABASE" "PGUSER" "PGPASSWORD")
for var in "${required_vars[@]}"; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: Required environment variable $var is not set"
        exit 1
    fi
done

# Test database connectivity
echo "Testing PostgreSQL connection..."
if ! psql -c "SELECT version();" > /dev/null 2>&1; then
    echo "ERROR: Cannot connect to PostgreSQL"
    psql -c "SELECT version();" || true
    exit 1
fi
echo "✓ Connection successful"

# Create schema
echo ""
echo "Creating schema 'container_test'..."
psql -v ON_ERROR_STOP=1 <<-EOSQL
    -- Drop schema if exists (for clean testing)
    DROP SCHEMA IF EXISTS container_test CASCADE;
    
    -- Create fresh schema
    CREATE SCHEMA container_test;
    
    -- Grant permissions
    GRANT USAGE ON SCHEMA container_test TO ${PGUSER};
    GRANT CREATE ON SCHEMA container_test TO ${PGUSER};
    GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA container_test TO ${PGUSER};
    GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA container_test TO ${PGUSER};
    
    -- Set default privileges for future objects
    ALTER DEFAULT PRIVILEGES IN SCHEMA container_test 
        GRANT ALL PRIVILEGES ON TABLES TO ${PGUSER};
    ALTER DEFAULT PRIVILEGES IN SCHEMA container_test 
        GRANT ALL PRIVILEGES ON SEQUENCES TO ${PGUSER};
    
    -- Create execution tracking table
    CREATE TABLE IF NOT EXISTS container_test.execution_log (
        id SERIAL PRIMARY KEY,
        execution_id VARCHAR(100),
        step_name VARCHAR(100),
        executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status VARCHAR(50),
        message TEXT
    );
    
    -- Log this execution
    INSERT INTO container_test.execution_log (execution_id, step_name, status, message)
    VALUES ('${EXECUTION_ID}', 'init_schema', 'success', 'Schema initialized via container job');
EOSQL

echo "✓ Schema created successfully"

# Verify schema creation
echo ""
echo "Verifying schema..."
schema_count=$(psql -t -c "SELECT COUNT(*) FROM information_schema.schemata WHERE schema_name = 'container_test';")
if [ "$schema_count" -eq 1 ]; then
    echo "✓ Schema verification passed"
else
    echo "ERROR: Schema verification failed"
    exit 1
fi

# List created objects
echo ""
echo "Created objects:"
psql -c "SELECT schemaname, tablename FROM pg_tables WHERE schemaname = 'container_test' ORDER BY tablename;"

echo ""
echo "==================================================="
echo "Schema initialization complete!"
echo "==================================================="
exit 0
