#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
NOETL_API_PATH="$DIR/../noetl/api.py"
HOST="localhost"
PORT="8021"
NATS_PORT=$(kubectl get svc nats -n nats -o=jsonpath='{.spec.ports[0].nodePort}')
NATS_URL="nats://localhost:${NATS_PORT}"
source .venv/bin/activate
# pycharm --host "localhost" --port "8021" --nats_url "nats://localhost:32645"
python ${NOETL_API_PATH} --host $HOST --port $PORT --nats_url ${NATS_URL} --reload
