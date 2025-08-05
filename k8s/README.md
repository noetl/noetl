# NoETL Kubernetes Deployment with Kind

Set up a local Kubernetes cluster using Kind (Kubernetes in Docker) and deploy NoETL and Postgres to it.

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

Once the deployments are ready, you can access the NoETL application:

- NoETL Web UI: http://localhost:30080
- NoETL API: http://localhost:30080/api

## Troubleshooting

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


## Option 1: Using the Redeployment Script

The easiest way to redeploy Postgres is to use the provided script:

```bash
cd /path/to/noetl/k8s

chmod +x redeploy-postgres.sh

./redeploy-postgres.sh
```

## Option 2: Manual Redeployment

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

1. **Regular backups**: Schedule regular backups of your Postgres database
2. **Version compatibility**: Ensure Postgres version compatibility when upgrading
3. **Storage class**: Use an appropriate storage class for your environment
4. **Resource limits**: Set appropriate storage resource limits for your PVC
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

## Option 1: Using the Redeployment Script

The easiest way to redeploy NoETL is to use the provided script:

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

## Option 2: Manual Redeployment

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
