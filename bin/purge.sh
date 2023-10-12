#!/bin/bash

NATS_URL="nats://localhost:32645"

nats stream purge commands  --force -s ${NATS_URL}
