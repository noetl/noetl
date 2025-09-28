# NoETL Port Configuration

## Overview

This document explains the port configuration for NoETL deployments in Kubernetes. 
It addresses the issue of port conflicts between different NoETL deployments and provides a solution to run them simultaneously without interference.

## Issue Description

The original configuration had both the standard NoETL deployment (`noetl-deployment.yaml`) and the development deployment (`noetl-dev-deployment.yaml`) using the same port (8080). This caused port conflicts when both deployments were running simultaneously, resulting in one of the deployments failing to start properly.

## Solution

The solution involves configuring the development deployment to use a different port than the standard deployment. Current port assignments are:

1. **Standard NoETL Deployment (pip image)**:
   - Container Port: 8082
   - Service Port: 8082
   - NodePort: 30082
   - Namespace: `noetl`

2. **Development NoETL Deployment (local-dev image)**:
   - Container Port: 8080
   - Service Port: 8080
   - NodePort: 30080
   - Namespace: `default`

## Configuration Files

### Standard NoETL Deployment

The standard NoETL deployment uses the following files:
- `noetl-deployment.yaml`: Defines the deployment with container port 8082
- `noetl-service.yaml`: Exposes the deployment on port 8082 with NodePort 30082
- `noetl-worker-deployments.yaml`: Defines the worker pools connecting to the server API
- `noetl/namespaces.yaml`: Creates the `noetl` server namespace and worker pool namespaces

### Development NoETL Deployment

The development NoETL deployment uses the following files:
- `noetl-dev-deployment.yaml`: Defines the deployment with container port 8080
- `noetl-dev-service.yaml`: Exposes the deployment on port 8080 with NodePort 30080

## Accessing the Deployments

You can access the deployments at the following URLs:

- Standard NoETL (pip): http://localhost:30082/health
- Development NoETL (local-dev): http://localhost:30080/api/health

## Deployment

To deploy both versions:

1. Deploy the standard NoETL:
   ```bash
   kubectl apply -f noetl/noetl-configmap.yaml
   kubectl apply -f noetl/noetl-secret.yaml
   kubectl apply -f noetl/noetl-deployment.yaml
   kubectl apply -f noetl/noetl-service.yaml
   kubectl apply -f noetl/noetl-worker-deployments.yaml
   ```

2. Deploy the development NoETL:
   ```bash
   kubectl apply -f noetl/noetl-configmap.yaml
   kubectl apply -f noetl/noetl-secret.yaml
   kubectl apply -f noetl/noetl-dev-deployment.yaml
   kubectl apply -f noetl/noetl-dev-service.yaml
   ```

## Validation

You can validate the port configuration using the provided test script:

```bash
./tests/test-noetl-dev-port.sh
```

This script checks for port conflicts between the deployments and services.

## Troubleshooting

If you encounter issues with the deployments:

1. Check if both services are running:
   ```bash
   kubectl get services | grep noetl
   ```

2. Check if both pods are running:
   ```bash
   kubectl get pods | grep noetl
   ```

3. Check the logs for any errors:
   ```bash
   kubectl logs -l app=noetl
   kubectl logs -l app=noetl-dev
   ```

4. Check the ports are not used by other services:
   ```bash
   kubectl get services --all-namespaces | grep -E '30080|30082'
   ```

   Note: Port 30082 is used for the NoETL server NodePort; 30080 is used for the local-dev deployment.
