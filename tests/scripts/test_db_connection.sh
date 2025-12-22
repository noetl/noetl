#!/bin/bash
# Test Database Connection Script
# This script tests the database connection and runtime table access

echo "Testing NoETL Database Connection..."
echo ""

DB_HOST="${DB_HOST:-localhost}"
DB_PORT="${DB_PORT:-30543}"
DB_NAME="${DB_NAME:-demo_noetl}"
DB_USER="${DB_USER:-demo}"
DB_PASSWORD="${DB_PASSWORD:-demo}"

echo "Connection: $DB_USER@$DB_HOST:$DB_PORT/$DB_NAME"
echo ""

echo "Testing database connection..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SELECT version();" >/dev/null 2>&1
if [ $? -eq 0 ]; then
    echo "Database connection successful"
else
    echo "Database connection failed"
    exit 1
fi

echo "Testing runtime table access..."
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "
    SELECT name, status, component_type, last_heartbeat
    FROM noetl.runtime
    WHERE component_type = 'worker_pool'
    ORDER BY name;
" 2>/dev/null

if [ $? -eq 0 ]; then
    echo "Runtime table access successful"
else
    echo "Runtime table access failed"
fi

echo "Current search path:"
PGPASSWORD="$DB_PASSWORD" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -c "SHOW search_path;"

echo "Database test completed."
