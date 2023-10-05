#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

NOETL_API_PATH="$DIR/../noetl/api.py"

HOST="localhost"
PORT="8021"

python ${NOETL_API_PATH} --host $HOST --port $PORT
