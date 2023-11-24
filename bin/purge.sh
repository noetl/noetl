#!/bin/bash

NATS_PORT=$(kubectl get svc nats -n nats -o=jsonpath='{.spec.ports[0].nodePort}')
NATS_URL="nats://localhost:${NATS_PORT}"

nats stream purge commands  --force -s ${NATS_URL}
