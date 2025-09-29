# NoETL Platform Components

This document describes all components in the NoETL platform, their responsibilities, and their dependencies on each other. 
## All Components

- PostgreSQL: Running in postgres namespace
- NoETL Server: Accessible at http://localhost:30082
- NoETL Workers: All 3 worker pools running (cpu-01, cpu-02, gpu-01)
- Grafana: Accessible at http://localhost:3000 (admin/admin)
- VictoriaMetrics: Running and accessible at http://localhost:8428/vmui/
- VictoriaLogs: Running and accessible at http://localhost:9428
- Dashboards: Both NoETL server and worker dashboards provisioned
- Datasources: Grafana datasources ConfigMap found and provisioned

## Architecture Diagram

```
                            +---------------------+
                            |     PostgreSQL      |
                            |  (metadata, jobs)   |
                            +----------^----------+
                                       |
                               reads/writes via
                                       |
+----------------------+       +-------+--------+        +----------------------+
|   VictoriaMetrics    |<------|   NoETL Server |<------>|    NoETL Workers     |
| (metrics storage)    |  scrapes  |  (API & UI) |  RPC  | (cpu-01, cpu-02,     |
+----------^-----------+        |               |        |  gpu-01 pools)       |
           |                    |               |        +----------^-----------+
           |                emits|metrics & logs|                   |
           |                    v               v                   |
           |            +---------------+   +---------------+       |
           |            |  Vector/Logs  |-->|  VictoriaLogs |<------+
           |            |  (agents)     |   |  (logs store) |
           |            +---------------+   +---------------+
           |
           +---------------------> Grafana <-------------------------+
                                  (dashboards & alerting)
                          reads from VM + VictoriaLogs datasources
```

Legend:
- NoETL Server communicates with Workers (task scheduling, status updates). Both write job/task metadata to PostgreSQL.
- Metrics are scraped by VictoriaMetrics (via PodMonitor/PodScrape). Logs are shipped by agents (Vector) to VictoriaLogs.
- Grafana reads from VictoriaMetrics and VictoriaLogs and shows pre-provisioned dashboards and datasources.

## Component Responsibilities & Dependencies

### 1. PostgreSQL
- Purpose: System-of-record for metadata (pipelines, jobs, tasks, results, scheduling state).
- Depends on: Persistent storage (Kubernetes PVC or external DB).
- Used by: NoETL Server.

### 2. NoETL Server
- Purpose: HTTP API/UI, orchestration, scheduling, and coordination of workers.
- Depends on:
  - PostgreSQL (read/write job and pipeline metadata)
  - Kubernetes (service discovery and worker orchestration)
  - Observability stack for metrics/logs export
- Provides:
  - API at http://localhost:30082
  - Metrics endpoint scraped by VictoriaMetrics
  - Logs shipped to VictoriaLogs via Vector agents

### 3. NoETL Workers (cpu-01, cpu-02, gpu-01)
- Purpose: Execute tasks; report status and metrics.
- Depends on:
  - NoETL Server (work assignment, heartbeats)
  - Container runtime / GPU drivers (for gpu-01)
- Emits:
  - Metrics scraped by VictoriaMetrics
  - Logs shipped to VictoriaLogs

### 4. VictoriaMetrics
- Purpose: Time-series metrics storage and query (PromQL-compatible).
- Depends on:
  - PodMonitor/PodScrape configs to discover Server and Worker metrics endpoints
- Used by:
  - Grafana (dashboards)

### 5. VictoriaLogs
- Purpose: Centralized logs storage and query.
- Depends on:
  - Log shippers (Vector agents) to forward container logs
- Used by:
  - Grafana (Explore/log panels)

### 6. Grafana
- Purpose: Visualization, dashboards, alerts.
- Depends on:
  - Datasource provisioning for VictoriaMetrics and VictoriaLogs
  - Dashboard provisioning for NoETL Server and Workers
- Endpoints:
  - http://localhost:3000 (admin/admin)

### 7. Provisioned Dashboards and Datasources
- Dashboards:
  - NoETL Server dashboard
  - NoETL Worker dashboard
- Datasources:
  - VictoriaMetrics (metrics)
  - VictoriaLogs (logs)

## Operational Notes
- Namespaces: PostgreSQL runs in the `postgres` namespace; other components typically run in a unified platform namespace (e.g., `noetl-platform`).
- Health checks: Use the unified make targets (e.g., `make unified-health-check`) to validate all components are up and endpoints are reachable.
- Troubleshooting:
  - Metrics scraping: see `k8s/observability/vmpodscrape-noetl.yaml`
  - Worker metrics monitors: see `k8s/observability/podmonitor-noetl-workers.yaml`
  - Logs shippers: see `k8s/observability/vector-values.yaml`
  - Prometheus/VictoriaMetrics tips: `docs/observability/troubleshoot-prometheus.md`
