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
