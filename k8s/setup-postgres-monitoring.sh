#!/bin/bash
set -euo pipefail

echo "Setting up PostgreSQL monitoring for NoETL..."

# Deploy postgres monitoring configuration (VMServiceScrape)
echo "Deploying PostgreSQL monitoring configuration..."
kubectl apply -f k8s/postgres/monitoring/

# Deploy Grafana dashboards
echo "Deploying Grafana dashboards..."
kubectl apply -f k8s/observability/postgres-dashboard-configmap.yaml
kubectl apply -f k8s/observability/noetl-server-dashboard-configmap.yaml

# Wait for postgres exporter to be ready
echo "Waiting for PostgreSQL exporter to be ready..."
kubectl rollout status deployment/postgres-exporter -n postgres --timeout=60s

# Restart Grafana to pick up new dashboards
echo "Restarting Grafana to pick up new dashboards..."
kubectl rollout restart deployment/vmstack-grafana -n noetl-platform
kubectl rollout status deployment/vmstack-grafana -n noetl-platform --timeout=120s

echo "PostgreSQL monitoring setup completed!"
echo ""
echo "To access Grafana:"
echo "  kubectl port-forward -n noetl-platform svc/vmstack-grafana 3000:80"
echo "  Then visit: http://localhost:3000 (admin/admin)"
echo ""
echo "Available dashboards:"
echo "  - PostgreSQL Dashboard"
echo "  - NoETL Server Overview"
echo ""
echo "To verify postgres metrics are being scraped:"
echo "  kubectl port-forward -n postgres svc/postgres-exporter 9187:9187"
echo "  curl http://localhost:9187/metrics | grep pg_up"