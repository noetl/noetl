GHCR_USERNAME=noetl
VERSION="0.1.17"
K8S_DIR=k8s
COMPOSE_FILE = docker-compose.yaml
PROJECT_NAME = noetl
PYPI_USER = noetl
VENV = .venv
PYTHON = $(VENV)/bin/python
UV = $(HOME)/.local/bin/uv

#   export PAT=<PERSONAL_ACCESS_TOKEN>
#   export GIT_USER=<GITHUB_USERNAME>
#   make docker-login PAT=<git_pat_token> GIT_USER=<git_username>
#   PAT := <PERSONAL_ACCESS_TOKEN>
#   GIT_USER := <GITHUB_USERNAME>

.PHONY: help
help:
	@echo "Commands:"
	@echo "  make build                        Build containers"
	@echo "  make rebuild                      Rebuild containers"
	@echo "  make up                           Start containers"
	@echo "  make down                         Stop containers"
	@echo "  make restart                      Restart services"
	@echo "  make logs                         View logs"
	@echo "  make clean                        Clean up"
	@echo ""
	@echo "Development Commands:"
	@echo "  make install-uv                   Install uv package manager"
	@echo "  make create-venv                  Create virtual environment (.venv)"
	@echo "  make install-dev                  Install development dependencies"
	@echo "  make install                      Install package"
	@echo "  make run                          Run the server"
	@echo "  make diagram PLAYBOOK=... [FORMAT=plantuml|svg|png] [OUTPUT=...]  Generate DAG diagram via 'noetl diagram'"
	@echo ""
	@echo "Release Commands:"
	@echo "  make release VER=X.Y.Z            Run release pipeline (or use VERSION=X.Y.Z)"
	@echo ""
	@echo "Test Commands:"
	@echo "  make test-setup                   Set up test environment (create required directories)"
	@echo "  make test                         Run all tests with coverage"
	@echo "  make test-server-api              Run server API tests"
	@echo "  make test-server-api-unit         Run server API unit tests"
	@echo "  make test-parquet-export          Run Parquet export tests"
	@echo "  make test-keyval                  Run key-value tests"
	@echo "  make test-payload                 Run payload tests"
	@echo "  make test-playbook                Run playbook tests"
	@echo ""
	@echo "Kubernetes Commands:"
	@echo "  make deploy-platform              Deploy the NoETL platform (pass flags via ARGS)"
	@echo "      e.g., make deploy-platform ARGS=\"--deploy-noetl-dev\""
	@echo "            make deploy-platform ARGS=\"--no-cluster\""
	@echo "            make deploy-platform ARGS=\"--no-cluster --no-postgres --no-noetl-pip --deploy-noetl-dev\""
	@echo "            make deploy-platform ARGS=\"--repo-path /path/to/your/noetl/repo --deploy-noetl-dev\""
	@echo "  make deploy-platform-dev          Shortcut: --deploy-noetl-dev"
	@echo "  make deploy-platform-no-cluster   Shortcut: --no-cluster"
	@echo "  make deploy-platform-dev-only     Shortcut: --no-cluster --no-postgres --no-noetl-pip --deploy-noetl-dev"
	@echo "  make deploy-platform-dev-repo     Shortcut with REPO_PATH=/path/to/repo"
	@echo "  make deploy-dashboard             Deploy the Kubernetes dashboard manifests"
	@echo "  make deploy-all                   Deploy platform and dashboard"
	@echo "  make k8s-noetl-config            Apply NoETL ConfigMap and optional IBM quantum secret (NAMESPACE=ns)"
	@echo "  make k8s-noetl-services          Apply NoETL Services (server, worker cpu/qpu) (NAMESPACE=ns)"
	@echo "  make k8s-noetl-deployments       Apply NoETL Deployments (server, worker cpu/qpu) (NAMESPACE=ns)"
	@echo "  make k8s-noetl-apply             Apply config, services, and deployments in order (NAMESPACE=ns)"
	@echo "  make k8s-noetl-delete            Delete NoETL resources (reverse order) (NAMESPACE=ns)"
	@echo "  make k8s-noetl-restart           Rollout restart server and worker deployments (NAMESPACE=ns)"
	@echo "  make k8s-postgres-apply          Apply ONLY Postgres manifests (NAMESPACE=ns)"
	@echo "  make k8s-postgres-delete         Delete ONLY Postgres manifests (NAMESPACE=ns)"

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
	$(VENV)/bin/noetl server start --host 0.0.0.0 --port 8082

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

#[GCP]##################################################################################################################
.PHONY: gcp-credentials
gcp-credentials:
	@mkdir -p ./secrets
	@gcloud auth application-default login
	@rmdir ./secrets/application_default_credentials.json
	@cp $$HOME/.config/gcloud/application_default_credentials.json ./secrets/application_default_credentials.json
	@echo "Credentials copied to ./secrets/application_default_credentials.json"

.PHONY: deploy-platform deploy-dashboard deploy-all deploy-platform-dev deploy-platform-no-cluster deploy-platform-dev-only deploy-platform-dev-repo

# Allow passing flags via ARGS, e.g., make deploy-platform ARGS="--deploy-noetl-dev"
deploy-platform:
	bash $(K8S_DIR)/deploy-platform.sh $(ARGS)

deploy-dashboard:
	bash $(K8S_DIR)/deploy-dashboard.sh

# Deploy both platform and dashboard
deploy-all: deploy-platform deploy-dashboard
	@echo "Platform and dashboard deployed."

# Shortcuts matching common recipes
deploy-platform-dev:
	$(MAKE) deploy-platform ARGS="--deploy-noetl-dev"

deploy-platform-no-cluster:
	$(MAKE) deploy-platform ARGS="--no-cluster"

deploy-platform-dev-only:
	$(MAKE) deploy-platform ARGS="--no-cluster --no-postgres --no-noetl-pip --deploy-noetl-dev"

deploy-platform-dev-repo:
	@if [ -z "$(REPO_PATH)" ]; then echo "Usage: make deploy-platform-dev-repo REPO_PATH=/path/to/your/noetl/repo"; exit 1; fi
	$(MAKE) deploy-platform ARGS="--repo-path $(REPO_PATH) --deploy-noetl-dev"

.PHONY: release
release:
	@ver="$(VER)"; \
	[ -n "$$ver" ] || ver="$(VERSION)"; \
	if [ -z "$$ver" ]; then \
	  echo "Usage: make release VER=X.Y.Z (or VERSION=X.Y.Z)"; \
	  exit 1; \
	fi; \
	./scripts/release.sh $$ver


# === NoETL Kubernetes (direct kubectl) ===
KUBECTL ?= kubectl
NAMESPACE ?= default
K8S_NOETL_DIR ?= $(K8S_DIR)/noetl
K8S_POSTGRES_DIR ?= $(K8S_DIR)/postgres

.PHONY: k8s-noetl-config k8s-noetl-services k8s-noetl-deployments k8s-noetl-apply k8s-noetl-delete k8s-noetl-restart

k8s-noetl-config:
	@echo "Applying NoETL ConfigMap..."
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_NOETL_DIR)/noetl-configmap.yaml
	@# Optional IBM Quantum secret
	@if [ -f "$(K8S_NOETL_DIR)/ibm-quantum-secret.yaml" ]; then \
		echo "Applying IBM Quantum secret..."; \
		$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_NOETL_DIR)/ibm-quantum-secret.yaml; \
	else \
		echo "IBM Quantum secret manifest not found, skipping."; \
	fi

k8s-noetl-services:
	@echo "Applying NoETL Services (server + worker pools)..."
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_NOETL_DIR)/noetl-service.yaml
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_NOETL_DIR)/worker-cpu-service.yaml
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_NOETL_DIR)/worker-qpu-service.yaml

k8s-noetl-deployments:
	@echo "Applying NoETL Deployments (server + worker pools)..."
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_NOETL_DIR)/noetl-deployment.yaml
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_NOETL_DIR)/worker-cpu-deployment.yaml
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_NOETL_DIR)/worker-qpu-deployment.yaml

k8s-noetl-apply: k8s-noetl-config k8s-noetl-services k8s-noetl-deployments
	@echo "NoETL Kubernetes resources applied to namespace $(NAMESPACE)."

k8s-noetl-delete:
	@echo "Deleting NoETL resources from namespace $(NAMESPACE)..."
	-$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_NOETL_DIR)/worker-qpu-deployment.yaml --ignore-not-found
	-$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_NOETL_DIR)/worker-cpu-deployment.yaml --ignore-not-found
	-$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_NOETL_DIR)/noetl-deployment.yaml --ignore-not-found
	-$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_NOETL_DIR)/worker-qpu-service.yaml --ignore-not-found
	-$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_NOETL_DIR)/worker-cpu-service.yaml --ignore-not-found
	-$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_NOETL_DIR)/noetl-service.yaml --ignore-not-found
	-$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_NOETL_DIR)/ibm-quantum-secret.yaml --ignore-not-found
	-$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_NOETL_DIR)/noetl-configmap.yaml --ignore-not-found

k8s-noetl-restart:
	@echo "Rolling out restarts for NoETL deployments in $(NAMESPACE)..."
	-$(KUBECTL) -n $(NAMESPACE) rollout restart deployment/noetl || true
	-$(KUBECTL) -n $(NAMESPACE) rollout restart deployment/noetl-worker-cpu || true
	-$(KUBECTL) -n $(NAMESPACE) rollout restart deployment/noetl-worker-qpu || true

# === Postgres (only) on Kubernetes ===
.PHONY: k8s-postgres-apply k8s-postgres-delete

k8s-postgres-apply:
	@echo "Applying ONLY Postgres manifests to namespace $(NAMESPACE)..."
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_POSTGRES_DIR)/postgres-pv.yaml
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_POSTGRES_DIR)/postgres-service.yaml
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_POSTGRES_DIR)/postgres-configmap.yaml
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_POSTGRES_DIR)/postgres-secret.yaml
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_POSTGRES_DIR)/postgres-config-files.yaml
	$(KUBECTL) -n $(NAMESPACE) apply -f $(K8S_POSTGRES_DIR)/postgres-deployment.yaml
	@echo "Postgres applied. NodePort may be exposed at 30543 (see postgres-service.yaml)."

k8s-postgres-delete:
	@echo "Deleting ONLY Postgres manifests from namespace $(NAMESPACE)..."
	-$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_POSTGRES_DIR)/postgres-deployment.yaml --ignore-not-found
	-$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_POSTGRES_DIR)/postgres-config-files.yaml --ignore-not-found
	-$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_POSTGRES_DIR)/postgres-secret.yaml --ignore-not-found
	-$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_POSTGRES_DIR)/postgres-configmap.yaml --ignore-not-found
	-$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_POSTGRES_DIR)/postgres-service.yaml --ignore-not-found
	-$(KUBECTL) -n $(NAMESPACE) delete -f $(K8S_POSTGRES_DIR)/postgres-pv.yaml --ignore-not-found
	@echo "Postgres resources deleted (PVC/PV may persist depending on cluster policy)."

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


.PHONY: run-server-api run-server-api-dev env-check
env-check:
	@if [ ! -f .env ]; then echo "Warning: .env file not found. Using current environment or defaults."; fi

run-server-api: env-check
	set -a; [ -f .env ] && . .env; set +a; \
	if [ -x "$(VENV)/bin/uvicorn" ]; then \
		"$(VENV)/bin/uvicorn" noetl.main:create_app --factory --host $${NOETL_HOST:-0.0.0.0} --port $${NOETL_PORT:-8082}; \
	else \
		python -m uvicorn noetl.main:create_app --factory --host $${NOETL_HOST:-0.0.0.0} --port $${NOETL_PORT:-8082}; \
	fi

run-server-api-dev: env-check
	set -a; [ -f .env ] && . .env; set +a; \
	if [ -x "$(VENV)/bin/uvicorn" ]; then \
		"$(VENV)/bin/uvicorn" noetl.main:create_app --factory --reload --host $${NOETL_HOST:-0.0.0.0} --port $${NOETL_PORT:-8082}; \
	else \
		python -m uvicorn noetl.main:create_app --factory --reload --host $${NOETL_HOST:-0.0.0.0} --port $${NOETL_PORT:-8082}; \
	fi



.PHONY: run-broker run-worker-api run-worker-api-dev

# Run Broker control loop (event-driven)
run-broker: env-check
	set -a; [ -f .env ] && . .env; set +a; \
	if [ -x "$(VENV)/bin/python" ]; then PYBIN="$(VENV)/bin/python"; else PYBIN="python"; fi; \
	"$$PYBIN" -c "import os; from noetl.broker import run_control_loop; run_control_loop(os.getenv('NOETL_SERVER_URL','http://localhost:8082'), poll_interval=float(os.getenv('NOETL_BROKER_POLL_INTERVAL','2.0')), stop_after=(int(os.getenv('NOETL_BROKER_STOP_AFTER','0')) or None))"

# Run Worker API
run-worker-api: env-check
	set -a; [ -f .env ] && . .env; set +a; \
	export NOETL_ENABLE_WORKER_API=true; \
	export NOETL_HOST=$${NOETL_WORKER_HOST:-0.0.0.0}; \
	export NOETL_PORT=$${NOETL_WORKER_PORT:-8081}; \
	if [ -z "$$NOETL_WORKER_BASE_URL" ]; then export NOETL_WORKER_BASE_URL="http://localhost:$${NOETL_PORT}/api/worker"; fi; \
	if [ -x "$(VENV)/bin/uvicorn" ]; then \
		"$(VENV)/bin/uvicorn" noetl.main:create_app --factory --host $${NOETL_HOST} --port $${NOETL_PORT}; \
	else \
		python -m uvicorn noetl.main:create_app --factory --host $${NOETL_HOST} --port $${NOETL_PORT}; \
	fi

# Run Worker API (dev, autoreload)
run-worker-api-dev: env-check
	set -a; [ -f .env ] && . .env; set +a; \
	export NOETL_ENABLE_WORKER_API=true; \
	export NOETL_HOST=$${NOETL_WORKER_HOST:-0.0.0.0}; \
	export NOETL_PORT=$${NOETL_WORKER_PORT:-8081}; \
	if [ -z "$$NOETL_WORKER_BASE_URL" ]; then export NOETL_WORKER_BASE_URL="http://localhost:$${NOETL_PORT}/api/worker"; fi; \
	if [ -x "$(VENV)/bin/uvicorn" ]; then \
		"$(VENV)/bin/uvicorn" noetl.main:create_app --factory --reload --host $${NOETL_HOST} --port $${NOETL_PORT}; \
	else \
		python -m uvicorn noetl.main:create_app --factory --reload --host $${NOETL_HOST} --port $${NOETL_PORT}; \
	fi

# Run Worker2 API
run-worker2-api: env-check
	set -a; [ -f .env ] && . .env; set +a; \
	export NOETL_ENABLE_WORKER_API=true; \
	# Map Worker2 envs to primary ones for app startup
	export NOETL_WORKER_POOL_RUNTIME=$${NOETL_WORKER2_RUNTIME:-gpu}; \
	export NOETL_WORKER_POOL_NAME=$${NOETL_WORKER2_NAME:-worker-gpu}; \
	export NOETL_HOST=$${NOETL_WORKER2_HOST:-0.0.0.0}; \
	export NOETL_PORT=$${NOETL_WORKER2_PORT:-9081}; \
	export NOETL_WORKER_BASE_URL=$${NOETL_WORKER2_BASE_URL:-http://localhost:9081/api/worker}; \
	export NOETL_WORKER_CAPACITY=$${NOETL_WORKER2_CAPACITY:-1}; \
	export NOETL_WORKER_LABELS=$${NOETL_WORKER2_LABELS:-local,dev,gpu}; \
	if [ -x "$(VENV)/bin/uvicorn" ]; then \
		"$(VENV)/bin/uvicorn" noetl.main:create_app --factory --host $${NOETL_HOST} --port $${NOETL_PORT}; \
	else \
		python -m uvicorn noetl.main:create_app --factory --host $${NOETL_HOST} --port $${NOETL_PORT}; \
	fi

# Run Worker2 API (dev, autoreload)
run-worker2-api-dev: env-check
	set -a; [ -f .env ] && . .env; set +a; \
	export NOETL_ENABLE_WORKER_API=true; \
	# Map Worker2 envs to primary ones for app startup
	export NOETL_WORKER_POOL_RUNTIME=$${NOETL_WORKER2_RUNTIME:-gpu}; \
	export NOETL_WORKER_POOL_NAME=$${NOETL_WORKER2_NAME:-worker-gpu}; \
	export NOETL_HOST=$${NOETL_WORKER2_HOST:-0.0.0.0}; \
	export NOETL_PORT=$${NOETL_WORKER2_PORT:-9081}; \
	export NOETL_WORKER_BASE_URL=$${NOETL_WORKER2_BASE_URL:-http://localhost:9081/api/worker}; \
	export NOETL_WORKER_CAPACITY=$${NOETL_WORKER2_CAPACITY:-1}; \
	export NOETL_WORKER_LABELS=$${NOETL_WORKER2_LABELS:-local,dev,gpu}; \
	if [ -x "$(VENV)/bin/uvicorn" ]; then \
		"$(VENV)/bin/uvicorn" noetl.main:create_app --factory --reload --host $${NOETL_HOST} --port $${NOETL_PORT}; \
	else \
		python -m uvicorn noetl.main:create_app --factory --reload --host $${NOETL_HOST} --port $${NOETL_PORT}; \
	fi
