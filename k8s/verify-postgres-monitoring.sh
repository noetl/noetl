#!/bin/bash
set -euo pipefail

echo "Verifying PostgreSQL monitoring setup..."
echo "======================================="

# Check if postgres exporter is running
echo "1. Checking PostgreSQL exporter status:"
if kubectl get pods -n postgres | grep postgres-exporter | grep -q Running; then
    echo "   ✓ PostgreSQL exporter is running"
else
    echo "   ✗ PostgreSQL exporter is not running"
    exit 1
fi

# Check if VMServiceScrape is operational
echo "2. Checking VMServiceScrape status:"
if kubectl get vmservicescrape -n postgres postgres-exporter -o jsonpath='{.status.updateStatus}' | grep -q operational; then
    echo "   ✓ VMServiceScrape is operational"
else
    echo "   ✗ VMServiceScrape is not operational"
    exit 1
fi

# Check if Grafana is running
echo "3. Checking Grafana status:"
if kubectl get pods -n noetl-platform | grep vmstack-grafana | grep -q "2/2.*Running"; then
    echo "   ✓ Grafana is running"
else
    echo "   ✗ Grafana is not running properly"
    exit 1
fi

# Check if dashboards are configured
echo "4. Checking dashboard ConfigMaps:"
if kubectl get configmap -n noetl-platform postgres-dashboard >/dev/null 2>&1; then
    echo "   ✓ PostgreSQL dashboard ConfigMap exists"
else
    echo "   ✗ PostgreSQL dashboard ConfigMap not found"
fi

if kubectl get configmap -n noetl-platform noetl-server-dashboard >/dev/null 2>&1; then
    echo "   ✓ NoETL server dashboard ConfigMap exists"
else
    echo "   ✗ NoETL server dashboard ConfigMap not found"
fi

# Test metrics availability (optional - requires port forwarding)
echo "5. Testing metrics availability (requires port-forward):"
echo "   Run the following to test metrics:"
echo "   kubectl port-forward -n postgres svc/postgres-exporter 9187:9187 &"
echo "   curl http://localhost:9187/metrics | grep pg_up"
echo ""

echo "Setup verification completed!"
echo ""
echo "To access Grafana:"
echo "  kubectl port-forward -n noetl-platform svc/vmstack-grafana 3000:80"
echo "  Then visit: http://localhost:3000"
echo "  Login: admin/admin"
echo ""
echo "Available dashboards should include:"
echo "  - PostgreSQL Dashboard"
echo "  - NoETL Server Overview"