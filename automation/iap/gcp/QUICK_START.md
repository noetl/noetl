# NoETL GKE Quick Start

## Connect to Cluster

```bash
gcloud container clusters get-credentials noetl-cluster --region us-central1 --project <PROJECT_ID>
```

## Run Post-Deployment Setup

```bash
noetl run automation/iap/gcp/post_deploy_setup.yaml --set action=setup
```

## Access Services

| Service | Command |
|---------|---------|
| Gateway (Public) | `curl http://$(kubectl get svc gateway -n gateway -o jsonpath='{.status.loadBalancer.ingress[0].ip}')/health` |
| NoETL Server UI | `kubectl port-forward -n noetl svc/noetl 8082:8082` → http://localhost:8082/docs |
| PostgreSQL | `kubectl port-forward -n postgres svc/postgres 5432:5432` → `psql -h localhost -U postgres -d noetl` (pw: demo) |
| ClickHouse | `kubectl port-forward -n clickhouse svc/clickhouse 8123:8123` → http://localhost:8123 |

## Upload Playbooks & Credentials

```bash
# Register playbook
noetl register playbook --file path/to/playbook.yaml

# Register credential
noetl register credential --file path/to/credential.json

# Run playbook
noetl run playbook_name --set key=value
```

## View Logs

```bash
kubectl logs -n noetl -l app=noetl-worker -f    # Worker logs
kubectl logs -n noetl -l app=noetl -f           # Server logs
kubectl logs -n gateway -l app=gateway -f       # Gateway logs
```

## Sync Events to ClickHouse

```bash
kubectl exec -n postgres postgres-0 -- psql -U postgres -d noetl -t -A -c "
SELECT json_build_object('Timestamp', to_char(created_at, 'YYYY-MM-DD HH24:MI:SS'),
  'EventId', event_id::text, 'ExecutionId', execution_id::text, 'EventType', event_type,
  'Duration', COALESCE((duration * 1000)::bigint, 0))
FROM noetl.event WHERE created_at >= NOW() - INTERVAL '1 hour' LIMIT 1000;
" | kubectl exec -i -n clickhouse clickhouse-0 -- clickhouse-client \
  --query="INSERT INTO observability.noetl_events FORMAT JSONEachRow"
```

## Verify Setup

```bash
noetl run automation/iap/gcp/post_deploy_setup.yaml --set action=verify
```

---
See [GKE_USER_GUIDE.md](GKE_USER_GUIDE.md) for detailed documentation.
