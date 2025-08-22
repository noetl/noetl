#!/bin/bash

# Export environment variables explicitly
export NOETL_SCHEMA=noetl
export NOETL_USER=noetl
export NOETL_PASSWORD=noetl
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5434
export POSTGRES_USER=demo
export POSTGRES_PASSWORD=demo
export POSTGRES_DB=demo_noetl
export POSTGRES_SCHEMA=public
export LOG_LEVEL=INFO

echo "Environment variables exported:"
echo "NOETL_SCHEMA: $NOETL_SCHEMA"
echo "NOETL_USER: $NOETL_USER"
echo "POSTGRES_HOST: $POSTGRES_HOST"
echo "POSTGRES_PORT: $POSTGRES_PORT"
