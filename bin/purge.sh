#!/bin/bash

NATS_URL="nats://localhost:32645"

nats stream purge commands  --force -s s{NATS_URL}
