#!/usr/bin/env bash
set -euo pipefail

# Deploy observability stack into the specified namespace (unified with NoETL)
# This is a modified version of the original observability deployment

NAMESPACE="$1"
if [ -z "$NAMESPACE" ]; then
    echo "Usage: $0 <namespace>"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OBSERVABILITY_DIR="${SCRIPT_DIR}/observability"

need_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    return 1
  fi
}

info() { echo "[INFO] $*"; }
warn() { echo "[WARN] $*"; }
error() { echo "[ERROR] $*" 1>&2; }

# Check required tools
if ! need_cmd kubectl; then
  error "kubectl is not installed or not in PATH. Skipping deployment."
  exit 1
fi
if ! need_cmd helm; then
  error "helm is not installed or not in PATH. Skipping deployment."
  exit 1
fi

info "Deploying observability stack to unified namespace '${NAMESPACE}'..."

# Add/update repos
helm repo add vm https://victoriametrics.github.io/helm-charts/ >/dev/null 2>&1 || true
helm repo add vector https://helm.vector.dev >/dev/null 2>&1 || true
helm repo update

# Ensure namespace exists (should already be created by main script)
if ! kubectl get ns "${NAMESPACE}" >/dev/null 2>&1; then
  info "Creating namespace ${NAMESPACE}"
  kubectl create ns "${NAMESPACE}"
fi

# Create PersistentVolume for VictoriaMetrics storage
info "Creating PersistentVolume for VictoriaMetrics storage..."
kubectl apply -f "${OBSERVABILITY_DIR}/victoriametrics-pv.yaml" || warn "Failed to create VictoriaMetrics PV, continuing..."

# VictoriaMetrics stack (Grafana + vmagent + vmsingle)
info "Installing/Upgrading VictoriaMetrics k8s stack (vmstack) in namespace ${NAMESPACE}"
VMSTACK_VALUES="${OBSERVABILITY_DIR}/vmstack-values.yaml"

# Create custom values for unified deployment
UNIFIED_VMSTACK_VALUES="/tmp/vmstack-values-unified.yaml"
cat > "${UNIFIED_VMSTACK_VALUES}" << EOF
# Unified deployment values for VictoriaMetrics stack
vmsingle:
  enabled: true
  spec:
    retentionPeriod: "1w"
    storage:
      storageClassName: ""
      resources:
        requests:
          storage: 5Gi
    image:
      pullPolicy: IfNotPresent

vmagent:
  enabled: true
  spec:
    selectAllByDefault: true
    scrapeInterval: "30s"
    externalLabels:
      cluster: "noetl-platform"
    image:
      pullPolicy: IfNotPresent

vmalert:
  enabled: true

grafana:
  enabled: true
  sidecar:
    dashboards:
      enabled: true
      label: grafana_dashboard
      labelValue: "1" 
      searchNamespace: ALL
      folderAnnotation: grafana_folder
      defaultFolderName: NoETL
    datasources:
      enabled: true
      label: grafana_datasource
      searchNamespace: ALL
  service:
    type: NodePort
    nodePort: 30000
  persistence:
    enabled: false
  adminPassword: admin

defaultRules:
  create: true
  rules:
    etcd: false
    general: true
    k8s: true
    kubeApiserver: false
    kubeApiserverAvailability: false
    kubeApiserverBurnrate: false
    kubeApiserverHistogram: false
    kubeApiserverSlos: false
    kubelet: false
    kubePrometheusGeneral: true
    kubePrometheusNodeRecording: true
    kubernetesApps: true
    kubernetesResources: true
    kubernetesStorage: false
    kubernetesSystem: false
    node: false
    prometheus: true
    prometheusOperator: true

vmoperator:
  enabled: true
EOF

if [ -f "${VMSTACK_VALUES}" ]; then
  info "Merging with existing vmstack values"
  # Use existing values as base and override with unified values
  helm upgrade --install vmstack vm/victoria-metrics-k8s-stack -n "${NAMESPACE}" \
    -f "${VMSTACK_VALUES}" \
    -f "${UNIFIED_VMSTACK_VALUES}"
else
  helm upgrade --install vmstack vm/victoria-metrics-k8s-stack -n "${NAMESPACE}" \
    -f "${UNIFIED_VMSTACK_VALUES}"
fi

# Wait for operator webhook to become ready
info "Waiting for VictoriaMetrics operator deployment to become ready"
if ! kubectl rollout status deployment/vmstack-victoria-metrics-operator -n "${NAMESPACE}" --timeout=180s >/dev/null 2>&1; then
  warn "VictoriaMetrics operator deployment not ready after timeout; continuing but webhook operations may fail"
else
  sleep 3
fi

# VictoriaLogs single node
info "Installing/Upgrading VictoriaLogs (vlogs) in namespace ${NAMESPACE}"
helm upgrade --install vlogs vm/victoria-logs-single -n "${NAMESPACE}" \
  --set server.service.type=NodePort \
  --set server.service.nodePort=30428

# Vector DaemonSet: use custom values for unified deployment
VECTOR_VALUES="${OBSERVABILITY_DIR}/vector-values.yaml"
UNIFIED_VECTOR_VALUES="/tmp/vector-values-unified.yaml"
cat > "${UNIFIED_VECTOR_VALUES}" << EOF
role: "Agent"

service:
  enabled: false

podMonitor:
  enabled: false

# Custom config for unified namespace
customConfig:
  data_dir: "/vector-data-dir"
  api:
    enabled: true
    address: "127.0.0.1:8686"
  sources:
    kubernetes_logs:
      type: "kubernetes_logs"
      namespace_annotation_fields:
        namespace_labels: ""
      node_annotation_fields:
        node_labels: ""
      pod_annotation_fields:
        pod_labels: ""
        pod_annotations: ""
    host_metrics:
      type: "host_metrics"
      collectors: ["cpu", "disk", "filesystem", "load", "host", "memory", "network"]
  transforms:
    remap_k8s_logs:
      type: "remap"
      inputs: ["kubernetes_logs"]
      source: |
        .message = string!(.message)
        .stream = string!(.stream)
        .timestamp = .timestamp
  sinks:
    vlogs:
      type: "http"
      inputs: ["remap_k8s_logs"]
      uri: "http://vlogs-victoria-logs-single-server.${NAMESPACE}.svc.cluster.local:9428/insert/jsonline?_stream_fields=stream,kubernetes.pod_namespace,kubernetes.pod_name,kubernetes.container_name&_msg_field=message&_time_field=timestamp"
      method: "post"
      encoding:
        codec: "json"
      framing:
        method: "newline_delimited"
    vmsingle:
      type: "prometheus_remote_write"
      inputs: ["host_metrics"]
      endpoint: "http://vmsingle-vmstack-victoria-metrics-k8s-stack.${NAMESPACE}.svc.cluster.local:8429/api/v1/write"
EOF

if [ -f "${VECTOR_VALUES}" ]; then
  info "Installing/Upgrading Vector with custom unified values"
  helm upgrade --install vector vector/vector -n "${NAMESPACE}" \
    -f "${VECTOR_VALUES}" \
    -f "${UNIFIED_VECTOR_VALUES}"
else
  info "Installing/Upgrading Vector with unified values"
  helm upgrade --install vector vector/vector -n "${NAMESPACE}" \
    -f "${UNIFIED_VECTOR_VALUES}"
fi

# Create unified VMPodScrape for NoETL monitoring
info "Creating VMPodScrape for NoETL components"
cat << EOF | kubectl apply -f -
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMPodScrape
metadata:
  name: noetl-components
  namespace: ${NAMESPACE}
  labels:
    app: noetl
spec:
  selector:
    matchLabels:
      app: noetl
  podMetricsEndpoints:
  - port: http
    path: /metrics
    interval: 30s
    targetPort: 8082
  namespaceSelector:
    matchNames:
    - ${NAMESPACE}
---
apiVersion: operator.victoriametrics.com/v1beta1
kind: VMPodScrape
metadata:
  name: noetl-workers
  namespace: ${NAMESPACE}
  labels:
    app: noetl-worker
spec:
  selector:
    matchLabels:
      component: worker
  podMetricsEndpoints:
  - port: metrics
    path: /metrics
    interval: 30s
    targetPort: 8080
  namespaceSelector:
    matchNames:
    - ${NAMESPACE}
EOF

# Apply port-forward for observability UIs
info "Setting up port-forwarding for observability UIs"
cat > "/tmp/port-forward-unified.sh" << EOF
#!/bin/bash
# Port-forward script for unified observability

NAMESPACE="${NAMESPACE}"

# Function to start port-forward in background
start_port_forward() {
    local service=\$1
    local local_port=\$2
    local remote_port=\$3
    local name=\$4
    
    # Kill existing process if running
    pkill -f "kubectl.*port-forward.*\${service}" || true
    sleep 1
    
    echo "Starting port-forward for \${name}: localhost:\${local_port}"
    kubectl port-forward -n "\${NAMESPACE}" "service/\${service}" "\${local_port}:\${remote_port}" > "/tmp/pf-\${name}.log" 2>&1 &
    echo \$! > "/tmp/pf-\${name}.pid"
}

case "\$1" in
    start)
        echo "Starting port-forwards for unified observability..."
        start_port_forward "vmstack-grafana" 3000 80 "grafana"
        start_port_forward "vlogs-victoria-logs-single-server" 9428 9428 "vlogs"
        start_port_forward "vmsingle-vmstack-victoria-metrics-k8s-stack" 8428 8428 "vmsingle"
        echo "Port-forwards started. Services available at:"
        echo "  - Grafana:            http://localhost:3000"
        echo "  - VictoriaLogs UI:    http://localhost:9428"
        echo "  - VictoriaMetrics UI: http://localhost:8428/vmui/"
        ;;
    stop)
        echo "Stopping all port-forwards..."
        for pid_file in /tmp/pf-*.pid; do
            if [ -f "\$pid_file" ]; then
                pid=\$(cat "\$pid_file")
                kill "\$pid" 2>/dev/null || true
                rm "\$pid_file"
            fi
        done
        pkill -f "kubectl.*port-forward.*vmstack-grafana" || true
        pkill -f "kubectl.*port-forward.*vlogs-victoria-logs-single-server" || true
        pkill -f "kubectl.*port-forward.*vmsingle-vmstack-victoria-metrics-k8s-stack" || true
        echo "Port-forwards stopped."
        ;;
    status)
        echo "Port-forward status:"
        for pid_file in /tmp/pf-*.pid; do
            if [ -f "\$pid_file" ]; then
                pid=\$(cat "\$pid_file")
                if kill -0 "\$pid" 2>/dev/null; then
                    name=\$(basename "\$pid_file" .pid | sed 's/pf-//')
                    echo "  \${name}: RUNNING (PID: \$pid)"
                else
                    echo "  \${name}: STOPPED"
                fi
            fi
        done
        ;;
    *)
        echo "Usage: \$0 {start|stop|status}"
        exit 1
        ;;
esac
EOF

chmod +x "/tmp/port-forward-unified.sh"
"/tmp/port-forward-unified.sh" start

# Copy port-forward script to observability directory
cp "/tmp/port-forward-unified.sh" "${OBSERVABILITY_DIR}/port-forward-unified.sh"
chmod +x "${OBSERVABILITY_DIR}/port-forward-unified.sh"

# Clean up temporary files
rm -f "${UNIFIED_VMSTACK_VALUES}" "${UNIFIED_VECTOR_VALUES}"

# Provision Grafana dashboards (NoETL server & workers) via ConfigMaps (sidecar)
info "Provisioning Grafana dashboards..."
"${OBSERVABILITY_DIR}/provision-grafana.sh" "${NAMESPACE}" || warn "Dashboard provisioning failed, continuing..."

# Provision Grafana datasources (VictoriaMetrics + VictoriaLogs) via ConfigMap (sidecar)
info "Provisioning Grafana datasources..."
"${OBSERVABILITY_DIR}/provision-datasources.sh" "${NAMESPACE}" || warn "Datasource provisioning failed, continuing..."

info "Unified observability deployment completed!"
cat << EOF

Unified observability stack deployed in namespace: ${NAMESPACE}

Services are available at:
  - Grafana:            http://localhost:3000 (admin/admin)
  - VictoriaLogs UI:    http://localhost:9428
  - VictoriaMetrics UI: http://localhost:8428/vmui/

Port-forwarding management:
  - Status: ${OBSERVABILITY_DIR}/port-forward-unified.sh status
  - Stop:   ${OBSERVABILITY_DIR}/port-forward-unified.sh stop
  - Start:  ${OBSERVABILITY_DIR}/port-forward-unified.sh start

All NoETL components (server + workers) and observability are now running in the same namespace: ${NAMESPACE}
EOF