# NoETL Kubernetes Resource Requirements

This document outlines the resource requirements for running NoETL components in a Kubernetes environment.

## Overview

NoETL components, especially during installation and startup, require sufficient resources to function properly. Insufficient resources can lead to pods being terminated with OOM (Out of Memory) errors, which manifest as exit code 137 in pod logs.

## Resource Requirements

| Component | CPU Request | Memory Request | CPU Limit | Memory Limit | Notes |
|-----------|-------------|----------------|-----------|--------------|-------|
| postgres  | 0.5         | 512Mi          | 1         | 1Gi          | Database server |
| noetl     | 0.5         | 512Mi          | 1         | 1Gi          | Standard NoETL installation |
| noetl-dev | 0.5         | 512Mi          | 2         | 3Gi          | Development (local-dev) |

## Memory Considerations

### Why 3Gi for Development Pods?

The development pod (noetl-dev) requires significantly more memory than the standard NoETL installation because:

1. It installs NoETL in development mode (`pip install -e`)
2. It installs additional development dependencies 
3. Git operations during setup can be memory-intensive
4. The installation process for all dependencies can consume over 2Gi of memory

Testing has shown that 2Gi is insufficient and leads to OOM (Out of Memory) errors during the installation process. 3Gi provides enough headroom for the installation and operation of these development pods.

### Signs of Insufficient Memory

If you see any of the following, it may indicate insufficient memory:

- Pods terminating with exit code 137
- Pods in CrashLoopBackOff status
- Logs showing "Killed" messages
- Kubernetes events showing "OOMKilled"

## CPU Considerations

The CPU limits are set to ensure that:

1. Pods have enough CPU during installation and startup
2. Development pods have additional CPU for development tasks
3. No single pod can consume all available CPU on a node

## Adjusting Resource Requirements

If you need to adjust the resource requirements, you can modify the deployment YAML files:

```yaml
resources:
  limits:
    cpu: "2"
    memory: "2Gi"
  requests:
    cpu: "0.5"
    memory: "512Mi"
```

### Considerations for Different Environments

- **Development**: The default settings should be sufficient for most development work
- **Production**: Consider increasing both requests and limits based on expected load
- **Resource-Constrained Environments**: If running on a resource-constrained system, you may need to:
  - Reduce the number of concurrent deployments
  - Deploy components one at a time
  - Increase the available resources to the Kubernetes cluster

## Monitoring Resource Usage

To monitor resource usage:

```bash
# Get resource usage for all pods
kubectl top pods

# Get resource usage for a specific pod
kubectl top pod <pod-name>

# Get resource usage for nodes
kubectl top nodes
```

## Troubleshooting

If pods are still failing with resource issues:

1. Check if the Kubernetes cluster has enough resources available
2. Consider using a more powerful machine for a Kubernetes cluster
3. Deploy fewer components simultaneously
4. Check for memory leaks in custom code
5. Review logs for specific errors related to resource usage

```bash
# Check pod status
kubectl get pods

# Check pod details
kubectl describe pod <pod-name>

# Check pod logs
kubectl logs <pod-name>
```