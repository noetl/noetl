#!/bin/bash
set -euo pipefail

# create_tables.sh - Create test tables via container
# This script demonstrates loading SQL files from the container workspace

echo "==================================================="
echo "NoETL Container Job: Table Creation"
echo "==================================================="
echo "Execution ID: ${EXECUTION_ID:-unknown}"
echo "Timestamp: $(date -u +"%Y-%m-%d %H:%M:%S UTC")"
echo "Schema: ${SCHEMA_NAME}"
echo "==================================================="

# Verify required environment variables
required_vars=("PGHOST" "PGPORT" "PGDATABASE" "PGUSER" "PGPASSWORD" "SCHEMA_NAME")
for var in "${required_vars[@]}"; do
    if [ -z "${!var:-}" ]; then
        echo "ERROR: Required environment variable $var is not set"
        exit 1
    fi
done

# List available SQL files in workspace
echo "Available SQL files in /workspace:"
ls -lh /workspace/*.sql 2>/dev/null || echo "No SQL files found"
echo ""

# Execute schema creation SQL
echo "Executing create_schema.sql..."
if [ -f "/workspace/create_schema.sql" ]; then
    psql -v ON_ERROR_STOP=1 -f /workspace/create_schema.sql
    echo "✓ Schema SQL executed successfully"
else
    echo "WARNING: create_schema.sql not found, skipping"
fi

# Execute table creation SQL
echo ""
echo "Executing create_tables.sql..."
if [ -f "/workspace/create_tables.sql" ]; then
    psql -v ON_ERROR_STOP=1 -f /workspace/create_tables.sql
    echo "✓ Tables created successfully"
else
    echo "ERROR: create_tables.sql not found"
    exit 1
fi

# Log execution
echo ""
echo "Logging execution..."
psql -v ON_ERROR_STOP=1 <<-EOSQL
    INSERT INTO ${SCHEMA_NAME}.execution_log (execution_id, step_name, status, message)
    VALUES ('${EXECUTION_ID}', 'create_tables', 'success', 'Tables created via container job');
EOSQL

# Verify tables
echo ""
echo "Verifying created tables..."
psql -c "
    SELECT 
        schemaname,
        tablename,
        pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
    FROM pg_tables 
    WHERE schemaname = '${SCHEMA_NAME}'
    ORDER BY tablename;
"

echo ""
echo "==================================================="
echo "Table creation complete!"
echo "==================================================="
exit 0
