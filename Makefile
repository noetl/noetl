GHCR_USERNAME=noetl
VERSION="0.1.17"
K8S_DIR=k8s
COMPOSE_FILE = docker-compose.yaml
PROJECT_NAME = noetl
PYPI_USER = noetl
VENV = .venv
PYTHON = $(VENV)/bin/python
UV = $(HOME)/.local/bin/uv
KUBECTL ?= kubectl
NAMESPACE ?= postgres
K8S_NOETL_DIR ?= $(K8S_DIR)/noetl
K8S_POSTGRES_DIR ?= $(K8S_DIR)/postgres
KIND ?= kind
KIND_CLUSTER ?= noetl


#   export PAT=<PERSONAL_ACCESS_TOKEN>
#   export GIT_USER=<GITHUB_USERNAME>
#   make docker-login PAT=<git_pat_token> GIT_USER=<git_username>
#   PAT := <PERSONAL_ACCESS_TOKEN>
#   GIT_USER := <GITHUB_USERNAME>

.PHONY: help
help:
	@echo "Commands:"
	@echo "  make build                 Build containers"
	@echo "  make rebuild               Rebuild containers"
	@echo "  make up                    Start containers"
	@echo "  make down                  Stop containers"
	@echo "  make restart               Restart services"
	@echo "  make logs                  View logs"
	@echo "  make clean                 Clean up"
	@echo ""
	@echo "Local Runtime (env + logs):"
	@echo "  make server-start          Start NoETL server using .env.server or .env (logs/logs/server.log)"
	@echo "  make server-stop           Stop NoETL server"
	@echo "  make server-status         Check NoETL server status and port"
	@echo "  make worker-start          Start NoETL worker using .env.worker or .env (logs/worker.log)"
	@echo "  make worker-stop           Stop NoETL workers (supports multiple instances)"
	@echo ""
	@echo "Development Commands:"
	@echo "  make install-uv            Install uv package manager"
	@echo "  make create-venv           Create virtual environment"
	@echo "  make install-dev           Install development dependencies"
	@echo "  make install               Install package"
	@echo "  make run                   Run the server"
	@echo ""
	@echo "Test Commands:"
	@echo "  make test-setup      Set up test environment (create required directories)"
	@echo "  make test            Run all tests with coverage"
	@echo "  make test-server-api Run server API tests"
	@echo "  make test-server-api-unit Run server API unit tests"
	@echo "  make test-parquet-export Run Parquet export tests"
	@echo "  make test-keyval     Run key-value tests"
	@echo "  make test-payload    Run payload tests"
	@echo "  make test-playbook   Run playbook tests"
	@echo ""
	@echo "Kubernetes Commands:"
	@echo "  make k8s-kind-create          Create kind cluster (or use existing) and set kubectl context"
	@echo "  make k8s-kind-delete          Delete kind cluster"
	@echo "  make k8s-kind-recreate        Recreate kind cluster (delete + create)"
	@echo "  make k8s-reset                Recreate kind cluster and apply Postgres (delete + create + apply)"
	@echo "  make k8s-postgres-apply       Apply ONLY Postgres manifests (NAMESPACE=ns)"
	@echo "  make k8s-postgres-delete      Delete ONLY Postgres manifests (NAMESPACE=ns)"
	@echo "  make k8s-postgres-recreate    Recreate ONLY Postgres (delete + apply) in namespace"
	@echo "  make docker-build-postgres    Build postgres-noetl:latest Docker image locally"
	@echo "  make k8s-load-postgres-image  Load postgres-noetl:latest into kind cluster ($(KIND_CLUSTER))"
	@echo "  make k8s-postgres-deploy      Build + load image into kind + apply Postgres manifests"
	@echo "  make k8s-postgres-port-forward     Set up port forwarding from localhost:30543 to Postgres (interactive)"
	@echo "  make k8s-postgres-port-forward-bg  Set up background port forwarding from localhost:30543 to Postgres"
	@echo "  make k8s-postgres-port-forward-stop Stop background port forwarding"
	@echo "  make k8s-dev-setup               Complete development setup: deploy Postgres + start port forwarding"
	@echo "  make postgres-reset-schema    Recreates noetl schema only in running postgres database instance"

docker-login:
	echo $(PAT) | docker login ghcr.io -u $(GIT_USER) --password-stdin

#docker-login:
#	@echo "Logging in to GitHub Container Registry"
#	@echo $$PAT | docker login ghcr.io -u noetl --password-stdin

.PHONY: build
build:
	@echo "Building UI assets"
	set -a; [ -f .env.docker ] && . .env.docker; set +a; bash scripts/build_ui.sh
	@echo "Building Docker images"
	docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) build

.PHONY: rebuild
rebuild:
	@echo "Building UI assets first with no cache"
	@bash scripts/build_ui.sh
	@echo "Rebuilding Docker images with no cache"
	docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) build --no-cache

.PHONY: up
up:
	set -a; [ -f .env.docker ] && . .env.docker; set +a; docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) up -d --remove-orphans

.PHONY: down
down:
	docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) down --remove-orphans

.PHONY: db-up db-down
db-up:
	docker compose up -d db

db-down:
	docker compose down

.PHONY: restart
restart: down up

.PHONY: logs
logs:
	docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) logs -f

.PHONY: clean install-uv create-venv install-dev uv-lock run test test-server-api test-server-api-unit test-parquet-export test-keyval test-payload test-playbook test-setup build-uv publish encode-playbook register-playbook execute-playbook

clean:
	docker system prune -af --volumes

install-uv:
	@echo "Installing or upgrading uv to the latest version..."
	@curl -LsSf https://astral.sh/uv/install.sh | sh
	@echo "uv has been installed/upgraded."
	@echo "You may need to open a new terminal or run 'source ~/.bashrc' for the change to take effect."


create-venv:
	$(UV) venv
	. $(VENV)/bin/activate

install-dev:
	$(UV) pip install -e ".[dev]"

install:
	$(UV) pip install -e .

uninstall:
	$(UV) pip uninstall noetl

uv-lock:
	    $(UV) lock

run:
	$(VENV)/bin/noetl server --host 0.0.0.0 --port 8082

test: test-setup
	$(VENV)/bin/pytest -v --cov=noetl tests/

test-server-api: test-setup
	$(VENV)/bin/python tests/test_server_api.py

test-server-api-unit: test-setup
	$(VENV)/bin/python tests/test_server_api_unit.py

test-parquet-export: test-setup
	$(VENV)/bin/python tests/test_parquet_export.py

test-keyval: test-setup
	$(VENV)/bin/pytest -v tests/test_keyval.py

test-payload: test-setup
	$(VENV)/bin/pytest -v tests/test_payload.py

test-playbook: test-setup
	$(VENV)/bin/pytest -v tests/test_playbook.py

.PHONY: test-killer
test-killer: test-setup
	$(VENV)/bin/pytest -v tests/test_killer.py
	@echo "  make test-kill      Run process termination tests"


test-setup:
	@echo "Setting up test environment..."
	@mkdir -p data/input data/exports
	@echo "Test environment setup complete."

build-uv:
	$(UV) build

publish:
	$(UV) publish --username $(PYPI_USER)

clean-dist:
	rm -rf dist *.egg-info .pytest_cache .mypy_cache .venv


.PHONY: ui
ui:
	set -a; [ -f .env ] && . .env; set +a; \
	cd ui-src && npm install && VITE_API_BASE_URL=$$VITE_API_BASE_URL npm run dev


.PHONY: server-start server-stop worker-start worker-stop

.PHONY: server-start server-stop

server-start:
	@mkdir -p logs
	@set -a; \
	if [ -f .env ]; then . .env; fi; \
	if [ -f .env.server ]; then . .env.server; fi; \
	set +a; \
	if [ -z "$${NOETL_SCHEMA_VALIDATE:-}" ]; then \
	  echo "ERROR: NOETL_SCHEMA_VALIDATE must be set (true/false) in your .env[.server]"; \
	  exit 1; \
	fi; \
	if [ "$${NOETL_SCHEMA_VALIDATE}" != "true" ] && [ "$${NOETL_SCHEMA_VALIDATE}" != "false" ]; then \
	  echo "ERROR: NOETL_SCHEMA_VALIDATE must be 'true' or 'false'"; \
	  exit 1; \
	fi; \
	mkdir -p ~/.noetl; \
	if command -v setsid >/dev/null 2>&1; then \
	  setsid nohup noetl server start </dev/null >> logs/server.log 2>&1 & echo $$! > ~/.noetl/noetl_server.pid; \
	else \
	  nohup noetl server start </dev/null >> logs/server.log 2>&1 & echo $$! > ~/.noetl/noetl_server.pid; \
	fi; \
	sleep 3; \
	if [ -f ~/.noetl/noetl_server.pid ] && ps -p $$(cat ~/.noetl/noetl_server.pid) >/dev/null 2>&1; then \
	  echo "NoETL server started: PID=$$(cat ~/.noetl/noetl_server.pid) | Port: $(NOETL_PORT) | logs at logs/server.log"; \
	else \
	  echo "Server failed to stay up. Last 50 log lines:"; \
	  tail -n 50 logs/server.log || true; \
	  exit 1; \
	fi

server-stop:
	@if [ -f ~/.noetl/noetl_server.pid ]; then \
	  pid=$$(cat ~/.noetl/noetl_server.pid); \
	  kill -TERM $$pid 2>/dev/null || true; \
	  sleep 3; \
	  if ps -p $$pid >/dev/null 2>&1; then kill -KILL $$pid 2>/dev/null || true; fi; \
	  rm -f ~/.noetl/noetl_server.pid; \
	  rm -f logs/server.pid; \
	  echo "NoETL server stop: PID=$$pid"; \
	else \
	  noetl server stop -f || true; \
	fi

server-status:
	@if [ -f ~/.noetl/noetl_server.pid ] && ps -p $$(cat ~/.noetl/noetl_server.pid) >/dev/null 2>&1; then \
	  pid=$$(cat ~/.noetl/noetl_server.pid); \
	  port=$$(ps aux | grep $$pid | grep -o 'port [0-9]*' | awk '{print $$2}' || echo "8082"); \
	  echo "NoETL server is RUNNING:"; \
	  echo "  - PID: $$pid"; \
	  echo "  - Port: $$port"; \
	  echo "  - URL: http://localhost:$$port"; \
	  echo "  - Logs: logs/server.log"; \
	else \
	  echo "NoETL server is NOT running"; \
	  if [ -f logs/server.log ]; then \
	    echo "Check logs: logs/server.log"; \
	  fi; \
	fi





worker-start:
	@mkdir -p logs
	@/bin/bash -lc ' \
		set -a; \
		if [ -f .env.worker ]; then . .env.worker; \
		elif [ -f .env ]; then . .env; fi; \
		set +a; \
		worker_name=$${NOETL_WORKER_POOL_NAME:-worker-$${NOETL_WORKER_POOL_RUNTIME:-cpu}}; \
		worker_name=$${worker_name//-/_}; \
		log_file=logs/worker_$${worker_name}.log; \
		nohup noetl worker start > $$log_file 2>&1 & \
		sleep 1; \
		pid_file=$$HOME/.noetl/noetl_worker_$${worker_name}.pid; \
		if [ -f $$pid_file ]; then \
			echo "NoETL worker started: PID=$$(cat $$pid_file) | logs at $$log_file"; \
		else \
			echo "Worker failed to start — check $$log_file"; \
		fi'

worker-stop:
	@echo "Stopping NoETL workers..."
	-@noetl worker stop || true

# === kind Kubernetes cluster management ===
.PHONY: k8s-kind-create k8s-kind-delete k8s-kind-recreate k8s-context

k8s-kind-create:
	@echo "Ensuring kind cluster '$(KIND_CLUSTER)' exists and kubectl context is set..."
	@if ! command -v $(KIND) >/dev/null 2>&1; then \
		echo "Error: kind is not installed. See https://kind.sigs.k8s.io/docs/user/quick-start/"; \
		exit 1; \
	fi
	@if $(KIND) get clusters | grep -qx "$(KIND_CLUSTER)"; then \
		echo "kind cluster $(KIND_CLUSTER) already exists"; \
	else \
		cfg="kind-config.yaml"; \
		if [ -f $$cfg ]; then \
			echo "Creating kind cluster $(KIND_CLUSTER) with $$cfg..."; \
			$(KIND) create cluster --name $(KIND_CLUSTER) --config $$cfg; \
		else \
			echo "Creating kind cluster $(KIND_CLUSTER) with default config..."; \
			$(KIND) create cluster --name $(KIND_CLUSTER); \
		fi; \
	fi
	@echo "Setting kubectl context to kind-$(KIND_CLUSTER)"
	@$(KUBECTL) config use-context kind-$(KIND_CLUSTER)
	@echo "Creating namespace '$(NAMESPACE)' if missing..."
	@$(KUBECTL) get ns $(NAMESPACE) >/dev/null 2>&1 || $(KUBECTL) create ns $(NAMESPACE)
	@echo "Cluster is ready. You can now run: make k8s-postgres-apply"

k8s-kind-delete:
	@echo "Deleting kind cluster '$(KIND_CLUSTER)'..."
	@$(KIND) delete cluster --name $(KIND_CLUSTER) || true

k8s-kind-recreate: k8s-kind-delete k8s-kind-create

k8s-context:
	@$(KUBECTL) config use-context kind-$(KIND_CLUSTER)

# === Postgres only on Kubernetes ===
.PHONY: k8s-postgres-apply k8s-postgres-delete

k8s-postgres-apply: k8s-kind-create
	@echo "Applying ONLY Postgres manifests to namespace $(NAMESPACE)..."
	@$(KUBECTL) get ns $(NAMESPACE) >/dev/null 2>&1 || $(KUBECTL) create ns $(NAMESPACE)
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_POSTGRES_DIR)/postgres-pv.yaml
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_POSTGRES_DIR)/postgres-service.yaml
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_POSTGRES_DIR)/postgres-configmap.yaml
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_POSTGRES_DIR)/postgres-secret.yaml
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_POSTGRES_DIR)/postgres-config-files.yaml
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_POSTGRES_DIR)/postgres-deployment.yaml
	@echo "Postgres applied. NodePort may be exposed at 30543 (see postgres-service.yaml)."

.PHONY: k8s-postgres-recreate k8s-reset
k8s-postgres-recreate: k8s-postgres-delete k8s-postgres-apply
	@echo "Recreated Postgres manifests in namespace $(NAMESPACE)."

k8s-reset: k8s-kind-recreate k8s-postgres-apply
	@echo "Kind cluster '$(KIND_CLUSTER)' recreated and Postgres applied in namespace $(NAMESPACE)."

# Build the local Postgres image used by the k8s deployment
.PHONY: docker-build-postgres
docker-build-postgres:
	@echo "Building local Docker image postgres-noetl:latest ..."
	docker build -t postgres-noetl:latest -f docker/postgres/Dockerfile .

# Load the local image into the kind cluster so it is pullable by nodes
.PHONY: k8s-load-postgres-image
k8s-load-postgres-image: k8s-kind-create
	@echo "Loading postgres-noetl:latest into kind cluster '$(KIND_CLUSTER)' ..."
	@$(KIND) load docker-image postgres-noetl:latest --name "$(KIND_CLUSTER)"

# End-to-end: build + load image + apply manifests
.PHONY: k8s-postgres-deploy
k8s-postgres-deploy: docker-build-postgres k8s-load-postgres-image k8s-postgres-apply
	@echo "Postgres deployed to kind cluster '$(KIND_CLUSTER)' in namespace $(NAMESPACE)."

# === Port Forwarding ===
.PHONY: k8s-postgres-port-forward k8s-postgres-port-forward-bg

k8s-postgres-port-forward:
	@echo "Setting up port forwarding from localhost:30543 to Postgres in namespace $(NAMESPACE)..."
	@echo "Press Ctrl+C to stop port forwarding"
	@$(KUBECTL) port-forward -n $(NAMESPACE) svc/postgres 30543:5432

k8s-postgres-port-forward-bg:
	@echo "Setting up background port forwarding from localhost:30543 to Postgres in namespace $(NAMESPACE)..."
	@if pgrep -f "kubectl port-forward -n $(NAMESPACE) svc/postgres 30543:5432" >/dev/null; then \
		echo "Port forwarding already running"; \
	else \
		nohup $(KUBECTL) port-forward -n $(NAMESPACE) svc/postgres 30543:5432 >/dev/null 2>&1 & \
		echo $$! > .postgres-port-forward.pid; \
		echo "Port forwarding started (PID: $$(cat .postgres-port-forward.pid))"; \
		echo "Run 'make k8s-postgres-port-forward-stop' to stop"; \
	fi

.PHONY: k8s-postgres-port-forward-stop
k8s-postgres-port-forward-stop:
	@if [ -f .postgres-port-forward.pid ]; then \
		pid=$$(cat .postgres-port-forward.pid); \
		if ps -p $$pid >/dev/null 2>&1; then \
			kill $$pid && echo "Port forwarding stopped (PID: $$pid)"; \
		else \
			echo "Port forwarding process not running"; \
		fi; \
		rm -f .postgres-port-forward.pid; \
	else \
		echo "No port forwarding PID file found"; \
	fi

# === Convenience targets ===
.PHONY: k8s-dev-setup
k8s-dev-setup: k8s-postgres-deploy k8s-postgres-port-forward-bg
	@echo "Kubernetes development environment is ready!"
	@echo "  - Postgres is running in namespace $(NAMESPACE)"
	@echo "  - Port forwarding is active: localhost:30543 -> Postgres:5432"
	@echo "  - You can now run 'make server-start' to start the NoETL server"
	@echo "  - Run 'make k8s-postgres-port-forward-stop' to stop port forwarding"

k8s-postgres-delete:
	@echo "Deleting ONLY Postgres manifests from namespace $(NAMESPACE)..."
	@if ! $(KUBECTL) cluster-info >/dev/null 2>&1; then \
		echo "No active Kubernetes cluster detected. Skipping delete."; \
	else \
		$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_POSTGRES_DIR)/postgres-deployment.yaml --ignore-not-found || true; \
		$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_POSTGRES_DIR)/postgres-config-files.yaml --ignore-not-found || true; \
		$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_POSTGRES_DIR)/postgres-secret.yaml --ignore-not-found || true; \
		$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_POSTGRES_DIR)/postgres-configmap.yaml --ignore-not-found || true; \
		$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_POSTGRES_DIR)/postgres-service.yaml --ignore-not-found || true; \
		$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_POSTGRES_DIR)/postgres-pv.yaml --ignore-not-found || true; \
		echo "Postgres resources deleted (PVC/PV may persist depending on cluster policy)."; \
	fi

.PHONY: postgres-reset-schema

postgres-reset-schema:
	@echo "Resetting NoETL schema on Postgres (DROP schema and re-run schema_ddl.sql)."
	set -a; [ -f .env ] && . .env; set +a; \
	export PGHOST=$$POSTGRES_HOST PGPORT=$$POSTGRES_PORT PGUSER=$$POSTGRES_USER PGPASSWORD=$$POSTGRES_PASSWORD PGDATABASE=$$POSTGRES_DB; \
	echo "Dropping schema $${NOETL_SCHEMA:-noetl}..."; \
	psql -v ON_ERROR_STOP=1 -c "DROP SCHEMA IF EXISTS $${NOETL_SCHEMA:-noetl} CASCADE;"; \
	echo "Applying schema DDL..."; \
	if $(KUBECTL) -n $(NAMESPACE) get configmap postgres-config-files >/dev/null 2>&1 ; then \
		$(KUBECTL) -n $(NAMESPACE) get configmap postgres-config-files -o jsonpath='{.data.schema_ddl\.sql}' | psql -v ON_ERROR_STOP=1 -f - ; \
	else \
		if [ -f k8s/postgres/schema_ddl.sql ]; then \
			psql -v ON_ERROR_STOP=1 -f k8s/postgres/schema_ddl.sql ; \
		else \
			echo "Could not find schema_ddl.sql locally or in cluster configmap; aborting."; exit 1; \
		fi; \
	fi

# Generate a DAG diagram using the NoETL CLI
.PHONY: diagram
# Usage examples:
#   make diagram PLAYBOOK=examples/weather/weather_loop_example.yaml
#   make diagram PLAYBOOK=examples/weather/weather_loop_example.yaml FORMAT=svg
#   make diagram PLAYBOOK=examples/weather/weather_loop_example.yaml OUTPUT=playbook.puml
#   make diagram PLAYBOOK=playbook.puml FORMAT=svg OUTPUT=playbook.svg
# Variables:
#   PLAYBOOK - path to .yaml/.yml or .puml file (required)
#   FORMAT   - plantuml (default), svg, or png
#   OUTPUT   - output file path; if omitted, defaults to <PLAYBOOK base>.<ext>

diagram:
	@if [ -z "$(PLAYBOOK)" ]; then \
	  echo "Usage: make diagram PLAYBOOK=path/to/playbook.(yaml|yml|puml) [FORMAT=plantuml|svg|png] [OUTPUT=/path/to/out.ext]"; \
	  exit 1; \
	fi
	@fmt="$(FORMAT)"; \
	if [ -z "$$fmt" ]; then fmt="plantuml"; fi; \
	out="$(OUTPUT)"; \
	if [ -z "$$out" ]; then \
	  base="$$(/bin/echo $(PLAYBOOK) | sed -E 's/\.(yaml|yml|json|puml|plantuml)$$//')"; \
	  if [ "$$fmt" = "plantuml" ]; then ext="puml"; else ext="$$fmt"; fi; \
	  out="$$base.$$ext"; \
	  echo "No OUTPUT provided; defaulting to $$out"; \
	fi; \
	cli="$(VENV)/bin/noetl"; \
	if [ ! -x "$$cli" ]; then cli="noetl"; fi; \
	echo "Generating diagram from $(PLAYBOOK) -> $$out (format=$$fmt) using '$$cli'"; \
	"$$cli" diagram "$(PLAYBOOK)" -f "$$fmt" -o "$$out"



#[GCP]##################################################################################################################
.PHONY: gcp-credentials
gcp-credentials:
	@mkdir -p ./secrets
	@gcloud auth application-default login
	@rmdir ./secrets/application_default_credentials.json
	@cp $$HOME/.config/gcloud/application_default_credentials.json ./secrets/application_default_credentials.json
	@echo "Credentials copied to ./secrets/application_default_credentials.json"
