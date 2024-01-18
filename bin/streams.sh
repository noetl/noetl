#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
kubectl apply -f ${DIR}/../k8s/nats/tests/test-stream.yaml -n nats
kubectl apply -f ${DIR}/../k8s/nats/commands/command-stream.yaml -n nats
kubectl apply -f ${DIR}/../k8s/nats/commands/command-pull.yaml -n nats
kubectl apply -f ${DIR}/../k8s/nats/events/event-stream.yaml -n nats
kubectl apply -f ${DIR}/../k8s/nats/events/event-pull.yaml -n nats
