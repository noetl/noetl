#!/bin/bash
set -e

# Script to generate unified NoETL deployment YAML with server and workers in same namespace

NAMESPACE="$1"
if [ -z "$NAMESPACE" ]; then
    echo "Usage: $0 <namespace>"
    exit 1
fi

cat << EOF
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: noetl-server
  labels:
    app: noetl
    component: server
  namespace: ${NAMESPACE}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: noetl
      component: server
  template:
    metadata:
      labels:
        app: noetl
        component: server
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/path: "/metrics"
        prometheus.io/port: "8082"
    spec:
      containers:
        - name: noetl
          image: noetl-local-dev:latest
          imagePullPolicy: IfNotPresent
          command: ["/opt/noetl/.venv/bin/python3"]
          args: ["-m", "uvicorn", "noetl.server:create_app", "--factory", "--host", "0.0.0.0", "--port", "8082", "--log-level", "info"]
          ports:
            - containerPort: 8082
              name: http
          envFrom:
            - configMapRef:
                name: noetl-config
            - secretRef:
                name: noetl-secret
          volumeMounts:
            - name: noetl-data
              mountPath: /opt/noetl/data
            - name: noetl-logs
              mountPath: /opt/noetl/logs
          resources:
            limits:
              cpu: "1"
              memory: "1Gi"
            requests:
              cpu: "0.5"
              memory: "512Mi"
          livenessProbe:
            httpGet:
              path: /api/health
              port: 8082
            initialDelaySeconds: 90
            periodSeconds: 10
            timeoutSeconds: 5
            failureThreshold: 3
          readinessProbe:
            httpGet:
              path: /api/health
              port: 8082
            initialDelaySeconds: 30
            periodSeconds: 5
            timeoutSeconds: 3
            failureThreshold: 3
      volumes:
        - name: noetl-data
          emptyDir: {}
        - name: noetl-logs
          emptyDir: {}
---
apiVersion: v1
kind: Service
metadata:
  name: noetl-server
  labels:
    app: noetl
    component: server
  namespace: ${NAMESPACE}
spec:
  selector:
    app: noetl
    component: server
  ports:
    - name: http
      port: 8082
      targetPort: 8082
      nodePort: 30082
  type: NodePort
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: noetl-worker-cpu-01
  labels:
    app: noetl-worker
    component: worker
    runtime: cpu
    worker-pool: worker-cpu-01
  namespace: ${NAMESPACE}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: noetl-worker
      worker-pool: worker-cpu-01
  template:
    metadata:
      labels:
        app: noetl-worker
        component: worker
        runtime: cpu
        worker-pool: worker-cpu-01
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/path: "/metrics"
        prometheus.io/port: "8080"
    spec:
      initContainers:
        - name: wait-for-api
          image: curlimages/curl:8.7.1
          imagePullPolicy: IfNotPresent
          command:
            - sh
            - -c
            - >-
              until curl -sf http://noetl-server.${NAMESPACE}.svc.cluster.local:8082/api/health; do
                echo "Waiting for NoETL API...";
                sleep 3;
              done
      containers:
        - name: worker
          image: noetl-local-dev:latest
          imagePullPolicy: IfNotPresent
          command: ["noetl"]
          args: ["worker", "start"]
          ports:
            - containerPort: 8080
              name: metrics
          envFrom:
            - configMapRef:
                name: noetl-config
            - secretRef:
                name: noetl-secret
          env:
            - name: NOETL_RUN_MODE
              value: "worker"
            - name: NOETL_WORKER_POOL_NAME
              value: "worker-cpu-01"
            - name: NOETL_SERVER_URL
              value: "http://noetl-server.${NAMESPACE}.svc.cluster.local:8082"
          volumeMounts:
            - name: noetl-data
              mountPath: /opt/noetl/data
            - name: noetl-logs
              mountPath: /opt/noetl/logs
          resources:
            limits:
              cpu: "2"
              memory: "2Gi"
            requests:
              cpu: "0.5"
              memory: "512Mi"
      volumes:
        - name: noetl-data
          emptyDir: {}
        - name: noetl-logs
          emptyDir: {}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: noetl-worker-cpu-02
  labels:
    app: noetl-worker
    component: worker
    runtime: cpu
    worker-pool: worker-cpu-02
  namespace: ${NAMESPACE}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: noetl-worker
      worker-pool: worker-cpu-02
  template:
    metadata:
      labels:
        app: noetl-worker
        component: worker
        runtime: cpu
        worker-pool: worker-cpu-02
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/path: "/metrics"
        prometheus.io/port: "8080"
    spec:
      initContainers:
        - name: wait-for-api
          image: curlimages/curl:8.7.1
          imagePullPolicy: IfNotPresent
          command:
            - sh
            - -c
            - >-
              until curl -sf http://noetl-server.${NAMESPACE}.svc.cluster.local:8082/api/health; do
                echo "Waiting for NoETL API...";
                sleep 3;
              done
      containers:
        - name: worker
          image: noetl-local-dev:latest
          imagePullPolicy: IfNotPresent
          command: ["noetl"]
          args: ["worker", "start"]
          ports:
            - containerPort: 8080
              name: metrics
          envFrom:
            - configMapRef:
                name: noetl-config
            - secretRef:
                name: noetl-secret
          env:
            - name: NOETL_RUN_MODE
              value: "worker"
            - name: NOETL_WORKER_POOL_NAME
              value: "worker-cpu-02"
            - name: NOETL_SERVER_URL
              value: "http://noetl-server.${NAMESPACE}.svc.cluster.local:8082"
          volumeMounts:
            - name: noetl-data
              mountPath: /opt/noetl/data
            - name: noetl-logs
              mountPath: /opt/noetl/logs
          resources:
            limits:
              cpu: "2"
              memory: "2Gi"
            requests:
              cpu: "0.5"
              memory: "512Mi"
      volumes:
        - name: noetl-data
          emptyDir: {}
        - name: noetl-logs
          emptyDir: {}
---
apiVersion: apps/v1
kind: Deployment
metadata:
  name: noetl-worker-gpu-01
  labels:
    app: noetl-worker
    component: worker
    runtime: gpu
    worker-pool: worker-gpu-01
  namespace: ${NAMESPACE}
spec:
  replicas: 1
  selector:
    matchLabels:
      app: noetl-worker
      worker-pool: worker-gpu-01
  template:
    metadata:
      labels:
        app: noetl-worker
        component: worker
        runtime: gpu
        worker-pool: worker-gpu-01
      annotations:
        prometheus.io/scrape: "true"
        prometheus.io/path: "/metrics"
        prometheus.io/port: "8080"
    spec:
      initContainers:
        - name: wait-for-api
          image: curlimages/curl:8.7.1
          imagePullPolicy: IfNotPresent
          command:
            - sh
            - -c
            - >-
              until curl -sf http://noetl-server.${NAMESPACE}.svc.cluster.local:8082/api/health; do
                echo "Waiting for NoETL API...";
                sleep 3;
              done
      containers:
        - name: worker
          image: noetl-local-dev:latest
          imagePullPolicy: IfNotPresent
          command: ["noetl"]
          args: ["worker", "start"]
          ports:
            - containerPort: 8080
              name: metrics
          envFrom:
            - configMapRef:
                name: noetl-config
            - secretRef:
                name: noetl-secret
          env:
            - name: NOETL_RUN_MODE
              value: "worker"
            - name: NOETL_WORKER_POOL_NAME
              value: "worker-gpu-01"
            - name: NOETL_SERVER_URL
              value: "http://noetl-server.${NAMESPACE}.svc.cluster.local:8082"
          volumeMounts:
            - name: noetl-data
              mountPath: /opt/noetl/data
            - name: noetl-logs
              mountPath: /opt/noetl/logs
          resources:
            limits:
              cpu: "2"
              memory: "4Gi"
            requests:
              cpu: "0.5"
              memory: "1Gi"
      volumes:
        - name: noetl-data
          emptyDir: {}
        - name: noetl-logs
          emptyDir: {}
EOF