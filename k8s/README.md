# NoETL Kubernetes Deployment

Deploy the complete NoETL platform (Postgres + NoETL server) to a local Kubernetes cluster using Kind (Kubernetes in Docker).

##  Quick Start

The easiest way to deploy NoETL is using the Makefile targets:

```bash
# Deploy the complete platform
make k8s-platform-deploy

# Check status
make k8s-platform-status

# Test with a simple playbook
make k8s-platform-test

# Clean up when done
make k8s-platform-clean
```

**That's it!** The platform will be available at:
- **Health Check**: http://localhost:30082/api/health
- **API Documentation**: http://localhost:30082/docs
- **Main API**: http://localhost:30082/

### Namespaces
- NoETL server resources are deployed to the `noetl` namespace.
- Worker pools run in dedicated namespaces: `noetl-worker-cpu-01`, `noetl-worker-cpu-02`, and `noetl-worker-gpu-01`.
- Postgres continues to run in the `postgres` namespace.

##  Deployment Options

### Current Implementation
- **Image**: `noetl-local-dev:latest` (built from local source)
- **Health Endpoint**: `/api/health` (not `/health`)
- **Container Port**: 8082 with NodePort 30082
- **Database**: Postgres in dedicated `postgres` namespace
- **Server**: Direct uvicorn execution (not subprocess wrapper)

##  Prerequisites

- **Docker** installed and running
- **kubectl** installed
- **Kind** installed (see installation instructions below)
- **Make** installed (for using Makefile targets)
- Internet connection to pull base container images

##  Installing Kind

Kind (Kubernetes IN Docker) runs local Kubernetes clusters using Docker containers as nodes.

### macOS
```bash
# Using Homebrew (recommended)
brew install kind

# Or using binary
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-darwin-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind
```

### Linux
```bash
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind
```

### Windows
```powershell
# Using Chocolatey
choco install kind

# Or using binary
curl.exe -Lo kind-windows-amd64.exe https://kind.sigs.k8s.io/dl/v0.20.0/kind-windows-amd64
Move-Item .\kind-windows-amd64.exe c:\some-dir-in-your-PATH\kind.exe
```

##  Deployment Methods

### Method 1: Makefile Targets (Recommended)

The simplest approach using our pre-configured Makefile targets:

```bash
# Deploy everything in one command
make k8s-platform-deploy

# This will:
# - Create Kind cluster (noetl-cluster) 
# - Build Docker images (postgres-noetl, noetl-local-dev)
# - Deploy Postgres in 'postgres' namespace
# - Deploy NoETL server in 'default' namespace  
# - Initialize database schema
# - Configure health checks and services
```

### Method 2: Deployment Script

Direct script execution with options:

```bash
# Basic deployment
./k8s/deploy-platform.sh

# With options
./k8s/deploy-platform.sh --no-cluster    # Skip cluster creation
./k8s/deploy-platform.sh --no-postgres   # Skip Postgres deployment
./k8s/deploy-platform.sh --help         # Show all options
```

##  What Gets Deployed

### Postgres Database
- **Namespace**: `postgres` 
- **Image**: `postgres-noetl:latest` (built from `docker/postgres/`)
- **Storage**: Persistent volume at `/mnt/data` in Kind node
- **Database**: `demo_noetl` with `noetl` schema
- **Users**: `demo` (admin), `noetl` (application user)

### NoETL Server  
- **Namespace**: `default`
- **Image**: `noetl-local-dev:latest` (built from local source)
- **Port**: 8082 (exposed as NodePort 30082)
- **Health**: `/api/health` endpoint
- **Database**: Auto-initializes schema on startup
- **Execution**: Direct uvicorn (not subprocess wrapper)

### Fixes Applied
During development, we resolved several key issues:
-  **Namespace Creation**: Added `postgres-namespace.yaml` 
-  **Health Endpoint**: Fixed from `/health` to `/api/health`
-  **Database Schema**: Fixed UUID vs BIGINT type issues
-  **Process Management**: Fixed container exit issues 
-  **Volume Mounts**: Added logs directory support
-  **Docker Images**: Use local-dev vs pip image compatibility

### Method 3: Manual Deployment

For advanced users who want full control:

```bash
# 1. Create Kind cluster with port mappings
cat > kind-config.yaml << EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30082
    hostPort: 30082
    protocol: TCP
EOF

kind create cluster --name noetl-cluster --config kind-config.yaml

# 2. Build and load images
./docker/build-images.sh
kind load docker-image postgres-noetl:latest --name noetl-cluster
kind load docker-image noetl-local-dev:latest --name noetl-cluster

# 3. Create persistent volume directory
docker exec noetl-cluster-control-plane mkdir -p /mnt/data

# 4. Deploy Postgres
kubectl apply -f k8s/postgres/postgres-namespace.yaml
kubectl apply -f k8s/postgres/postgres-pv.yaml  
kubectl apply -f k8s/postgres/postgres-configmap.yaml
kubectl apply -f k8s/postgres/postgres-config-files.yaml
kubectl apply -f k8s/postgres/postgres-secret.yaml
kubectl apply -f k8s/postgres/postgres-deployment.yaml
kubectl apply -f k8s/postgres/postgres-service.yaml

# 5. Wait for Postgres to be ready
kubectl wait --for=condition=ready pod -l app=postgres -n postgres --timeout=180s

# 6. Deploy NoETL
kubectl apply -f k8s/noetl/noetl-configmap.yaml
kubectl apply -f k8s/noetl/noetl-secret.yaml  
kubectl apply -f k8s/noetl/noetl-deployment.yaml
kubectl apply -f k8s/noetl/noetl-service.yaml

# 7. Wait for NoETL to be ready
kubectl wait --for=condition=ready pod -l app=noetl --timeout=180s
```

## 🌐 Accessing NoETL

Once deployed, NoETL is available at:

| Endpoint | URL | Description |
|----------|-----|-------------|
| **Health Check** | http://localhost:30082/api/health | Service health status |
| **API Documentation** | http://localhost:30082/docs | Interactive Swagger UI |
| **Main API** | http://localhost:30082/ | Root API endpoint |
| **OpenAPI Spec** | http://localhost:30082/openapi.json | API specification |

### Quick Verification

```bash
# Health check
curl http://localhost:30082/api/health

# List registered playbooks  
curl http://localhost:30082/api/catalog/playbooks

# Check deployment status
make k8s-platform-status
```

##  Using NoETL

### Makefile Commands

| Command | Description |
|---------|-------------|
| `make k8s-platform-deploy` | Deploy complete platform |
| `make k8s-platform-status` | Check deployment status |
| `make k8s-platform-test` | Test with sample playbook |
| `make k8s-platform-clean` | Clean up everything |

### CLI Access

Access NoETL CLI inside the running container:

```bash
# Get help 
kubectl exec -it deployment/noetl -- noetl --help

# Register a playbook
kubectl exec -it deployment/noetl -- noetl register /path/to/playbook.yaml --host localhost --port 8082

# Run a playbook
kubectl exec -it deployment/noetl -- noetl run playbook-name --host localhost --port 8082

# List catalog
kubectl exec -it deployment/noetl -- noetl catalog list --host localhost --port 8082
```

### REST API Examples

```bash
# List all playbooks
curl http://localhost:30082/api/catalog/playbooks | jq .

# Execute a playbook  
curl -X POST http://localhost:30082/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{"playbook_id": "my-playbook"}'

# Check execution status
curl http://localhost:30082/api/executions/{execution_id} | jq .
```

### Sample Playbook

The platform test creates this example:

```yaml
name: hello-world-test
version: "1.0.0"
description: "Test playbook for NoETL platform"

steps:
  - name: test_step
    type: python
    parameters:
      code: |
        print(" NoETL Platform is working!")
        print(" Python step executed successfully") 
        return {"status": "success", "message": "Platform test completed"}
```

### Current Configuration

The NoETL deployment uses the `noetl-local-dev:latest` image built from local source code and runs on port 8082.

- **Deployment**: k8s/noetl/noetl-deployment.yaml  
- **Service**: k8s/noetl/noetl-service.yaml (NodePort 30082)
- **Health Endpoint**: http://localhost:30082/api/health

This is automatically configured by the `make k8s-platform-deploy` command or `./k8s/deploy-platform.sh` script.

### Accessing Postgres

To access the Postgres database from your local machine, you have two options:

1. **Using the port-forward script (Recommended)**:
   ```bash
   ./postgres-port-forward.sh
   ```
   This script automatically finds the Postgres pod and sets up port forwarding.

2. **Manual port forwarding**:
   ```bash
   kubectl port-forward pod/$(kubectl get pod -l app=postgres -o jsonpath="{.items[0].metadata.name}") 5432:5432
   ```

After setting up port forwarding, you can connect to Postgres using:
```bash
psql -h localhost -p 5432 -U demo -d demo_noetl
```

For more detailed instructions and alternative methods, see [Accessing Postgres in Kubernetes](docs/postgres_access.md).

##  Troubleshooting

### Common Issues and Solutions

| Issue | Symptoms | Solution |
|-------|----------|----------|
| **Pods not ready** | `0/1 Running` status | Check logs: `kubectl logs -l app=noetl` |
| **Health check fails** | CrashLoopBackOff | Verify endpoint: `curl localhost:30082/api/health` |
| **Database connection** | Connection errors in logs | Check Postgres: `kubectl get pods -n postgres` |
| **Permission denied** | Schema initialization fails | Clean schema: `make k8s-platform-clean` then redeploy |
| **Port conflicts** | Connection refused | Check Kind port mappings and ensure 30082 is free |

### Debugging Steps

1. **Check overall status**:
   ```bash
   make k8s-platform-status
   ```

2. **Inspect pod details**:
   ```bash
   kubectl describe pod -l app=noetl
   kubectl describe pod -l app=postgres -n postgres
   ```

3. **View logs**:
   ```bash
   # NoETL logs (follow)
   kubectl logs -l app=noetl -f
   
   # Postgres logs
   kubectl logs -l app=postgres -n postgres -f
   
   # Previous container logs (if crashed)
   kubectl logs -l app=noetl --previous
   ```

4. **Test database connectivity**:
   ```bash
   # Connect to Postgres directly
   kubectl exec -it deployment/postgres -n postgres -- psql -U demo -d demo_noetl -c "SELECT version();"
   
   # Test from NoETL container
   kubectl exec -it deployment/noetl -- /opt/noetl/.venv/bin/python -c "
   import psycopg2
   conn = psycopg2.connect(
       host='postgres.postgres.svc.cluster.local',
       port=5432,
       user='noetl',
       password='noetl', 
       database='demo_noetl'
   )
   print('Database connection successful!')
   conn.close()
   "
   ```

5. **Resource usage**:
   ```bash
   kubectl top pods
   kubectl top nodes
   ```

### Recovery Procedures

#### Complete Reset
```bash
make k8s-platform-clean
make k8s-platform-deploy
```

#### Database Only Reset  
```bash
kubectl delete deployment postgres -n postgres
kubectl delete pvc postgres-pvc -n postgres
kubectl delete pv postgres-pv
./k8s/deploy-platform.sh --no-cluster --no-noetl-pip
```

#### NoETL Only Reset
```bash
kubectl delete deployment noetl
kubectl apply -f k8s/noetl/noetl-deployment.yaml
```

### Deleting the Cluster

You can delete the cluster:

```bash
kind delete cluster --name noetl-cluster
```

## Additional Resources

- [Kind Documentation](https://kind.sigs.k8s.io/docs/user/quick-start/)
- [Kubernetes Documentation](https://kubernetes.io/docs/home/)
- [NoETL Documentation](https://noetl.io/docs)

# Postgres Redeployment Guide


## Recommended: Redeploy via deploy-platform.sh or kubectl

You can redeploy Postgres without special scripts:

- Rerun the platform script to (re)apply Postgres manifests:
  ```bash
  # Recreate cluster and redeploy everything
  ./k8s/deploy-platform.sh

  # Or reuse existing cluster and redeploy only Postgres
  ./k8s/deploy-platform.sh --no-cluster --no-noetl-pip
  ```
- Or do a simple rollout restart:
  ```bash
  kubectl rollout restart deployment/postgres
  ```

## Optional: Using the Redeployment Script

If you prefer a focused redeploy, you can still use the convenience script:

```bash
cd /path/to/noetl/k8s

chmod +x redeploy-postgres.sh

./redeploy-postgres.sh
```

## Manual Redeployment

to redeploy Postgres manually, follow these steps:

1. Delete the existing Postgres deployment:
   ```bash
   kubectl delete deployment postgres --ignore-not-found=true
   ```

2. Wait for the Postgres pods to terminate:
   ```bash
   kubectl wait --for=delete pod -l app=postgres --timeout=60s || true
   ```

3. Reapply the Postgres manifests:
   ```bash
   kubectl apply -f postgres/postgres-configmap.yaml
   kubectl apply -f postgres/postgres-config-files.yaml
   kubectl apply -f postgres/postgres-secret.yaml
   kubectl apply -f postgres/postgres-deployment.yaml
   ```

4. Wait for Postgres to be ready:
   ```bash
   kubectl wait --for=condition=ready pod -l app=postgres --timeout=180s
   ```

5. Verify the deployment:
   ```bash
   kubectl get pods -l app=postgres
   ```

## Troubleshooting

### Automated Troubleshooting

Use the verification script to automatically check for common issues:

```bash
chmod +x verify-postgres.sh

./verify-postgres.sh
```

### Manual Troubleshooting

If Postgres fails to start, follow these steps:

1. **Check pod status**:
   ```bash
   kubectl get pods -l app=postgres
   ```
   Look for status like `CrashLoopBackOff`, `Error`, or `ImagePullBackOff`.

2. **Check detailed pod information**:
   ```bash
   kubectl describe pod -l app=postgres
   ```
   Look for events and conditions that might indicate problems.

3. **Check container logs**:
   ```bash
   POSTGRES_POD=$(kubectl get pod -l app=postgres -o jsonpath="{.items[0].metadata.name}")
   
   kubectl logs $POSTGRES_POD
   ```

4. **Check if Postgres service is running**:
   ```bash
   kubectl get service postgres
   ```

### Common Issues and Solutions

1. **Permission problems**: 
   - Error: "root execution of the Postgres server is not permitted"
   - Solution: Ensure the security context in postgres-deployment.yaml is set to run as user 999 (postgres).
   ```yaml
   securityContext:
     runAsUser: 999
     runAsGroup: 999
   ```
   - Also ensure the pod-level fsGroup is set:
   ```yaml
   spec:
     securityContext:
       fsGroup: 999
   ```

2. **Volume mount issues**: 
   - Error: "could not create directory", "permission denied"
   - Solution: Check that the persistent volume is correctly mounted and has proper permissions.
   - Add a subPath to the volume mount to prevent permission issues:
   ```yaml
   volumeMounts:
     - name: postgres-storage
       mountPath: /var/lib/Postgres/data
       subPath: postgres-data
   ```

3. **Configuration errors**: 
   - Error: "could not read configuration file"
   - Solution: Verify the configmaps and secrets are correctly applied.
   ```bash
   kubectl get configmap postgres-config -o yaml
   kubectl get configmap postgres-config-files -o yaml
   ```

4. **Database initialization issues**:
   - Error: "database files are incompatible with server"
   - Solution: If you've changed Postgres versions, you may need to delete and recreate the PVC:
   ```bash
   kubectl delete pvc postgres-pvc
   kubectl apply -f postgres/postgres-pv.yaml
   ```
   - Warning: This will delete all existing data.

## Data Persistence

### Understanding Postgres Data Storage

Postgres stores its data in a persistent volume, which survives pod restarts and redeployments. Data remains intact when you:

- Restart the Postgres pod
- Update the Postgres deployment
- Redeploy Postgres with configuration changes
- Restart the Kubernetes cluster

The data is stored in the persistent volume claim (PVC) named `postgres-pvc`, which is bound to the persistent volume (PV) named `postgres-pv`.

### Backing Up Postgres Data Before Redeployment

It's always a good practice to back up data before redeployment:

```bash
POSTGRES_POD=$(kubectl get pod -l app=postgres -o jsonpath="{.items[0].metadata.name}")

kubectl exec $POSTGRES_POD -- pg_dump -U $POSTGRES_USER $POSTGRES_DB > postgres_backup.sql
```

### Deleting Postgres Data (When Necessary)

In some cases, you might need to delete the Postgres data and start fresh:

```bash
kubectl delete pvc postgres-pvc

kubectl apply -f postgres/postgres-pv.yaml
```

Situations when you might need to delete the data:
- When upgrading to a new major version of Postgres
- When the database is corrupted
- When you want to start with a clean database

### Restoring Postgres Data After Redeployment

If you need to restore data from a backup:

```bash
POSTGRES_POD=$(kubectl get pod -l app=postgres -o jsonpath="{.items[0].metadata.name}")

kubectl cp postgres_backup.sql $POSTGRES_POD:/tmp/

kubectl exec $POSTGRES_POD -- psql -U $POSTGRES_USER $POSTGRES_DB -f /tmp/postgres_backup.sql
```

### Best Practices for Data Persistence

1. **Regular backups**: Schedule regular backups of Postgres database
2. **Version compatibility**: Ensure Postgres version compatibility when upgrading
3. **Storage class**: Use an appropriate storage class for the environment
4. **Resource limits**: Set appropriate storage resource limits for the PVC
5. **Monitoring**: Monitor disk usage to prevent running out of space

# Postgres Deployment Troubleshooting Guide

## Issue
The Postgres pod is failing to start with a `CrashLoopBackOff` status. The logs show permission errors when trying to create the data directory:

```
mkdir: cannot create directory '/var/lib/Postgres/data/pgdata': Permission denied
```

## Root Cause
The issue is related to volume permissions in Kubernetes. When Postgres tries to initialize its data directory, it needs proper permissions on the mounted volume. There were two main problems:

1. The Postgres container runs as user `postgres` (UID 999), but the mounted volume doesn't have the correct permissions
2. There is a mismatch between the `PGDATA` environment variable and the volume mount configuration

## Solution
The issue should be fixed by implementing the following changes:

1. Added an `initContainer` to set up proper permissions on the volume before the Postgres container starts:
   ```yaml
   initContainers:
     - name: init-permissions
       image: busybox
       command: ["sh", "-c", "mkdir -p /data/pgdata && chmod 700 /data/pgdata && chown -R 999:999 /data"]
       volumeMounts:
         - name: postgres-storage
           mountPath: /data
   ```

2. Use a consistent `subPath` in the volume mount:
   ```yaml
   volumeMounts:
     - name: postgres-storage
       mountPath: /var/lib/Postgres/data
       subPath: pgdata
   ```

3. Verify the `PGDATA` environment variable matches the path with the subPath:
   ```yaml
   PGDATA: /var/lib/Postgres/data/pgdata
   ```

4. Maintain the security context settings:
   ```yaml
   securityContext:
     fsGroup: 999
   ```
   ```yaml
   securityContext:
     runAsUser: 999
     runAsGroup: 999
   ```

## Explanation
The `initContainer` runs before the main Postgres container and prepares the volume with the correct permissions. It creates the necessary directory structure and sets ownership to UID/GID 999 (postgres user).

The `subPath` in the volume mount helps isolate Postgres data in a subdirectory of the persistent volume, preventing conflicts with other files that might be in the volume.

The `PGDATA` environment variable tells Postgres where to store its data, and it must match the path that will be available inside the container after the volume is mounted with the subPath.

## Verification
After applying these changes, the Postgres pod successfully started and reached the `Running` state with `1/1` containers ready. The logs confirm that the "database system is ready to accept connections".

## Summary and Recommendations

The key to fixing the Postgres deployment is addressing the volume permissions issue through:

1. **Using an initContainer**: proper directory permissions are set before Postgres starts
2. **Consistent path configuration**: the PGDATA environment variable matches the volume mount with subPath
3. **Proper security context**: Setting the correct user, group, and fsGroup for Postgres

### Best Practices for Postgres on Kubernetes

1. Always use an initContainer to set up volume permissions when deploying Postgres
2. Use subPath for volume mounts to isolate Postgres data
3. Set proper security context at both pod and container level
4. Make sure environment variables and volume mounts are consistent
5. When troubleshooting, check the logs with `kubectl logs -l app=postgres`

### Next Steps

If you need to create the noetl user that appears in the logs, you can:

1. Connect to the Postgres pod:
   ```bash
   kubectl exec -it $(kubectl get pod -l app=postgres -o jsonpath="{.items[0].metadata.name}") -- bash
   ```

2. Create the user:
   ```bash
   psql -U demo -d demo_noetl -c "CREATE USER noetl WITH PASSWORD 'noetl' CREATEDB LOGIN;"
   ```

# NoETL Redeployment Guide

## Recommended: Redeploy via deploy-platform.sh or kubectl

You can redeploy NoETL without special scripts:

- Rerun the platform script to (re)apply NoETL manifests (pip version by default):
  ```bash
  # Recreate cluster and redeploy everything
  ./k8s/deploy-platform.sh

  # Or reuse existing cluster and redeploy only NoETL (pip)
  ./k8s/deploy-platform.sh --no-cluster --no-postgres
  ```
- Or do a simple rollout restart:
  ```bash
  kubectl rollout restart deployment/noetl
  ```

## Optional: Using the Redeployment Script

If you prefer a focused redeploy, you can still use the convenience script:

1. Navigate to the k8s directory:

```bash
cd /path/to/noetl/k8s
```

2. Make sure the script is executable:

```bash
chmod +x redeploy-noetl.sh
```

3. Run the script:

```bash
./redeploy-noetl.sh
```

The script will:
- Check if kubectl is installed and configured
- Remove the existing NoETL deployment
- Apply the NoETL manifests - configmap, secret, deployment, service
- Wait for the NoETL pods to be ready
- Display the status of the NoETL deployment

## Manual Redeployment

If you prefer to redeploy NoETL manually, follow these steps:

1. Delete the existing NoETL deployment:

```bash
kubectl delete deployment noetl --ignore-not-found=true
```

2. Wait for the NoETL pods to terminate:

```bash
kubectl wait --for=delete pod -l app=noetl --timeout=60s || true
```

3. Apply the NoETL manifests:

```bash
kubectl apply -f noetl/noetl-configmap.yaml
kubectl apply -f noetl/noetl-secret.yaml
kubectl apply -f noetl/noetl-deployment.yaml
kubectl apply -f noetl/noetl-service.yaml
```

4. Wait for the NoETL pods to be ready:

```bash
kubectl wait --for=condition=ready pod -l app=noetl --timeout=180s
```

5. Check the status of the NoETL deployment:

```bash
kubectl get pods -l app=noetl
```

## Troubleshooting

If you encounter issues during redeployment, check the logs of the NoETL pods:

```bash
kubectl logs -l app=noetl
```

For more detailed logs:

```bash
kubectl describe pod -l app=noetl
```

# NoETL Development Deployment Options

This document explains how to deploy NoETL in a Kubernetes environment using different installation methods, particularly for development purposes.

## Overview

Three deployment options are provided:

1. **Development Mode**: Mounts a local NoETL repository and installs it in editable mode, allowing live code changes
2. **Package Installation**: Installs NoETL from a locally built package file (tar.gz or wheel)
3. **Version-Specific**: Installs a specific version of NoETL from PyPI

## Prerequisites

- Kubernetes cluster (local or remote)
- kubectl installed and configured
- Access to the NoETL repository or package files

## Deployment Files

The following deployment files are available:

- `noetl-dev-deployment.yaml`: For development mode with a mounted repository
- `noetl-package-deployment.yaml`: For installing from a local package file
- `noetl-version-deployment.yaml`: For installing a specific version from PyPI

## Deployment Script

A deployment script `deploy-noetl-dev.sh` is provided to simplify the deployment process. The script supports all three deployment methods and handles the necessary Kubernetes resources.

### Usage

```bash
./deploy-noetl-dev.sh [options]
```

### Options

- `--type TYPE`: Deployment type: dev, package, version (default: dev)
- `--repo-path PATH`: Path to local NoETL repository (for dev type)
- `--package-path PATH`: Path to directory with NoETL package files (for package type)
- `--version VERSION`: NoETL version to install from PyPI (for version type)
- `--help`: Show help message

### Examples

#### Development Mode

```bash
# Deploy using the local repository
./deploy-noetl-dev.sh --type dev --repo-path /path/to/noetl

# Deploy using the default repository path (parent directory of script)
./deploy-noetl-dev.sh
```

#### Package Installation

```bash
# Deploy using a local package file
./deploy-noetl-dev.sh --type package --package-path /path/to/packages
```

#### Version-Specific

```bash
# Deploy a specific version from PyPI
./deploy-noetl-dev.sh --type version --version 0.1.24

# Deploy the latest version from PyPI
./deploy-noetl-dev.sh --type version
```

## Manual Deployment

If you prefer to deploy manually, you can use the following steps:

### Development Mode

1. Edit `noetl-dev-deployment.yaml` to set the correct path to the local NoETL repository
2. Apply the deployment:

```bash
kubectl apply -f noetl/noetl-configmap.yaml
kubectl apply -f noetl/noetl-secret.yaml
kubectl apply -f noetl/noetl-dev-deployment.yaml
kubectl apply -f noetl/noetl-service.yaml
```

## 🏗️ Architecture Overview

### Current Implementation

```
┌─────────────────────────────────────────────────────────────┐
│                    Kind Cluster                             │
│  ┌─────────────────┐    ┌─────────────────────────────────┐  │
│  │ Postgres NS     │    │ Default NS                      │  │
│  │                 │    │                                 │  │
│  │ ┌─────────────┐ │    │ ┌─────────────────────────────┐ │  │
│  │ │ Postgres    │ │    │ │ NoETL Server                │ │  │
│  │ │ Pod         │ │    │ │ - Image: noetl-local-dev    │ │  │
│  │ │             │ │    │ │ - Port: 8082                │ │  │
│  │ │ - DB: demo  │ │    │ │ - Health: /api/health       │ │  │  
│  │ │ - Schema:   │◄─────┤ │ - Direct uvicorn            │ │  │
│  │ │   noetl     │ │    │ │ - Auto DB init              │ │  │
│  │ └─────────────┘ │    │ └─────────────────────────────┘ │  │
│  └─────────────────┘    └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────┘
         │                           │
         │                           │ NodePort 30082
         │                           ▼
         │                  ┌─────────────────┐
         │                  │ localhost:30082 │
         │                  │ - /api/health   │
         │                  │ - /docs         │
         │                  │ - /api/*        │
         │                  └─────────────────┘
         │
    ┌────▼────────────────────────────────────────────────────┐
    │ Volume Mounts:                                          │
    │ - /opt/noetl/data (playbooks, data)                    │
    │ - /opt/noetl/logs (application logs)                   │
    │ - /mnt/data (postgres persistent storage)              │
    └─────────────────────────────────────────────────────────┘
```

### Key Design Decisions

- **Namespace Separation**: Postgres in `postgres` namespace for isolation
- **Local Development**: Uses `noetl-local-dev` image built from source  
- **Direct Execution**: Runs uvicorn directly, not through subprocess wrapper
- **Health Checks**: Uses correct `/api/health` endpoint
- **Auto-initialization**: Database schema created automatically on startup
- **Persistent Storage**: Postgres data persisted in Kind node filesystem

## 📚 Additional Resources

### Documentation
- [API Documentation](http://localhost:30082/docs) - Available after deployment
- [OpenAPI Specification](http://localhost:30082/openapi.json) - Machine-readable API spec

### Makefile Commands Summary
```bash
make k8s-platform-deploy  # Deploy complete platform
make k8s-platform-status  # Check status
make k8s-platform-test    # Test with sample playbook  
make k8s-platform-clean   # Clean up everything
make help                 # Show all available commands
```

### Quick Reference
- **Health Check**: `curl http://localhost:30082/api/health`
- **List Playbooks**: `curl http://localhost:30082/api/catalog/playbooks`
- **View Logs**: `kubectl logs -l app=noetl -f`
- **CLI Access**: `kubectl exec -it deployment/noetl -- noetl --help`
- **Cleanup**: `make k8s-platform-clean` or `kind delete cluster --name noetl-cluster`

---

🎉 **Your NoETL platform is ready for action!** 

For questions or issues, check the troubleshooting section above or examine the pod logs for detailed error information.


# Quick Health Check

To quickly check the status of the NoETL platform after deployment, use the helper script:

```bash
# Make the script executable (first time only)
chmod +x k8s/check-status.sh

# Run with defaults (namespace: default, waits for pods to be ready)
./k8s/check-status.sh

# Common options
./k8s/check-status.sh --namespace default           # specify namespace
./k8s/check-status.sh --no-wait                     # don't wait for readiness
./k8s/check-status.sh --url http://localhost:30082/health  # override URL
```

What it does:
- Shows pods and services for Postgres and NoETL
- Optionally waits for pods to become Ready
- Checks Postgres readiness using pg_isready inside the pod
- Tests the NoETL `/api/health` endpoint via NodePort

---

##  File Structure Reference

### Current Active Files
- **`deploy-platform.sh`** - Main deployment script
- **`postgres-namespace.yaml`** - Postgres namespace (ADDED)
- **`noetl-deployment.yaml`** - Uses `noetl-local-dev` image, direct uvicorn
- **`noetl-configmap.yaml`** - Environment configuration  
- **`noetl-secret.yaml`** - Sensitive configuration
- **`noetl-service.yaml`** - NodePort 30082 service

### Fixes Applied
-  **Namespace Creation**: Added `postgres-namespace.yaml`
-  **Health Endpoint**: Updated from `/health` to `/api/health` 
-  **Process Management**: Changed to direct uvicorn execution
-  **Volume Mounts**: Added logs directory support
-  **Database Schema**: Fixed type compatibility issues
-  **Image Selection**: Using `noetl-local-dev` vs `noetl-pip`

### Makefile Integration
- **`k8s-platform-deploy`** - Complete platform deployment
- **`k8s-platform-status`** - Status monitoring with health checks  
- **`k8s-platform-test`** - End-to-end testing with sample playbook
- **`k8s-platform-clean`** - Comprehensive cleanup
