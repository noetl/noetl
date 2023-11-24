#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

NOETL_CMD_PATH="$DIR/../noetl/registrar.py"
PROM_HOST="localhost"
PROM_PORT="9102"
NATS_PORT=$(kubectl get svc nats -n nats -o=jsonpath='{.spec.ports[0].nodePort}')
NATS_URL="nats://localhost:${NATS_PORT}"

# pycharm --nats_url "nats://localhost:32222" --prom_host "localhost" --prom_port "9100"
python ${NOETL_CMD_PATH} --nats_url ${NATS_URL} --prom_host ${PROM_HOST} --prom_port ${PROM_PORT}
