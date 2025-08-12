# NoETL Kubernetes Deployment with Kind

Set up a local Kubernetes cluster using Kind (Kubernetes in Docker) and deploy NoETL and Postgres to it.

Note on deployment options:
- Pip deployment (PyPI-based): use these manifests
  - k8s/noetl/noetl-deployment.yaml (uses image noetl-pip:latest, container port 8084)
  - k8s/noetl/noetl-service.yaml (NodePort 30084; health at http://localhost:30084/api/health)
- Local development (from local path): use these manifests
  - k8s/noetl/noetl-dev-deployment.yaml (uses image noetl-local-dev:latest, container port 8080)
  - k8s/noetl/noetl-dev-service.yaml (NodePort 30082; health at http://localhost:30082/api/health)

For the up-to-date, concise guide, see k8s/docs/README.md.

## Prerequisites

- Docker installed and running
- kubectl installed
- Internet connection to pull container images

## Installing Kind

Kind="Kubernetes IN Docker", is a tool for running local Kubernetes clusters using Docker container nodes.

### macOS

Using Homebrew:
```bash
brew install kind
```

Using binary download:
```bash
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-darwin-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind
```

### Linux

Using binary download:
```bash
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind
```

### Windows

Using Chocolatey:
```powershell
choco install kind
```

Using binary download:
```powershell
curl.exe -Lo kind-windows-amd64.exe https://kind.sigs.k8s.io/dl/v0.20.0/kind-windows-amd64
Move-Item .\kind-windows-amd64.exe c:\some-dir-in-your-PATH\kind.exe
```

## Creating a Local Kubernetes Cluster

1. Create a Kind configuration file:

```bash
cat > kind-config.yaml << EOF
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  extraPortMappings:
  - containerPort: 30080
    hostPort: 30080
    protocol: TCP
EOF
```

2. Create the cluster:

```bash
kind create cluster --name noetl-cluster --config kind-config.yaml
```

3. Verify the cluster is running:

```bash
kubectl cluster-info --context kind-noetl-cluster
```

## Deploying NoETL and Postgres

### Option 1: Using the All-in-One Deployment Script

The easiest way to deploy the complete NoETL platform is to use the provided `deploy-platform.sh` script:

```bash
# Make the script executable
chmod +x k8s/deploy-platform.sh

# Run the script with default options (sets up cluster, deploys Postgres and NoETL from pip)
./k8s/deploy-platform.sh
```

The script supports various deployment options:

```bash
# Deploy everything supported (cluster, Postgres, NoETL from pip by default, plus local-dev)
./k8s/deploy-platform.sh --deploy-noetl-dev

# Skip cluster setup (if you already have a cluster)
./k8s/deploy-platform.sh --no-cluster

# Deploy only NoETL from local-dev (GitHub/local path)
./k8s/deploy-platform.sh --no-cluster --no-postgres --no-noetl-pip --deploy-noetl-dev

# Specify a custom repository path for local-dev
./k8s/deploy-platform.sh --repo-path /path/to/your/noetl/repo --deploy-noetl-dev
```

Note on images:
- The deploy-platform.sh script automatically builds required Docker images (Postgres, noetl-pip, and noetl-local-dev) using docker/build-images.sh and, when running against a Kind cluster, loads them into the cluster with k8s/load-images.sh. You do not need to run docker/build-images.sh manually before running the script (including when using --deploy-noetl-dev).
- If you want to skip the all-in-one helper and do things manually, see Option 2 below.

For more options, run:
```bash
./k8s/deploy-platform.sh --help
```

### Option 2: Manual Deployment

If you prefer to deploy components manually:

1. Create the necessary directories for persistent volumes:

```bash
docker exec -it noetl-cluster-control-plane mkdir -p /mnt/data
```

2. Apply the Kubernetes manifests:

```bash
kubectl apply -f k8s/postgres/postgres-pv.yaml
kubectl apply -f k8s/postgres/postgres-configmap.yaml
kubectl apply -f k8s/postgres/postgres-config-files.yaml
kubectl apply -f k8s/postgres/postgres-secret.yaml
kubectl apply -f k8s/postgres/postgres-deployment.yaml
kubectl apply -f k8s/postgres/postgres-service.yaml

kubectl wait --for=condition=ready pod -l app=postgres --timeout=120s

kubectl apply -f k8s/noetl/noetl-configmap.yaml
kubectl apply -f k8s/noetl/noetl-secret.yaml
kubectl apply -f k8s/noetl/noetl-deployment.yaml
kubectl apply -f k8s/noetl/noetl-service.yaml
```

3. Verify the deployments:

```bash
kubectl get pods
kubectl get services
```

## Accessing the Application

Once the deployments are ready, you can access NoETL via the following services:

- NoETL (pip):
  - UI: http://localhost:30084
  - API: http://localhost:30084/api
  - Health: http://localhost:30084/api/health
- NoETL (local-dev):
  - UI: http://localhost:30082
  - API: http://localhost:30082/api
  - Health: http://localhost:30082/api/health

### Kubernetes Dashboard

The Kubernetes Dashboard is a web-based UI for managing your Kubernetes cluster.

Important: It is not installed by default by our scripts or manifests. If you see a 404 like services "kubernetes-dashboard" not found, you need to install the Dashboard first.

Quick install (see docs for details and latest version):
```bash
kubectl apply -f https://raw.githubusercontent.com/kubernetes/dashboard/v2.7.0/aio/deploy/recommended.yaml
```

After installing, start the proxy and open the UI:
1. Start the Kubernetes proxy:
   ```bash
   kubectl proxy
   ```
2. Access the Dashboard at:
   ```
   http://localhost:8001/api/v1/namespaces/kubernetes-dashboard/services/https:kubernetes-dashboard:/proxy/
   ```

For installation steps, authentication, and token retrieval, see [Kubernetes Dashboard Documentation](docs/kubernetes_dashboard.md).

### Local Development

The supported development option is the local-dev deployment, which runs the noetl-local-dev:latest image and targets port 8080.

- Deployment: k8s/noetl/noetl-dev-deployment.yaml
- Service: k8s/noetl/noetl-dev-service.yaml (NodePort 30082; health at http://localhost:30082/api/health)

To deploy via the script:

```bash
./k8s/deploy-platform.sh --deploy-noetl-dev
```

To deploy manually:

```bash
kubectl apply -f k8s/noetl/noetl-configmap.yaml
kubectl apply -f k8s/noetl/noetl-secret.yaml
kubectl apply -f k8s/noetl/noetl-dev-deployment.yaml
kubectl apply -f k8s/noetl/noetl-dev-service.yaml
```

Note: The previous reload-based development flow is deprecated and no longer supported.

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

## Troubleshooting

### Resource Requirements

NoETL components, especially the development versions, require sufficient resources to function properly. If pods are failing with OOM errors (exit code 137), you may need to increase the memory limits.

For detailed information about resource requirements and troubleshooting, see [Resource Requirements Documentation](docs/resource_requirements.md).

### Checking Logs

To check logs for the NoETL application:

```bash
kubectl logs -l app=noetl
```

To check logs for Postgres:

```bash
kubectl logs -l app=postgres
```

### Restarting Deployments

If you need to restart a deployment:

```bash
kubectl rollout restart deployment/noetl
kubectl rollout restart deployment/postgres
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

### Package Installation

1. Build the NoETL package:

```bash
cd /path/to/noetl
python -m build
```

2. Edit `noetl-package-deployment.yaml` to set the correct path to the package directory
3. Apply the deployment:

```bash
kubectl apply -f noetl/noetl-configmap.yaml
kubectl apply -f noetl/noetl-secret.yaml
kubectl apply -f noetl/noetl-package-deployment.yaml
kubectl apply -f noetl/noetl-service.yaml
```

### Version-Specific

1. Edit `noetl-version-deployment.yaml` to set the desired version
2. Apply the deployment:

```bash
kubectl apply -f noetl/noetl-configmap.yaml
kubectl apply -f noetl/noetl-secret.yaml
kubectl apply -f noetl/noetl-version-deployment.yaml
kubectl apply -f noetl/noetl-service.yaml
```

## How It Works

### Development Mode

The development mode deployment mounts the local NoETL repository into the container and installs it in editable mode using `pip install -e`. This allows you to make changes to the code and see them reflected in the running application without rebuilding the container.

Key components:
- Volume mount for the repository: `mountPath: /opt/noetl/repo`
- Installation command: `pip install --user -e /opt/noetl/repo`

### Package Installation

The package installation deployment mounts a directory containing NoETL package files (tar.gz or wheel) and installs the package using pip. This is useful for testing built packages before publishing them.

Key components:
- Volume mount for the package directory: `mountPath: /opt/noetl/package`
- Installation command: `pip install --user /opt/noetl/package/noetl-*.tar.gz`

### Version-Specific

The version-specific deployment installs a specific version of NoETL from PyPI. This is useful for testing specific versions without building packages locally.

Key components:
- Environment variable for version: `NOETL_VERSION`
- Installation command: `pip install --user noetl==${NOETL_VERSION}`

## Troubleshooting

### Pod Fails to Start

If the pod fails to start, check the logs:

```bash
kubectl logs -l app=noetl-dev
```

Common issues:
- Repository path not accessible
- Package file not found
- Version not available on PyPI

### Permission Issues

If you encounter permission issues, ensure that:
- The repository directory is readable by the container
- The package directory is readable by the container
- The user in the container has permission to install packages

### Service Not Accessible

If the service is not accessible, check the service status:

```bash
kubectl get service noetl
```

Ensure that:
- The service is running
- The service is of the correct type (NodePort, LoadBalancer, etc.)
- The service is targeting the correct pods
- If using Kind locally, the Kind config maps the NodePort to the host. For NoETL pip on port 30084, include in extraPortMappings:
  - containerPort: 30084 / hostPort: 30084 / protocol: TCP, then recreate the cluster.


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
./k8s/check-status.sh --url http://localhost:30084/api/health  # override URL
```

What it does:
- Shows pods and services for Postgres and NoETL
- Optionally waits for pods to become Ready
- Checks Postgres readiness using pg_isready inside the pod
- Curls the NoETL /api/health endpoint via the Service NodePort

Expected success URL (default):
- NoETL (pip): http://localhost:30084/api/health

If a check fails, the script exits with non-zero status and prints details to help with troubleshooting.



## Deprecated and Safe-to-Remove Files (Reload flow)

Only two Kubernetes deployment options are supported now: pip (noetl-pip) and local-dev (noetl-local-dev). The previous reload-based development flow is deprecated and no longer used by any script or doc path. You can safely remove the following files from k8s/:

- k8s/deploy-noetl-reload.sh
- k8s/noetl/noetl-reload-deployment.yaml
- k8s/noetl/noetl-reload-service.yaml
- k8s/noetl/Dockerfile.reload
- k8s/tests/test-reload-setup.sh
- k8s/docs/noetl_reload_feature.md
- k8s/docs/noetl_reload_flag_fix_summary.md
- k8s/docs/noetl_reload_path_fix.md
- k8s/docs/kind_hostpath_mounting.md
- k8s/docs/kind_hostpath_fix_summary.md
- k8s/kind-config-with-mounts.yaml
- k8s/noetl/kind-config-mounts.yaml

Notes:
- These Kind config files with extraMounts were only useful for the deprecated reload flow (mounting the repo into the Kind node). They are not used by the supported pip/local-dev workflows. If you ever need a custom Kind config, generate it on the fly as needed (deploy-platform.sh does this), or use setup-kind-cluster.sh which writes a temporary config.
- The basic Kind config files still include port mappings like 30080–30084; this is harmless. Keep them if you want flexibility, or simplify later.
- If you rely on any custom workflow that used the reload path, prefer the local-dev deployment instead (k8s/noetl/noetl-dev-*.yaml).
