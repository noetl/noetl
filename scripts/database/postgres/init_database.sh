#!/bin/bash
set -e

POSTGRES="psql -d ${POSTGRES_DB} --username ${POSTGRES_USER}"

echo "Creating database schemas in $POSTGRES_DB"

echo "Creating database schema ${POSTGRES_SCHEMA}"

$POSTGRES <<-ESQL
\connect ${POSTGRES_DB};
SET SESSION AUTHORIZATION ${POSTGRES_USER};
CREATE SCHEMA IF NOT EXISTS ${POSTGRES_SCHEMA};
CREATE EXTENSION IF NOT EXISTS plpython3u;
ESQL

echo "Database schema ${POSTGRES_SCHEMA} created"

# Create noetl user and schema
echo "Creating noetl user and schema"

$POSTGRES <<-ESQL
\connect ${POSTGRES_DB};
SET SESSION AUTHORIZATION ${POSTGRES_USER};

-- Create noetl user if it doesn't exist
DO \$\$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${NOETL_USER}') THEN
    CREATE USER ${NOETL_USER} WITH PASSWORD '${NOETL_PASSWORD}' CREATEDB LOGIN;
  END IF;
END
\$\$;

-- Create noetl schema if it doesn't exist
CREATE SCHEMA IF NOT EXISTS ${NOETL_SCHEMA};

-- Grant privileges to noetl user
GRANT ALL PRIVILEGES ON SCHEMA ${NOETL_SCHEMA} TO ${NOETL_USER};
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA ${NOETL_SCHEMA} TO ${NOETL_USER};
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA ${NOETL_SCHEMA} TO ${NOETL_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA ${NOETL_SCHEMA} GRANT ALL ON TABLES TO ${NOETL_USER};
ALTER DEFAULT PRIVILEGES IN SCHEMA ${NOETL_SCHEMA} GRANT ALL ON SEQUENCES TO ${NOETL_USER};
ESQL

echo "Noetl user and schema created"

$POSTGRES -v SCHEMA_NAME=${POSTGRES_SCHEMA} -f /schema_ddl.sql --echo-all

echo "Database schema ${POSTGRES_USER} objects created"
