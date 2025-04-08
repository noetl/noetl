# Variables
COMPOSE_FILE = docker-compose.yaml
PROJECT_NAME = noetl

# Default target
.PHONY: help
help:
	@echo "Available commands:"
	@echo "  make build           Build Docker containers"
	@echo "  make rebuild         Rebuild containers without cache"
	@echo "  make up              Start containers in detached mode"
	@echo "  make down            Stop and remove containers"
	@echo "  make restart         Restart services"
	@echo "  make logs            View logs for all services"
	@echo "  make clean           Remove all stopped containers, unused images, volumes, and networks"

# Build Docker containers
.PHONY: build
build:
	docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) build

# Rebuild containers without using cache
.PHONY: rebuild
rebuild:
	docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) build --no-cache

# Start services in detached mode
.PHONY: up
up:
	docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) up -d

# Stop and remove services
.PHONY: down
down:
	docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) down

# Restart services
.PHONY: restart
restart: down up

# View logs of running services
.PHONY: logs
logs:
	docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) logs -f

# Clean up unused Docker resources
.PHONY: clean
clean:
	docker system prune -af --volumes


.PHONY: create-venv install-dev run test build publish clean
PYPI_USER = noetl
VENV = .venv
PYTHON = $(VENV)/bin/python
UV = uv

.PHONY: install-uv
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

build:
	$(UV) build

publish:
	$(UV) publish --username $(PYPI_USER)

clean:
	rm -rf dist *.egg-info .pytest_cache .mypy_cache .venv
