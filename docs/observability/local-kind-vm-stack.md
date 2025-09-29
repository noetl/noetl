# Local observability stack (kind): VictoriaMetrics + VictoriaLogs + Grafana + Vector

This guide shows a minimal, copy‑pasteable setup for a fast local observability stack on a kind cluster.

Stack overview:
- Metrics: VictoriaMetrics (single-node) + vmagent scrapes Kubernetes and your pods
- Logs: VictoriaLogs (single-node) + Vector DaemonSet ships container logs
- UI & dashboards: Grafana with VictoriaMetrics and VictoriaLogs data-source plugins

0) Quick start: one command via Makefile:

```
make observability-deploy
```

This will:
- Add/Update Helm repos and create the 'observability' namespace if needed
- Install VictoriaMetrics k8s stack (Grafana + vmagent + vmsingle), VictoriaLogs, and Vector Agent
- Use k8s/observability/vector-values.yaml if present to configure Vector → VictoriaLogs
- Use k8s/observability/vmstack-values.yaml to customize vmagent (disabled control-plane scrapes, retained helpers)
- Auto-provision Grafana datasources (VictoriaMetrics + VictoriaLogs) via ConfigMap (sidecar)
- Automatically start port-forwarding for Grafana (3000), VictoriaLogs (9428), and VictoriaMetrics UI (8428) in the background
- Print how to manage the port-forwards (start/stop/status)

Open your browser:
- Grafana:            http://localhost:3000
- VictoriaLogs UI:    http://localhost:9428
- VictoriaMetrics UI: http://localhost:8428/vmui/

Credentials & logins:
- Grafana: default admin credentials are generated and stored in the Secret vmstack-grafana.
  Quick way: run `make observability-grafana-credentials` to print the username/password.
  Or retrieve them (cross-platform) with kubectl go-template:

  ```bash
  kubectl -n observability get secret vmstack-grafana \
    -o go-template='user: {{index .data "admin-user" | base64decode}}{{"\n"}}pass: {{index .data "admin-password" | base64decode}}{{"\n"}}'
  ```
  Then log in at http://localhost:3000 with the printed user/pass (typically user is admin).

- VictoriaLogs UI: no authentication by default; open http://localhost:9428
- VictoriaMetrics vmui: no authentication by default; open http://localhost:8428/vmui/

To manage port-forwards later:
- Start:  `k8s/observability/port-forward.sh start`  (or: `make observability-port-forward-start`)
- Stop:   `k8s/observability/port-forward.sh stop`   (or: `make observability-port-forward-stop`)
- Status: `k8s/observability/port-forward.sh status` (or: `make observability-port-forward-status`)

You can still follow the manual Helm steps below if you prefer.

Redeploy/reset the observability stack:

- Quick redeploy (stop port-forwards, uninstall Helm releases, clean NoETL dashboard ConfigMaps, re-deploy):

```bash
make observability-redeploy
```

- Manual (alternative):

```bash
# stop port-forwards (if you started them manually or via the script)
k8s/observability/port-forward.sh stop

# uninstall Helm releases
helm -n observability uninstall vector || true
helm -n observability uninstall vlogs || true
helm -n observability uninstall vmstack || true

# optional: remove provisioned dashboard ConfigMaps so the sidecar re-imports fresh
kubectl -n observability delete cm -l grafana_dashboard=1 || true

# deploy again
make observability-deploy
```

1) Install the stack (Helm)

```bash
# repos
helm repo add vm https://victoriametrics.github.io/helm-charts/
helm repo add vector https://helm.vector.dev
helm repo update

# namespace
kubectl create ns observability

# Metrics: all-in-one k8s stack (Grafana + vmagent + vmsingle + node-exporter + kube-state-metrics)
helm install vmstack vm/victoria-metrics-k8s-stack -n observability \
  --set grafana.enabled=true \
  --set vmsingle.enabled=true \
  --set vmsingle.spec.retentionPeriod=1w \
  --set vmagent.enabled=true
# (The chart bundles Grafana and auto-scrapes core k8s. It’s a Prometheus-compatible stack.)

The Makefile-driven deployment automatically includes `k8s/observability/vmstack-values.yaml`, which disables the noisy control-plane scrape jobs and tunes vmagent defaults. Adjust that file if you need to re-enable those targets or add more scrape configs.

# Logs: VictoriaLogs (single node)
helm install vlogs vm/victoria-logs-single -n observability
# (Single binary, listens on :9428 for ingest, query, and its built-in UI.)

# Vector agent (DaemonSet role) to ship container logs
helm install vector vector/vector -n observability \
  --set role=Agent
# (Official Vector Helm chart; Agent role runs as a DaemonSet.)
```

Port-forward UIs locally (manual alternative):

```bash
# Grafana
kubectl -n observability port-forward svc/vmstack-grafana 3000:80
# VictoriaLogs UI
kubectl -n observability port-forward svc/vlogs-victoria-logs-single 9428:9428
# VictoriaMetrics vmui (optional quick queries)
kubectl -n observability port-forward svc/vmstack-victoria-metrics-single 8428:8428
```

Grafana: add the VictoriaMetrics and VictoriaLogs datasource plugins if they’re not preloaded.
- VM’s vmui: http://localhost:8428/vmui/
- VictoriaLogs UI: http://localhost:9428

2) Vector → VictoriaLogs (shipping K8s container logs)

Use Vector’s kubernetes_logs source and send to VictoriaLogs. The repository’s
Makefile ships with the JSON streaming configuration (Option B) baked into
`k8s/observability/vector-values.yaml`, so `make observability-deploy`
automatically deploys Vector with that sink. If you prefer the Loki push API you
can swap the sink block to Option A before re-running the Helm upgrade.

Option A — Loki wire-format (optional)

```yaml
sinks:
  vlogs:
    type: loki
    inputs: [enrich]
    endpoint: http://vlogs-victoria-logs-single.observability.svc.cluster.local:9428
    path: /insert/loki/api/v1/push
    encoding:
      codec: json
    labels:
      job: "kubernetes"
      app: "{{`{{labels.app}}`}}"
      namespace: "{{`{{labels.namespace}}`}}"
      pod: "{{`{{labels.pod}}`}}"
      container: "{{`{{labels.container}}`}}"
```

Option B — JSON stream API (default)

```yaml
sinks:
  vlogs_json:
    type: http
    inputs: [enrich]
    method: post
    uri: "http://vlogs-victoria-logs-single-server-0.vlogs-victoria-logs-single-server.observability.svc.cluster.local:9428/insert/jsonline?_stream_fields=labels.namespace,labels.pod,labels.container&_msg_field=log&_time_field=timestamp"
    encoding:
      codec: json
    framing:
      method: newline_delimited
    compression: gzip
```

Apply (or reapply) the Vector configuration anytime with:

```bash
helm upgrade --install vector vector/vector -n observability -f k8s/observability/vector-values.yaml
```

3) Grafana UI: dashboards & datasources

- Datasources (auto-provisioned):
  - The deploy script provisions two datasources via Grafana’s sidecar:
    - Metrics: Prometheus datasource named “VictoriaMetrics” pointing to vmstack vmsingle (in-cluster URL).
    - Logs: “VictoriaLogs” datasource pointing to the VictoriaLogs service (in-cluster URL).
  - Re-provision datasources anytime: `make observability-provision-datasources`.
- Dashboards (auto-provisioned):
  - After `make observability-deploy`, the NoETL dashboards are provisioned into Grafana via ConfigMaps (sidecar) and also imported via the Grafana HTTP API. The importer now auto-maps dashboard datasources: DS_PROMETHEUS → "VictoriaMetrics" and DS_VICTORIA_LOGS → "VictoriaLogs". They should appear under Dashboards → Browse → NoETL and start querying immediately.
  - Included dashboards:
    - Server: docs/observability/dashboards/noetl-server-dashboard.json
    - Workers: docs/observability/dashboards/noetl-workers-dashboard.json
  - If panels still show “no data”:
    - Metrics: ensure your NoETL server is being scraped (it must expose /metrics and be discovered by vmagent; use PodMonitor/ServiceMonitor or annotations). If running outside the cluster, the VM stack won’t auto-scrape it.
    - Logs: ensure your NoETL pods carry app labels expected by the dashboards: `app=noetl` (server) and `app=noetl-worker` (workers). The Vector config maps Kubernetes pod_labels.app into the `app` label in logs.
  - Re-provision dashboards anytime: `make observability-provision-dashboards`.
  - Re-import via API anytime: `make observability-import-dashboards` (waits for Grafana to be ready by default; override wait with flags in k8s/observability/import-dashboards.sh such as `--timeout=120`).
  - You can also import the VictoriaLogs Explorer dashboard from Grafana.com for general log exploration.

Log queries guide: see docs/observability/querying-noetl-logs.md for examples of filtering server vs worker logs, error rates, and top noisy pods.

4) Scrape your NoETL server and worker pools

Expose a /metrics endpoint (Prometheus format). This repository now exposes it on the API server at /metrics.

For worker pools, add similar endpoints or rely on app-level metrics. Then either:
- Let vmagent auto-discover via annotations; or
- Add a ServiceMonitor/PodMonitor.

Example PodMonitor (minimal) is provided at k8s/observability/podmonitor-noetl-workers.yaml.
The Makefile deploy script also applies k8s/observability/vmpodscrape-noetl.yaml so
vmagent immediately scrapes the NoETL API `/metrics` endpoint in the `noetl`
namespace. Adjust the manifest if you change namespaces or labels.

Tip: add labels in your app logs (e.g., component=server|worker, pool_id, execution_id) so Vector → VictoriaLogs gives you filtered views per pool/execution.

Why this combo?
- Small & fast for dev
- Great UI: Grafana + built-in UIs (vmui and VictoriaLogs)
- Easy agents: vmagent + Vector DaemonSet
