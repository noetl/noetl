# Changelog

## [Unreleased] - Unified Kubernetes Deployment

### Added
- **Unified Kubernetes Deployment**: New deployment architecture that consolidates all NoETL components (server, workers, observability) into a single namespace
- **Integrated Observability**: Built-in Grafana, VictoriaMetrics, VictoriaLogs, and Vector monitoring stack
- **Simplified Management**: All components deployed and managed together
- **Build and Load Scripts**: Automated Docker image building and loading for Kind clusters
- **Port-Forward Management**: Automated port-forwarding setup for observability UIs

### Scripts Added
- `k8s/deploy-unified-platform.sh` - Main unified deployment script
- `k8s/generate-unified-noetl-deployment.sh` - Generates unified Kubernetes manifests
- `k8s/deploy-unified-observability.sh` - Deploys observability stack to unified namespace
- `k8s/build-and-load-images.sh` - Builds and loads Docker images into Kind cluster
- `k8s/cleanup-old-deployments.sh` - Cleans up legacy separate deployments

### Documentation Added
- `docs/unified_deployment.md` - Comprehensive unified deployment guide
- `k8s/UNIFIED_DEPLOYMENT.md` - Quick reference for unified deployment
- Updated `docs/installation.md` with Kubernetes installation option
- Updated `docs/kind_kubernetes.md` with unified deployment examples
- Updated `k8s/README.md` with unified vs legacy deployment comparison

### Benefits
- **Simplified Architecture**: Single namespace (`noetl-platform`) instead of 5 separate namespaces
- **Better Performance**: Direct service-to-service communication without cross-namespace networking
- **Unified Monitoring**: All components automatically monitored in one dashboard
- **Easier Troubleshooting**: Everything in one location
- **Resource Efficiency**: Reduced Kubernetes overhead

### Migration
- Use `./k8s/cleanup-old-deployments.sh` to migrate from legacy separate namespace deployment
- Maintains API compatibility with existing clients
- PostgreSQL remains in separate `postgres` namespace for data persistence

## [0.1.26] (2025-07-17)

Changes Made:
1. Updated noetl/main.py
Added a --no-ui flag to the server command
Modified the create_app() function to support UI enable/disable through a global variable
Added support for the NOETL_ENABLE_UI environment variable (defaults to "true")
The server now logs whether UI is enabled or disabled on startup
2. Updated Docker Configuration
Modified docker/noetl/development/Dockerfile to use the new CLI structure
Added NOETL_ENABLE_UI=true environment variable
Updated the CMD to use the new server command format
3. Enhanced scripts/build_ui.sh
Added --with-server option to start both UI and NoETL server together
Added new dev-with-server mode
Updated usage documentation to include the new options
How to Use:
Running the Server:
With UI (default):
python -m noetl.main server --host 0.0.0.0 --port 8080
Without UI:
python -m noetl.main server --host 0.0.0.0 --port 8080 --no-ui
Using environment variable:
NOETL_ENABLE_UI=false python -m noetl.main server --host 0.0.0.0 --port 8080
Building and Running UI:
Build UI for production:
./scripts/build_ui.sh -p 8080
Start UI development server with NoETL server:
./scripts/build_ui.sh --with-server -p 8080
Start UI development server (expects external NoETL server):
./scripts/build_ui.sh -m dev -p 8080
Docker Usage:
With UI (default):
docker run -p 8080:8080 noetl:latest
Without UI:
docker run -e NOETL_ENABLE_UI=false -p 8080:8080 noetl:latest
Key Features:
Backward Compatibility: Default behavior remains unchanged (UI enabled)
Environment Variable Support: Can be controlled via NOETL_ENABLE_UI
CLI Flag: --no-ui flag for explicit UI disabling
Docker Support: Environment variable works in containerized environments
Development Integration: Build script can start both servers together
Proper Logging: Clear indication of UI status on server startup
The implementation allows for flexible deployment scenarios where you can run the NoETL server as an API-only service or with the full UI depending on your needs.

## [0.1.18] (2025-06-29)

### Features

* **packaging**: Include UI components, static files and templates, in the package distribution
* **packaging**: Add package metadata including classifiers, keywords, and project URLs
* **packaging**: Update pyproject.toml with packaging standards
* **packaging**: Create ui package with __init__.py for UI components inclusion
* **packaging**: Add MANIFEST.in for file inclusion in distribution
* **packaging**: all CSS, JS, and HTML template files are bundled with the package

### Changed

* **version**: Bump version from 0.1.17 to 0.1.18
* **packaging**: Modernize setup.py with metadata and package data configuration
* **structure**: Make ui folder and Python package for distribution

### Removed

* **packaging**: Remove obsolete migration references from package configuration

## [0.1.0](https://github.com/noetl/noetl/compare/v0.0.1...v0.1.0) (2023-12-20)


### Features

* Add Semantic release SWP-98 ([2ac157e](https://github.com/noetl/noetl/commit/2ac157eb76ba43c974c604c235edf3e6caa7f931))
