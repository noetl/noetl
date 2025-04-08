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
	@echo "  make build           Build Docker containers"
	@echo "  make rebuild         Rebuild containers without cache"
	@echo "  make up              Start containers in detached mode"
	@echo "  make down            Stop and remove containers"
	@echo "  make restart         Restart services"
	@echo "  make logs            View logs for all services"
	@echo "  make clean           Remove all stopped containers, unused images, volumes, and networks"

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

.PHONY: clean
clean:
	docker system prune -af --volumes

.PHONY: install-uv create-venv install-dev run test build-uv publish clean

install-uv:
	@command -v uv >/dev/null 2>&1 || { \
		echo "Installing uv..."; \
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

run:
	$(VENV)/bin/noetl

test:
	$(VENV)/bin/pytest -v --cov=noetl tests/

build-uv:
	$(UV) build

publish:
	$(UV) publish --username $(PYPI_USER)

clean-dist:
	rm -rf dist *.egg-info .pytest_cache .mypy_cache .venv

#[NATS]#######################################################################

.PHONY: install-nats-tools nats-create-noetl nats-delete-noetl nats-reset-noetl purge-noetl stream-ls

install-nats-tools:
	@echo "Tapping nats-io/nats-tools..."
	@brew tap nats-io/nats-tools
	@echo "Installing nats from nats-io/nats-tools..."
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
