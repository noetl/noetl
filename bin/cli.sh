#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

NOETL_CLI_PATH="$DIR/../noetl/cli.py"

python ${NOETL_CLI_PATH}

# python ${NOETL_CLI_PATH} add workflow config file  "$DIR/../workflows/time/get-current-time.yaml"
