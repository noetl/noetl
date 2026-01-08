#!/bin/bash
# Regenerate gateway-ui-files ConfigMap from source files
# Run this script whenever you update UI files in tests/fixtures/gateway_ui/

set -e

echo "Regenerating gateway-ui-files ConfigMap manifest..."

kubectl create configmap gateway-ui-files \
  --from-file=tests/fixtures/gateway_ui/ \
  --namespace=gateway \
  --dry-run=client \
  -o yaml > ci/manifests/gateway/configmap-ui-files.yaml

echo "✅ ConfigMap manifest updated: ci/manifests/gateway/configmap-ui-files.yaml"
echo ""
echo "To apply changes to cluster:"
echo "  kubectl apply -f ci/manifests/gateway/configmap-ui-files.yaml"
echo "  kubectl rollout restart deployment/gateway-ui -n gateway"
