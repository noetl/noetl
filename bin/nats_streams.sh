#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
kubectl apply -f ${DIR}/../k8s/nats/stream-tests.yaml -n nats
kubectl apply -f ${DIR}/../k8s/nats/commands/stream-commands.yaml -n nats
kubectl apply -f ${DIR}/../k8s/nats/commands/command-pull.yaml -n nats
