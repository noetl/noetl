# Kubernetes Docs

This folder contains guidance for deploying NoETL to Kubernetes.

Supported images and two deployment options:
- noetl-pip: PyPI-based (pip-version) image for production-like usage.
- noetl-local-dev: Local-path build for development and testing.

Key files and scripts:
- docker/build-images.sh: builds both images with flags: --no-pip, --no-local-dev, --no-postgres, --tag, --registry, --push
- k8s/load-images.sh: loads images into a Kind cluster, flags: --no-pip, --no-local-dev, --no-postgres, --cluster-name
- k8s/noetl/noetl-deployment.yaml: deployment that uses the noetl-pip image, port 8084, NodePort 30084
- k8s/noetl/noetl-service.yaml: service for the pip deployment
- k8s/noetl/noetl-dev-deployment.yaml: deployment that uses the noetl-local-dev image on port 8080
- k8s/noetl/noetl-dev-service.yaml: service for the local-dev deployment (NodePort 30082)
- k8s/deploy-platform.sh: optional helper to provision a Kind cluster, build and load images, and apply manifests

Quick start (Kind):
1) Build images locally
   ./docker/build-images.sh

2) Create/load a Kind cluster and load images
   kind create cluster --name noetl-cluster
   ./k8s/load-images.sh --cluster-name noetl-cluster

3) Apply one of the deployments
   # pip-version (PyPI)
   kubectl apply -f k8s/noetl/noetl-configmap.yaml
   kubectl apply -f k8s/noetl/noetl-secret.yaml
   kubectl apply -f k8s/noetl/noetl-deployment.yaml
   kubectl apply -f k8s/noetl/noetl-service.yaml

   # OR local-dev (from local path)
   kubectl apply -f k8s/noetl/noetl-configmap.yaml
   kubectl apply -f k8s/noetl/noetl-secret.yaml
   kubectl apply -f k8s/noetl/noetl-dev-deployment.yaml
   kubectl apply -f k8s/noetl/noetl-dev-service.yaml

4) Check status
   kubectl get pods
   kubectl get svc

Endpoints:
- pip-version: http://localhost:30084/api/health
- local-dev: http://localhost:30082/api/health



## Deprecated (reload) — safe to remove

Only pip and local-dev deployments are supported. The former reload-based development flow is deprecated. You can remove these files:
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
- These Kind config files with extraMounts were only useful for the deprecated reload flow (mounting the repo into the Kind node). They are not used by the supported pip/local-dev workflows. If you need a custom Kind config, generate it ad-hoc (deploy-platform.sh writes one), or use setup-kind-cluster.sh which writes a temporary config.
