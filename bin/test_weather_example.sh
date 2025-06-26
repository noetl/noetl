#!/bin/bash
cd $(dirname $0)/..
./.venv/bin/python ./noetl/agent/agent.py -f ./catalog/playbooks/weather_example.yaml --debug -o plain --pgdb "dbname=noetl user=noetl password=noetl host=localhost port=5434" > ./data/log/agent.log 2>&1
