#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

NOETL_CMD_PATH="$DIR/../noetl/registrar.py"
PROM_HOST="localhost"
PROM_PORT="9102"
NATS_URL="nats://localhost:32645"

# pycharm --nats_url "nats://localhost:32645" --prom_host "localhost" --prom_port "9100"
python ${NOETL_CMD_PATH} --nats_url ${NATS_URL} --prom_host ${PROM_HOST} --prom_port ${PROM_PORT}
