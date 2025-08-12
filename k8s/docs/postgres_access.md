# Accessing Postgres in Kubernetes from a Local Machine

This document explains how to access the Postgres database running in Kubernetes from a local machine.

## Method 1: Using kubectl port-forward

The simplest and most secure way to access Postgres is using `kubectl port-forward`. This creates a temporary connection that forwards a local port to the Postgres pod in the cluster.

### Steps:

1. **Find the Postgres pod name**:
   ```bash
   kubectl get pods | grep postgres
   ```
   This will return something like:
   ```
   postgres-5d8b4b74d9-x7z9f   1/1     Running   0          3h
   ```

2. **Start port forwarding**:
   ```bash
   kubectl port-forward pod/postgres-5d8b4b74d9-x7z9f 5432:5432
   ```
   This forwards local port 5432 to port 5432 on the Postgres pod.

3. **Connect to Postgres** from a local machine:
   ```bash
   psql -h localhost -p 5432 -U demo -d demo_noetl
   ```
   When prompted for a password, enter: `demo`

4. **To stop port forwarding**, press `Ctrl+C` in the terminal where port-forward is running.

## Method 2: Modifying the Postgres Service (Alternative)

If you need persistent access to Postgres from outside the cluster, you can modify the service to use NodePort instead of ClusterIP.

> **Note**: This approach exposes Postgres more broadly and should be used with caution, especially in production environments.

### Steps:

1. **Edit the Postgres service**:
   ```bash
   kubectl edit service postgres
   ```
   
   Change `type: ClusterIP` to `type: NodePort` and add a `nodePort` field:
   ```yaml
   spec:
     type: NodePort
     ports:
       - port: 5432
         targetPort: 5432
         nodePort: 30543  # Choose an available port between 30000-32767
         protocol: TCP
         name: postgres
   ```

2. **Apply the changes**:
   ```bash
   kubectl apply -f k8s/postgres/postgres-service.yaml
   ```

3. **Connect to Postgres** from a local machine:
   ```bash
   psql -h localhost -p 30543 -U demo -d demo_noetl
   ```
   When prompted for a password, enter: `demo`

## Security Considerations

- The port-forward method is more secure as it only exposes the database temporarily and doesn't require changing the service configuration.
- If using NodePort, consider implementing additional security measures like:
  - Network policies to restrict access
  - Strong passwords
  - SSL/TLS encryption for connections

## Troubleshooting

If you encounter connection issues:

1. **Check if the Postgres pod is running**:
   ```bash
   kubectl get pods | grep postgres
   ```

2. **Check Postgres logs**:
   ```bash
   kubectl logs -l app=postgres
   ```

3. **Verify port forwarding is active**:
   ```bash
   netstat -an | grep 5432
   ```

4. **Test connection within the cluster**:
   ```bash
   kubectl exec -it $(kubectl get pod -l app=postgres -o jsonpath="{.items[0].metadata.name}") -- psql -U demo -d demo_noetl
   ```