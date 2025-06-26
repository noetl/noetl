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
	@echo ""
	@echo "API Commands:"
	@echo "  make encode-playbook  Encode playbook to base64"
	@echo "  make register-playbook Register playbook with NoETL server"
	@echo "  make execute-playbook Execute playbook on NoETL server"

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

# API Commands
encode-playbook:
	@echo "Encoding playbook to base64..."
	@# Use different base64 options based on platform (Linux vs macOS)
	@if [ "$$(uname)" = "Linux" ]; then \
		echo "export PLAYBOOK_BASE64=$$(cat ./catalog/playbooks/weather_example.yaml | base64 -w 0)"; \
		cat ./catalog/playbooks/weather_example.yaml | base64 -w 0 > /tmp/playbook_base64.txt; \
	else \
		echo "export PLAYBOOK_BASE64=$$(cat ./catalog/playbooks/weather_example.yaml | base64 | tr -d '\n')"; \
		cat ./catalog/playbooks/weather_example.yaml | base64 | tr -d '\n' > /tmp/playbook_base64.txt; \
	fi
	@echo "Playbook encoded and saved to /tmp/playbook_base64.txt"
	@echo "You can use: export PLAYBOOK_BASE64=\$$(cat /tmp/playbook_base64.txt)"

register-playbook:
	@echo "Registering playbook with NoETL server..."
	@# Use different base64 options based on platform (Linux vs macOS)
	@if [ "$$(uname)" = "Linux" ]; then \
		PLAYBOOK_BASE64=$$(cat ./catalog/playbooks/weather_example.yaml | base64 -w 0); \
	else \
		PLAYBOOK_BASE64=$$(cat ./catalog/playbooks/weather_example.yaml | base64 | tr -d '\n'); \
	fi; \
	curl -X POST "http://localhost:8082/catalog/register" \
	  -H "Content-Type: application/json" \
	  -d "{\"content_base64\": \"$$PLAYBOOK_BASE64\"}"

execute-playbook:
	@echo "Executing playbook on NoETL server..."
	@curl -X POST "http://localhost:8082/agent/execute" \
	  -H "Content-Type: application/json" \
	  -d '{ \
	    "path": "weather_example", \
	    "version": "0.1.0", \
	    "input_payload": { \
	      "city": "New York" \
	    }, \
	    "sync_to_postgres": true \
	  }'



#[NATS]#################################################################################################################

.PHONY: install-nats-tools nats-create-noetl nats-delete-noetl nats-reset-noetl purge-noetl stream-ls

install-nats-tools:
	@echo "Tapping nats-io/nats-tools"
	@brew tap nats-io/nats-tools
	@echo "Installing nats from nats-io/nats-tools"
	@brew install nats-io/nats-tools/nats
	@echo "NATS installation complete."

nats-create-noetl:
	@echo "Creating NATS noetl stream"
	kubectl config use-context docker-desktop
	kubectl apply -f $(K8S_DIR)/nats/noetl/noetl-stream.yaml -n nats

nats-delete-noetl:
	@echo "Deleting NATS noetl stream"
	kubectl config use-context docker-desktop
	kubectl delete -f $(K8S_DIR)/nats/noetl/noetl-stream.yaml -n nats

nats-reset-noetl: nats-delete-noetl nats-create-noetl
	@echo "Reset NATS noetl stream in Kubernetes"

purge-noetl:
	@echo "Purged NATS noetl stream"
	@nats stream purge noetl --force -s $(NATS_URL)
	@make stream-ls

stream-ls:
	@nats stream ls -s $(NATS_URL)

nats_account_info:
	@nats account info -s $(NATS_URL)

nats_kv_ls:
	@nats kv ls -s $(NATS_URL)


#[GCP]##################################################################################################################
.PHONY: gcp-credentials
gcp-credentials:
	@mkdir -p ./secrets
	@gcloud auth application-default login
	@rmdir ./secrets/application_default_credentials.json
	@cp $$HOME/.config/gcloud/application_default_credentials.json ./secrets/application_default_credentials.json
	@echo "Credentials copied to ./secrets/application_default_credentials.json"
