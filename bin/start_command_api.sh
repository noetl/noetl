#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

COMMAND_PATH="$DIR/../noetl/command.py"

HOST="localhost"
PORT="8021"

python ${COMMAND_PATH} --host $HOST --port $PORT
