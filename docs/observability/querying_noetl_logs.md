# Querying NoETL logs (server and worker pools)

This guide shows how to explore and query NoETL logs using VictoriaLogs (built‑in UI and Grafana).
It assumes you deployed the local stack via `make observability-deploy`, which also starts port‑forwards:

- VictoriaLogs UI: http://localhost:9428
- Grafana: http://localhost:3000 (get credentials via `make observability-grafana-credentials`)

Vector ships Kubernetes container logs to VictoriaLogs in Loki wire‑format with these labels:
- app (from the pod label)
- namespace
- pod
- container
- job="kubernetes"

The examples below use these labels to filter NoETL server and worker logs.

## Quick filters

- NoETL server logs:
  - `{app="noetl"}`
- NoETL worker pool logs:
  - `{app="noetl-worker"}`

Add label filters as needed, for example restrict to a namespace or pod:
- `{app="noetl" , namespace="default"}`
- `{app="noetl-worker", pod="noetl-worker-abc123"}`

You can also search by text in the log line using `|=`, `|~`, etc. (LogQL‑style):
- Errors for server: `{app="noetl"} |= "ERROR"`
- Warnings+Errors for workers: `{app="noetl-worker"} |= "WARN" or {app="noetl-worker"} |= "ERROR"`
- Messages with an execution ID: `{app="noetl-worker"} |= "execution_id=12345"`

Tip: Consider adding structured fields in your logs like `component=server|worker`, `pool_id=...`, `execution_id=...` to enable richer filters.

## In VictoriaLogs UI

Open http://localhost:9428 then:
1. Select the Explore (query) page.
2. Enter a query, e.g. `{app="noetl"}` and hit Run.
3. Use the label selectors above the editor to add filters (namespace, pod, container).
4. Toggle the histogram to see log volume over time.

Useful queries:
- Server error spike:
  - `{app="noetl"} |= "ERROR"`
- Worker retries (text search):
  - `{app="noetl-worker"} |= "retry"`
- Top noisy pods over last 5m:
  - `topk(5, sum by (pod) (count_over_time({app="noetl-worker"}[5m])))`

## In Grafana (with VictoriaLogs datasource)

1. In Grafana, ensure the VictoriaLogs datasource is installed and points to `http://vlogs-victoria-logs-single.observability.svc:9428`.
2. Create a new panel, pick the VictoriaLogs datasource.
3. Use queries like the examples above. Common patterns:
   - Log stream panel for server: `{app="noetl"}`
   - Error rate (lines/min) across worker pods:
     - `sum by (pod) (count_over_time({app="noetl-worker"} |= "ERROR" [1m]))`
   - Top pods by volume (5m window):
     - `topk(5, sum by (pod) (count_over_time({app="noetl-worker"}[5m])))`

## Ready‑made dashboards

Import these JSON dashboards into Grafana (Dashboards → Import):
- Server: docs/observability/dashboards/noetl-server-dashboard.json
- Workers: docs/observability/dashboards/noetl-workers-dashboard.json

On import, Grafana will ask you to map datasources:
- For metrics: choose your VictoriaMetrics (or Prometheus) datasource (the VM stack exposes a Prometheus‑compatible API).
- For logs: choose the VictoriaLogs datasource.

## Troubleshooting

- No logs appear:
  - Ensure Vector is running as a DaemonSet and `service.enabled: false` in values when using Agent role.
  - Check that the VictoriaLogs Service is up and the port‑forward is running (`k8s/observability/port-forward.sh status`).
- Queries error in Grafana:
  - Verify the VictoriaLogs datasource URL.
  - If functions like `count_over_time` or `topk` error, ensure you’re using the VictoriaLogs datasource (not Prometheus).
- Labels missing:
  - The Vector values in `k8s/observability/vector-values.yaml` enrich labels app/namespace/pod/container; confirm the DaemonSet is using those values.
