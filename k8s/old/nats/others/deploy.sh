# kubectl apply -f nats-namespace.yaml
#helm repo add nats https://nats-io.github.io/k8s/helm/charts/
#helm repo update
#helm install nats nats/nats -n nats --set=nats.jetstream.enabled=true
#helm install nack nats/nack -n nats --set jetstream.nats.url=nats://nats:4222
helm upgrade --install nats nats/nats \
    --values values.yaml \
    --namespace nats --create-namespace
