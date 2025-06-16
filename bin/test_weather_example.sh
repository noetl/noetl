#!/bin/bash
cd $(dirname $0)/..
./.venv/bin/python ./noetl/agent/agent007.py -f ./catalog/playbooks/weather_example.yaml -o plain --duckdb "./data/noetldb/agent007.duckdb" --sync --pgdb "dbname=noetl user=noetl password=noetl host=localhost port=5434" > ./data/log/agent007.log 2>&1
