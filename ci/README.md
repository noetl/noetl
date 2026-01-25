# NoETL Environment

NoETL uses automation playbooks for infrastructure and deployment management.
The following tools are available for in-cluster troubleshooting: [Tshoot](manifests/tshoot/README.md)

## Available Components

After deployment, the following components are available on the host system:
- Noetl server: http://localhost:8082/
- VictoriaLogs: http://localhost:9428/select/vmui
- Grafana: http://localhost:3000
  - with login: `admin`; password: `admin`
- Postgres: **`localhost:54321`**
  - database: `demo_noetl`
  - user: `noetl`
  - password: `noetl`
  - JDBC URL: `jdbc:postgresql://localhost:54321/demo_noetl`

---
#### Requirements:
- docker
- kind
- kubectl
- yq
- helm

Install **kind**, **kubectl**, **yq** on MacOS:
```
brew install kind
brew install kubectl
brew install yq
brew install helm
```

## Quick Start

### Bootstrap Everything

```bash
# Complete environment setup (build + deploy all components)
noetl run automation/setup/bootstrap.yaml
```

This single command:
- Verifies dependencies (Docker, kubectl, helm, kind)
- Builds NoETL Docker images
- Creates Kind cluster
- Loads images into cluster
- Deploys PostgreSQL
- Deploys observability stack
- Deploys monitoring stack
- Deploys NoETL services

## Step-by-Step Setup

### 1. Create **noetl** kind cluster

```bash
noetl run automation/infrastructure/kind.yaml --set action=create
```

### 2. Deploy Postgres

```bash
noetl run automation/infrastructure/postgres.yaml --set action=deploy
```

This command deploys Postgres 17.4 to the **noetl** cluster.

The `pgdata` folder of the Postgres pod will be mounted to the `ci/kind/data` (excluded with `.gitignore`) folder on the host system. That way Postgres data is preserved even if all Docker volumes are pruned.

The Postgres port will be exposed as `54321` on the host system. With this configuration, Postgres running in the **noetl** kind cluster will be available to applications on the host machine at `localhost:54321` with login `noetl` and password `noetl`. JDBC URL example: `jdbc:postgresql://localhost:54321/demo_noetl`

Note about ports you may see in kubectl vs. on the host:
- Inside the Kubernetes cluster, the service `postgres-ext` is a NodePort listening on `30321` (what can be seen in `kubectl get svc`).
- Kind maps that NodePort `30321` to host port `54321` via `extraPortMappings` in `ci/kind/config.yaml`:
  - containerPort: `30321` -> hostPort: `54321`
- As a result, you can connect to Postgres from:
  - In-cluster: NodePort is 30321 (and the ClusterIP service port is 5432).
  - From the host: connect to `localhost:54321` (e.g., `jdbc:postgresql://localhost:54321/demo_noetl`).

#### The mapping chain:
- Machine host (localhost:54321)
    ↓ (Docker port mapping)
- Kind Container (30321)
    ↓ (Kubernetes NodePort service)
- PostgreSQL Pod (5432)  (ClusterIP service)

### 3. Build noetl

**Using Rust CLI (Recommended):**
```bash
noetl build
# or without cache:
noetl build --no-cache
```

The Rust CLI automatically:
- Generates timestamp-based tag (YYYY-MM-DD-HH-MM)
- Saves tag to `.noetl_last_build_tag.txt`
- Streams build output to console

### 4. Deploy noetl

**Using Rust CLI (Recommended):**
```bash
noetl k8s deploy
```

The Rust CLI automatically:
- Reads image tag from `.noetl_last_build_tag.txt`
- Loads image into kind cluster (`kind load docker-image`)
- Updates deployment manifests with correct image reference
- Applies Kubernetes manifests
- Restores original manifest templates

---

The noetl service port `8082` is exposed as port `8082` on the host system. Container folders `/opt/noetl/data` and `/opt/noetl/logs` are mounted to the host folders `ci/kind/cache/noetl-data` and `ci/kind/cache/noetl-logs`, respectively. The container status can be checked at http://localhost:8082/api/health

### Rust CLI Kubernetes Commands

The `noetl` Rust CLI provides additional K8s management commands:

**Rebuild and Redeploy:**
```bash
noetl k8s redeploy
# or without cache:
noetl k8s redeploy --no-cache
```
This command:
1. Builds the Docker image
2. Removes existing deployment
3. Loads image to kind cluster
4. Deploys to Kubernetes

**Full Reset (Schema + Redeploy + Test Setup):**
```bash
noetl k8s reset
# or without cache:
noetl k8s reset --no-cache
```
This command performs a complete reset:
1. Resets Postgres schema
2. Rebuilds and redeploys NoETL
3. Installs NoETL CLI with dev dependencies
4. Sets up test environment (tables, credentials)

**Remove NoETL:**
```bash
noetl k8s remove
```

## Install VictoriaMetrics stack

### Using Automation Playbook (Recommended)

```bash
noetl run automation/infrastructure/monitoring.yaml --set action=deploy
```

### Manual Installation

#### 1. Add Helm repositories

```bash
helm repo add vm https://victoriametrics.github.io/helm-charts/
helm repo add metrics-server https://kubernetes-sigs.github.io/metrics-server/
helm repo add vector https://helm.vector.dev
helm repo update
```

#### 2. (Optional) Check available Helm chart versions

```bash
helm search repo vm/victoria-metrics-k8s-stack -l
helm search repo vm/victoria-metrics-operator -l
helm search repo vm/victoria-logs-single -l
helm search repo metrics-server/metrics-server -l
helm search repo vector/vector -l
```

|         Deployment        | Version in use |
|:--------------------------|:--------------:|
| VictoriaMetrics stack    | 0.60.1         |
| VictoriaMetrics operator | 0.54.0         |
| VictoriaLogs             | 0.11.11        |
| Metrics Server            | 3.13.0         |
| Vector                    | 0.46.0         |

#### 3. Install components

```bash
# Install metrics server
helm upgrade --install metrics-server metrics-server/metrics-server -n kube-system

# Install VictoriaMetrics operator
helm upgrade --install vm-operator vm/victoria-metrics-operator -n vmstack --create-namespace

# Install VictoriaMetrics stack
helm upgrade --install vmstack vm/victoria-metrics-k8s-stack -n vmstack

# Install VictoriaLogs
helm upgrade --install vmlogs vm/victoria-logs-single -n vmstack

# Install Vector
helm upgrade --install vector vector/vector -n vmstack
```

After deployment, Grafana is available at http://localhost:3000 with the login `admin` and password `admin`.

## Observability Stack

Deploy ClickHouse, Qdrant, and NATS:

```bash
# Deploy all observability services
noetl run automation/infrastructure/observability.yaml --set action=deploy

# Check status
noetl run automation/infrastructure/observability.yaml --set action=status

# Deploy individual services
noetl run automation/infrastructure/clickhouse.yaml --set action=deploy
noetl run automation/infrastructure/qdrant.yaml --set action=deploy
noetl run automation/infrastructure/nats.yaml --set action=deploy
```

## Automation Playbooks Reference

All automation playbooks are located in the `automation/` directory:

### Setup
- `automation/setup/bootstrap.yaml` - Complete environment setup
- `automation/setup/destroy.yaml` - Tear down environment

### Infrastructure
- `automation/infrastructure/kind.yaml` - Kind cluster management
- `automation/infrastructure/postgres.yaml` - PostgreSQL operations
- `automation/infrastructure/monitoring.yaml` - VictoriaMetrics stack
- `automation/infrastructure/observability.yaml` - Unified observability control
- `automation/infrastructure/clickhouse.yaml` - ClickHouse operations
- `automation/infrastructure/qdrant.yaml` - Qdrant operations
- `automation/infrastructure/nats.yaml` - NATS operations

### Deployment
- `automation/deployment/noetl-stack.yaml` - NoETL service deployment

### Development
- `automation/development/docker.yaml` - Docker image building
- `automation/development/noetl.yaml` - Development workflow

### Common Actions

```bash
# Create cluster
noetl run automation/infrastructure/kind.yaml --set action=create

# Delete cluster
noetl run automation/infrastructure/kind.yaml --set action=delete

# Deploy component
noetl run automation/infrastructure/postgres.yaml --set action=deploy

# Remove component
noetl run automation/infrastructure/postgres.yaml --set action=remove

# Check status
noetl run automation/infrastructure/postgres.yaml --set action=status

# Port forward
noetl run automation/infrastructure/postgres.yaml --set action=port-forward
```

## Teardown

```bash
# Destroy all infrastructure
noetl run automation/setup/destroy.yaml

# Or just delete the Kind cluster
noetl run automation/infrastructure/kind.yaml --set action=delete
```
