# Docker Hub Rate Limiting Issue - VictoriaMetrics Components

## Current Status

### ✅ Working Components:
- NoETL Server & Workers
- PostgreSQL & PostgreSQL Exporter  
- Grafana (accessible at http://localhost:3000)
- VictoriaLogs (log collection)
- Vector (log shipping)
- VictoriaMetrics Operator

### ❌ Affected Components (ImagePullBackOff):
- VictoriaMetrics Single (vmsingle) - metrics storage
- VMAgent (vmagent) - metrics collection  
- VMAlert (vmalert) - alerting
- VMAlertManager (vmalertmanager) - alert management

## Root Cause
Docker Hub rate limiting is preventing image pulls:
```
Error: "429 Too Many Requests - You have reached your unauthenticated pull rate limit"
```

## Impact
- Grafana is running but cannot display metrics dashboards (no metrics storage)
- PostgreSQL monitoring configuration is deployed but metrics aren't being stored
- Log collection is working (VictoriaLogs is running)

## Solutions

### Immediate (Wait for Rate Limit Reset)
Docker Hub rate limits typically reset after:
- **100 pulls per 6 hours** for anonymous users
- **200 pulls per 6 hours** for authenticated users

**Action**: Wait 1-2 hours and run:
```bash
make unified-port-forward-stop
kubectl delete pods -n noetl-platform -l "app.kubernetes.io/name in (victoria-metrics,vmagent,vmalert)"
# Wait for rate limit reset
make unified-recreate-all
```

### Alternative Solutions

#### 1. Use Docker Hub Authentication
```bash
docker login
# Then redeploy
```

#### 2. Pre-pull Images
```bash
# Once rate limit resets, pre-pull images
docker pull victoriametrics/victoria-metrics:v1.126.0
docker pull victoriametrics/vmagent:v1.126.0  
docker pull victoriametrics/vmalert:v1.126.0
# Then load into Kind
kind load docker-image victoriametrics/victoria-metrics:v1.126.0 --name noetl-cluster
kind load docker-image victoriametrics/vmagent:v1.126.0 --name noetl-cluster
kind load docker-image victoriametrics/vmalert:v1.126.0 --name noetl-cluster
```

#### 3. Use Alternative Registry (if available)
Update Helm values to use different image registry (quay.io, ghcr.io, etc.)

## Monitoring Current Status
```bash
# Check component status
kubectl get pods -n noetl-platform | grep victoria

# Check image pull errors
kubectl describe pod <pod-name> -n noetl-platform | tail -10

# Try manual image pull to test rate limit status  
docker pull victoriametrics/victoria-metrics:v1.126.0
```

## Expected Recovery Time
- **Rate limit reset**: 1-6 hours depending on usage
- **Full monitoring restore**: ~5 minutes after images are available

## Workaround
The PostgreSQL monitoring setup is complete and will work immediately once VictoriaMetrics components start. Grafana dashboards are deployed and ready to display data.