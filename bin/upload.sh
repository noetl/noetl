#!/bin/bash
curl http://127.0.0.1:8000/graphql \
   -F operations='{ "query": "mutation($file: Upload!){ readFile(file: $file) }", "variables": { "file": null } }' \
   -F map='{ "file": ["variables.file"] }' \
   -F file=@../conf/example_workflow.yaml
