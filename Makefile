GHCR_USERNAME=noetl
VERSION="0.1.17"
K8S_DIR=k8s
COMPOSE_FILE = docker-compose.yaml
PROJECT_NAME = noetl
PYPI_USER = noetl
VENV = .venv
PYTHON = $(VENV)/bin/python
UV = uv

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

docker-login:
	echo $(PAT) | docker login ghcr.io -u $(GIT_USER) --password-stdin

#docker-login:
#	@echo "Logging in to GitHub Container Registry"
#	@echo $$PAT | docker login ghcr.io -u noetl --password-stdin

.PHONY: build
build:
	docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) build

.PHONY: rebuild
rebuild:
	docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) build --no-cache

.PHONY: up
up:
	docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) up -d

.PHONY: down
down:
	docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) down

.PHONY: restart
restart: down up

.PHONY: logs
logs:
	docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) logs -f

.PHONY: clean install-uv create-venv install-dev run test test-server-api test-server-api-unit test-parquet-export test-keyval test-payload test-playbook test-setup build-uv publish encode-playbook register-playbook execute-playbook

clean:
	docker system prune -af --volumes

install-uv:
	@command -v uv >/dev/null 2>&1 || { \
		echo "Installing uv"; \
		curl -LsSf https://astral.sh/uv/install.sh | sh; \
		echo "uv installed to $$HOME/.local/bin"; \
	}

create-venv:
	$(UV) venv
	. $(VENV)/bin/activate

install-dev:
	$(UV) pip install -e ".[dev]"

install:
	$(UV) pip install -e .

uninstall:
	$(UV) pip uninstall noetl

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


#[GCP]##################################################################################################################
.PHONY: gcp-credentials
gcp-credentials:
	@mkdir -p ./secrets
	@gcloud auth application-default login
	@rmdir ./secrets/application_default_credentials.json
	@cp $$HOME/.config/gcloud/application_default_credentials.json ./secrets/application_default_credentials.json
	@echo "Credentials copied to ./secrets/application_default_credentials.json"
