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

$POSTGRES -v SCHEMA_NAME=${POSTGRES_SCHEMA} -f /schema_ddl.sql --echo-all

echo "Database schema ${POSTGRES_USER} objects created"
