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
NAMESPACE ?= default
K8S_NOETL_DIR ?= $(K8S_DIR)/noetl
K8S_POSTGRES_DIR ?= $(K8S_DIR)/postgres


#   export PAT=<PERSONAL_ACCESS_TOKEN>
#   export GIT_USER=<GITHUB_USERNAME>
#   make docker-login PAT=<git_pat_token> GIT_USER=<git_username>
#   PAT := <PERSONAL_ACCESS_TOKEN>
#   GIT_USER := <GITHUB_USERNAME>

.PHONY: help
help:
	@echo "Commands:"
	@echo "  make build           Build containers"
	@echo "  make rebuild         Rebuild containers"
	@echo "  make up              Start containers"
	@echo "  make down            Stop containers"
	@echo "  make restart         Restart services"
	@echo "  make logs            View logs"
	@echo "  make clean           Clean up"
	@echo ""
	@echo "Development Commands:"
	@echo "  make install-uv      Install uv package manager"
	@echo "  make create-venv     Create virtual environment"
	@echo "  make install-dev     Install development dependencies"
	@echo "  make install         Install package"
	@echo "  make run             Run the server"
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
	@echo "  make k8s-postgres-apply          Apply ONLY Postgres manifests (NAMESPACE=ns)"
	@echo "  make k8s-postgres-delete         Delete ONLY Postgres manifests (NAMESPACE=ns)"
	@echo "  make postgres-reset-schema       Recreates noetl schema only in running postgres database instance"

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


# === Postgres only on Kubernetes ===
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
