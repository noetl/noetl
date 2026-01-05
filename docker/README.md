# NoETL Docker Images

This directory contains Dockerfiles and scripts for building and deploying NoETL using Docker.

## Docker Images

Two NoETL images are supported:

1. noetl-pip:latest — PyPI-based (pip-version) image for production-like usage
2. noetl-local-dev:latest — Local-path build for development and testing

Additionally:
- postgres-noetl:latest — PostgreSQL image with NoETL-specific configuration

### Rust CLI Integration

All NoETL images now include the `noetl` Rust CLI binary built via a multi-stage Docker build:

**Build Stages:**
1. **ui-builder** (node:20-alpine) - Builds the web UI
2. **rust-builder** (rust:1.83-slim) - Compiles the `noetl` Rust CLI binary
3. **python builder** - Installs Python dependencies with uv
4. **Production** - Final image with Python runtime + noetl binary

The Rust CLI (`/usr/local/bin/noetl`) provides unified management for:
- Server lifecycle: `noetl server start/stop`
- Worker lifecycle: `noetl worker start/stop`
- Database management: `noetl db init/validate`
- Build automation: `noetl build [--no-cache]`
- K8s deployment: `noetl k8s deploy|remove|redeploy|reset`

Kubernetes deployments use the Rust CLI:
- Server: `command: ["noetl"], args: ["server", "start"]`
- Worker: `command: ["noetl"], args: ["worker", "start"]`

## Building the Images

### Using Rust CLI (Recommended)

The `noetl` Rust CLI provides integrated build and deployment:

```bash
# Build with automatic timestamp tagging
./bin/noetl build

# Build without cache
./bin/noetl build --no-cache

# Deploy to kind cluster (includes kind load)
./bin/noetl k8s deploy

# Rebuild and redeploy
./bin/noetl k8s redeploy [--no-cache]
```

The Rust CLI automatically:
- Generates timestamp-based tags (YYYY-MM-DD-HH-MM)
- Saves tag to `.noetl_last_build_tag.txt`
- Loads images into kind cluster
- Updates deployment manifests with correct image references

### Using Build Script (Legacy)

Alternatively, use the build script at the repo root:

```bash
./docker/build-images.sh
```

Options:
- --no-pip: Skip building the pip-version (PyPI) image
- --no-local-dev: Skip building the local-dev (local path) image
- --no-postgres: Skip building the PostgreSQL image
- --push: Push images to a registry
- --registry REGISTRY: Registry to push images to (e.g., 'localhost:5000/')
- --tag TAG: Tag for the images (default: latest)
- --plain: Show detailed docker build steps (enables BuildKit plain progress)

Examples:
- Build only local-dev image and push to a local registry:
```bash
./docker/build-images.sh --no-pip --push --registry localhost:5000/ --tag dev
```

## Dockerfile Locations

In use (do not delete):
- docker/noetl/pip/Dockerfile — pip-version image (from PyPI)
- docker/noetl/dev/Dockerfile — local-dev image (from local path, includes Rust CLI build)
- docker/postgres/Dockerfile — Postgres image
- docker/jupyter/Dockerfile — used by docker-compose jupyter service

Rust CLI source:
- noetlctl/src/main.rs — Rust CLI implementation (compiled in rust-builder stage)
- noetlctl/Cargo.toml — Rust dependencies and build configuration

Not used by current build scripts or K8s deploys (safe to remove):
- k8s/noetl/Dockerfile
- k8s/noetl/Dockerfile.dev
- k8s/noetl/Dockerfile.main

Notes:
- The official build script (docker/build-images.sh) only uses the Dockerfiles under docker/.
- Kubernetes manifests consume the images built from docker/; the k8s/noetl Dockerfiles are historical and not referenced anywhere in scripts.

## Deploying to Kubernetes

See the main README.md and ci/README.md for Kubernetes deployment documentation. In short:
- noetl-deployment.yaml uses noetl-pip:latest (port 8084)
- noetl-dev-deployment.yaml uses noetl-local-dev:latest (port 8080)

## Running Locally

Docker Compose is configured to use these images. Common services:
- database (postgres-noetl)
- local-dev (noetl-local-dev) at http://localhost:8080
- pip-api (noetl-pip) at http://localhost:8084

## Troubleshooting

- The pip image uses a minimal build context (docker/noetl/pip), so it should start showing steps quickly. Longer initial delays typically affect local-dev or postgres builds that use the repository as build context.
- If a build seems stuck after "Building ...", Docker is likely transferring the build context. Ensure a .dockerignore exists at the repo root to exclude large folders (e.g., data/, dist/, .git/, notebooks/, .venv/). Re-run with --plain to see step-by-step progress.
- Verify images exist: docker images
- Check container logs: docker logs <container_id>
- If using Kind, load images: ./k8s/load-images.sh