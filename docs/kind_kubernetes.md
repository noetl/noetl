# Kind (Kubernetes in Docker)
- [Kind default page](https://kind.sigs.k8s.io/)
- [Kind GitHub](https://github.com/kubernetes-sigs/kind)
- [Kind Documentation](https://kind.sigs.k8s.io/docs/)
- [Kind Cheat Sheet](https://kind.sigs.k8s.io/docs/user/cheatsheet/)
- [Kind Kubernetes in Docker](https://kind.sigs.k8s.io/docs/user/quick-start/#using-kind-with-docker)
- [Kind Kubernetes in Docker (Alternative)](https://kind.sigs.k8s.io/docs/user/quick-start/#using-kind-with-docker-alternative)

This guide should get you started with Kind and basic Kubernetes operations.
## What is Kind?
Kind is a tool for running local Kubernetes clusters using Docker containers as nodes. It's designed primarily for testing Kubernetes itself, but it's also used for local development and CI/CD pipelines.

## Prerequisites
- **Homebrew**: macOS package manager
- **Docker**: Kind requires Docker to be installed and running
- **Kind**: Kubernetes in Docker
- **kubectl**: Kubernetes command-line tool
- **kubectx and kubens**: for easier context and namespace switching

## Installation Instructions
### 1. Install Docker
If you don't have Docker installed:

**On macOS:**
``` bash
brew install docker

# Or download Docker Desktop from https://docker.com
```

**On Linux (Ubuntu/Debian):**
``` bash
sudo apt update
sudo apt install docker.io
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER  # Add user to docker group
```

**On Windows:**
- Download Docker Desktop from [https://docker.com](https://docker.com)

### 2. Install Kind
**Using Homebrew (macOS/Linux):**
``` bash
brew install kind
```
**Using Go:**
``` bash
go install sigs.k8s.io/kind@latest
```
**Direct Binary Download:**
``` bash
# For Linux
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-linux-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

# For macOS
curl -Lo ./kind https://kind.sigs.k8s.io/dl/v0.20.0/kind-darwin-amd64
chmod +x ./kind
sudo mv ./kind /usr/local/bin/kind

# For Windows (PowerShell)
curl.exe -Lo kind-windows-amd64.exe https://kind.sigs.k8s.io/dl/v0.20.0/kind-windows-amd64
Move-Item .\kind-windows-amd64.exe c:\some-dir-in-your-PATH\kind.exe
```
### 3. Install kubectl
``` bash
# Using Homebrew
brew install kubectl

# Or using curl (Linux/macOS)
curl -LO "https://dl.k8s.io/release/$(curl -L -s https://dl.k8s.io/release/stable.txt)/bin/linux/amd64/kubectl"
chmod +x kubectl
sudo mv kubectl /usr/local/bin/
```
## Creating a Cluster
### Basic Cluster Creation
``` bash
# Create a cluster with default name 'kind'
kind create cluster

# Create a cluster with a custom name
kind create cluster --name <cluster-name>

# Verify cluster creation
kubectl cluster-info --context kind-kind
```
### Basic Cluster Configuration
Create a config file:
``` yaml
# kind-config.yaml
kind: Cluster
apiVersion: kind.x-k8s.io/v1alpha4
nodes:
- role: control-plane
  kubeadmConfigPatches:
  - |
    kind: InitConfiguration
    nodeRegistration:
      kubeletExtraArgs:
        node-labels: "ingress-ready=true"
  extraPortMappings:
  - containerPort: 80
    hostPort: 80
    protocol: TCP
  - containerPort: 443
    hostPort: 443
    protocol: TCP
- role: worker
- role: worker
```

``` bash
# Create cluster with config
kind create cluster --config kind-config.yaml --name multi-node
```
## Basic Kubernetes Commands
### 1. Getting Pods
``` bash
# List pods in default namespace
kubectl get pods

# List pods in all namespaces
kubectl get pods -A
kubectl get pods --all-namespaces

# List pods in specific namespace
kubectl get pods -n kube-system

# Get detailed pod information
kubectl get pods -o wide

# Watch pods in real-time
kubectl get pods -w

# Get pod details
kubectl describe pod <pod-name>
kubectl describe pod <pod-name> -n <namespace>
```
### 2. Working with Namespaces
``` bash
# List all namespaces
kubectl get namespaces
kubectl get ns

# Create a new namespace
kubectl create namespace <app-name>
kubectl create ns <app-name>

# Switch to a namespace (set as default)
kubectl config set-context --current --namespace=<app-name>

# Check current namespace
kubectl config view --minify | grep namespace

# Switch back to default namespace
kubectl config set-context --current --namespace=default

# Delete a namespace
kubectl delete namespace <app-name>
```
### 3. Getting Services
``` bash
# List services in current namespace
kubectl get services
kubectl get svc

# List services in all namespaces
kubectl get svc -A

# List services in specific namespace
kubectl get svc -n kube-system

# Get detailed service information
kubectl get svc -o wide

# Describe a service
kubectl describe svc <service-name>
kubectl describe svc <service-name> -n <namespace>
```
### 4. Working with Ingress
``` bash
# List ingress resources
kubectl get ingress
kubectl get ing

# List ingress in all namespaces
kubectl get ing -A

# Describe an ingress
kubectl describe ingress <ingress-name>

# Create ingress from YAML
kubectl apply -f ingress.yaml

# Example ingress YAML:
```
``` yaml

apiVersion: networking.k8s.io/v1
kind: Ingress
metadata:
  name: example-ingress
  annotations:
    nginx.ingress.kubernetes.io/rewrite-target: /
spec:
  rules:
  - host: example.local
    http:
      paths:
      - path: /
        pathType: Prefix
        backend:
          service:
            name: example-service
            port:
              number: 80
```
### 5. Port Forwarding
``` bash
# Forward local port to pod
kubectl port-forward pod/<pod-name> 8080:80
kubectl port-forward pod/<pod-name> 8080:80 -n <namespace>

# Forward local port to service
kubectl port-forward svc/<service-name> 8080:80
kubectl port-forward svc/<service-name> 8080:80 -n <namespace>

# Forward with specific local address
kubectl port-forward --address 0.0.0.0 svc/<service-name> 8080:80

# Forward multiple ports
kubectl port-forward svc/<service-name> 8080:80 9090:90

# Background port forward (Linux/macOS)
kubectl port-forward svc/<service-name> 8080:80 &
```
### 6. Viewing Logs
``` bash
# Get logs from a pod
kubectl logs <pod-name>
kubectl logs <pod-name> -n <namespace>

# Get logs from specific container in pod
kubectl logs <pod-name> -c <container-name>

# Follow/stream logs
kubectl logs -f <pod-name>
kubectl logs -f <pod-name> -c <container-name>

# Get previous container logs (if crashed)
kubectl logs <pod-name> --previous

# Get logs from multiple pods
kubectl logs -l app=<app-name>

# Get logs with timestamps
kubectl logs <pod-name> --timestamps

# Get last N lines of logs
kubectl logs <pod-name> --tail=50

# Get logs from a specific time
kubectl logs <pod-name> --since=1h
kubectl logs <pod-name> --since-time=2023-01-01T00:00:00Z
```

### 7. Cluster Management
``` bash
# List Kind clusters
kind get clusters

# Delete a cluster
kind delete cluster --name cluster

# Load Docker image into cluster
kind load docker-image <image-name>:tag --name <cluster-name>

# Get cluster kubeconfig
kind get kubeconfig --name <cluster-name>
```
### 8. Context Management
``` bash
# List contexts
kubectl config get-contexts

# Switch context
kubectl config use-context kind-<cluster-name>

# Current context
kubectl config current-context
```
### 9. Quick Deployments for Testing
``` bash
# Create a test deployment
kubectl create deployment nginx --image=nginx

# Expose deployment
kubectl expose deployment nginx --port=80 --type=NodePort

# Scale deployment
kubectl scale deployment nginx --replicas=3

# Delete deployment
kubectl delete deployment nginx
```
## Tips and Best Practices
1. **Use aliases** for frequently used commands:
``` bash
   alias k='kubectl'
   alias kgp='kubectl get pods'
   alias kgs='kubectl get svc'
```
2. **Install kubectx and kubens** for easier context and namespace switching:
``` bash
   brew install kubectx
   # Then use 'kubectx' to switch contexts and 'kubens' to switch namespaces
```
3. **Use labels and selectors** for better resource management:
``` bash
   kubectl get pods -l app=<app-name>
   kubectl logs -l app=<app-name>
```
4. **Clean up resources** when done:
``` bash
   kubectl delete all --all  # Delete all resources in current namespace
   kind delete cluster       # Delete entire cluster
```

## NoETL Unified Platform Deployment

NoETL provides a unified deployment script that sets up a complete development environment with server, workers, and observability in a single Kind cluster.

### Quick Start

```bash
# Clone NoETL repository
git clone https://github.com/noetl/noetl.git
cd noetl

# Deploy unified platform (recommended)
make unified-deploy

# OR: Complete recreation from scratch  
make unified-recreate-all

# OR: Direct script usage
./k8s/deploy-unified-platform.sh
```

### What Gets Deployed

**Unified Architecture:**
- **Namespace**: `noetl-platform` (all NoETL components)
- **Namespace**: `postgres` (database)

**Components:**
- NoETL server (http://localhost:30082)
- 3 Worker pools (cpu-01, cpu-02, gpu-01)
- PostgreSQL database with schema
- Grafana dashboard (http://localhost:3000, admin/admin)
- VictoriaMetrics (http://localhost:8428/vmui/)
- VictoriaLogs (http://localhost:9428)
- Vector for log/metrics collection

### Benefits of Unified Deployment

1. **Simplified Management**: All components in one namespace
2. **Better Service Discovery**: Direct pod-to-pod communication
3. **Unified Observability**: Everything monitored together
4. **Resource Efficiency**: Reduced namespace overhead

### Deployment Options

**Makefile Commands (Recommended):**
```bash
# Complete unified deployment
make unified-deploy

# Complete recreation from scratch  
make unified-recreate-all

# Health checking
make unified-health-check

# Port forwarding management
make unified-port-forward-start
make unified-port-forward-status
make unified-port-forward-stop

# Get credentials
make unified-grafana-credentials

# View all commands
make help
```

**Direct Script Usage:**
```bash
# Basic unified deployment
./k8s/deploy-unified-platform.sh

# Complete recreation
./k8s/recreate-all.sh

# Health check
./k8s/health-check.sh

# Skip certain components
./k8s/deploy-unified-platform.sh --no-observability
./k8s/deploy-unified-platform.sh --no-postgres

# Use existing cluster
./k8s/deploy-unified-platform.sh --no-cluster

# Custom namespace
./k8s/deploy-unified-platform.sh --namespace my-platform
```

### Monitoring and Debugging

```bash
# Check all pods
kubectl get pods -n noetl-platform

# Check services
kubectl get services -n noetl-platform

# View NoETL server logs
kubectl logs -n noetl-platform -l app=noetl

# View worker logs
kubectl logs -n noetl-platform -l component=worker

# Port-forward to Grafana
kubectl port-forward -n noetl-platform service/vmstack-grafana 3000:80
```

### Cleanup

```bash
# Delete entire cluster
kind delete cluster --name noetl-cluster

# Or just delete NoETL components
kubectl delete namespace noetl-platform
kubectl delete namespace postgres
```
