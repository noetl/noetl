# Separated Build Workflow

## Overview
The build system has been split into separate scripts for NoETL and PostgreSQL components to optimize development velocity. This allows developers to rebuild only the components that have changed, avoiding unnecessary PostgreSQL rebuilds during NoETL code iterations.

## New Scripts

### Docker Build Scripts

#### `docker/build-noetl-images.sh`
- **Purpose**: Build only NoETL images (pip and local-dev variants)
- **Use Case**: Frequent NoETL code changes and iterations
- **Options**:
  - `--no-pip`: Skip building NoETL pip-version (PyPI) image
  - `--no-local-dev`: Skip building NoETL local-dev (local path) image
  - `--push`: Push images to registry
  - `--registry REGISTRY`: Registry to push images to
  - `--tag TAG`: Tag for the images (default: latest)
  - `--plain`: Show detailed docker build steps

#### `docker/build-postgres-image.sh`
- **Purpose**: Build PostgreSQL image with NoETL schema independently
- **Use Case**: Infrequent PostgreSQL/schema updates
- **Options**:
  - `--push`: Push image to registry
  - `--registry REGISTRY`: Registry to push image to
  - `--tag TAG`: Tag for the image (default: latest)
  - `--plain`: Show detailed docker build steps

### Kubernetes Image Loading Scripts

#### `k8s/load-noetl-images.sh`
- **Purpose**: Load only NoETL images into Kind cluster
- **Use Case**: Rapid deployment iteration during NoETL development
- **Options**:
  - `--cluster-name NAME`: Name of the Kind cluster (default: noetl-cluster)
  - `--no-pip`: Skip loading noetl-pip image
  - `--no-local-dev`: Skip loading noetl-local-dev image

#### `k8s/load-postgres-image.sh`
- **Purpose**: Load PostgreSQL image independently
- **Use Case**: When schema updates occur or PostgreSQL configuration changes
- **Options**:
  - `--cluster-name NAME`: Name of the Kind cluster (default: noetl-cluster)

## Updated Main Scripts

### `k8s/redeploy-noetl.sh`
The main redeployment script now uses the separated build and load scripts:
- Uses `docker/build-noetl-images.sh` in the `rebuild_images()` function
- Uses `k8s/load-noetl-images.sh` in the `load_images_to_kind()` function
- Preserves all existing functionality while optimizing build efficiency

## Development Workflows

### Typical NoETL Development Cycle
```bash
# 1. Build only NoETL images
./docker/build-noetl-images.sh

# 2. Load only NoETL images to Kind
./k8s/load-noetl-images.sh

# 3. Restart NoETL deployments (PostgreSQL remains untouched)
kubectl rollout restart -n noetl deployment/noetl-server
kubectl rollout restart -n noetl deployment/noetl-worker
```

### PostgreSQL Schema Updates
```bash
# 1. Build PostgreSQL image (when schema changes)
./docker/build-postgres-image.sh

# 2. Load PostgreSQL image to Kind
./k8s/load-postgres-image.sh

# 3. Restart PostgreSQL deployment
kubectl rollout restart -n postgres deployment/postgres
```

### Full Redeployment (Unchanged)
```bash
# Uses separated scripts internally for efficiency
./k8s/redeploy-noetl.sh
```

## Benefits

1. **Faster Development Cycles**: No need to rebuild PostgreSQL image for NoETL code changes
2. **Resource Efficiency**: Smaller build contexts and faster build times
3. **Selective Updates**: Build and load only what has changed
4. **Backward Compatibility**: Main redeployment script remains unchanged for full deployments
5. **Flexibility**: Can build and load components independently as needed

## Migration from Old Scripts

The old monolithic scripts (`docker/build-images.sh` and `k8s/load-images.sh`) are still available for compatibility, but the new separated scripts provide better efficiency for development workflows.

To use the old workflow:
```bash
./docker/build-images.sh
./k8s/load-images.sh
```

To use the new optimized workflow:
```bash
# For NoETL changes only
./docker/build-noetl-images.sh
./k8s/load-noetl-images.sh

# For PostgreSQL changes only
./docker/build-postgres-image.sh
./k8s/load-postgres-image.sh
```