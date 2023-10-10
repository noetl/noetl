#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

NOETL_CMD_PATH="$DIR/../noetl/commander.py"
PROM_HOST="localhost"
PROM_PORT="9100"
NATS_URL="nats://localhost:32645"


python ${NOETL_CMD_PATH} --nats_url ${NATS_URL} --prom_host ${PROM_HOST} --prom_port ${PROM_PORT}
