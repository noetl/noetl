-- create_schema.sql
-- Schema creation SQL file demonstrating file-based script execution
-- This file is loaded by the container job and executed via psql

-- Variable :schema_name is passed from the shell script
\set ECHO all
\set ON_ERROR_STOP on

-- Report execution
\echo '=== Executing create_schema.sql ==='
\echo 'Schema:' :schema_name

-- Schema should already exist from init_schema.sh
-- This SQL verifies and documents the schema structure

-- Verify schema exists (use direct schema name since it's hardcoded in the test)
SELECT 1 FROM information_schema.schemata WHERE schema_name = 'container_test';

-- Create or update schema comment
COMMENT ON SCHEMA container_test IS 'Test schema created by NoETL container job for demonstrating Kubernetes-based SQL execution';

\echo '✓ Schema verified and documented'
