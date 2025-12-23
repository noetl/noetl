#!/bin/bash
set -e

POSTGRES="psql --username ${POSTGRES_USER}"

echo "Creating databases and schemas"

# Create noetl user first
echo "Creating noetl user"

$POSTGRES -d ${POSTGRES_DB} <<-ESQL
-- Create noetl user if it doesn't exist (no CREATEDB privilege)
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${NOETL_USER}') THEN
    CREATE USER ${NOETL_USER} WITH PASSWORD '${NOETL_PASSWORD}' LOGIN;
  END IF;
END
\$\$;
ESQL

echo "Noetl user created"

# Create dedicated noetl database
echo "Creating noetl database: ${NOETL_POSTGRES_DB}"

$POSTGRES -d ${POSTGRES_DB} <<-ESQL
-- Create noetl database if it doesn't exist
SELECT 'CREATE DATABASE ${NOETL_POSTGRES_DB} OWNER ${NOETL_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${NOETL_POSTGRES_DB}')\gexec
ESQL

echo "Noetl database ${NOETL_POSTGRES_DB} created"

# Set up noetl database with noetl schema
echo "Setting up noetl schema in ${NOETL_POSTGRES_DB}"

$POSTGRES -d ${NOETL_POSTGRES_DB} <<-ESQL
\connect ${NOETL_POSTGRES_DB};
SET SESSION AUTHORIZATION ${POSTGRES_USER};

-- Create noetl schema
CREATE SCHEMA IF NOT EXISTS ${NOETL_SCHEMA};

-- Grant privileges to noetl user on database
GRANT ALL PRIVILEGES ON DATABASE ${NOETL_DB} TO ${NOETL_USER};

-- Grant privileges to noetl user on schema
GRANT ALL PRIVILEGES ON SCHEMA ${NOETL_SCHEMA} TO ${NOETL_USER};
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA ${NOETL_SCHEMA} TO ${NOETL_USER};
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA ${NOETL_SCHEMA} TO ${NOETL_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA ${NOETL_SCHEMA} GRANT ALL ON TABLES TO ${NOETL_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA ${NOETL_SCHEMA} GRANT ALL ON SEQUENCES TO ${NOETL_USER};
ESQL

echo "Noetl schema in ${NOETL_POSTGRES_DB} configured"

# Apply noetl schema DDL to noetl database
echo "Applying noetl schema DDL to ${NOETL_POSTGRES_DB}"
$POSTGRES -d ${NOETL_POSTGRES_DB} -v SCHEMA_NAME=${NOETL_SCHEMA} -f /schema_ddl.sql --echo-all
echo "Noetl schema objects created in ${NOETL_POSTGRES_DB}"

# Set up demo_noetl database with public schema
echo "Setting up demo database: ${POSTGRES_DB}"

$POSTGRES -d ${POSTGRES_DB} <<-ESQL
\connect ${POSTGRES_DB};
SET SESSION AUTHORIZATION ${POSTGRES_USER};

-- Create public schema (usually exists by default)
CREATE SCHEMA IF NOT EXISTS ${POSTGRES_SCHEMA};

-- Enable plpython3u extension for playbooks
CREATE EXTENSION IF NOT EXISTS plpython3u;
ESQL

echo "Demo database ${POSTGRES_DB} configured for playbooks"
echo "Note: noetl user has access only to ${NOETL_POSTGRES_DB} database"
