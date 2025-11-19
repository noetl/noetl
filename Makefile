GHCR_USERNAME=noetl
VERSION="1.0.0"
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
NOETL_HOST ?= localhost
NOETL_PORT ?= 8082


#   export PAT=<PERSONAL_ACCESS_TOKEN>
#   export GIT_USER=<GITHUB_USERNAME>
#   make docker-login PAT=<git_pat_token> GIT_USER=<git_username>
#   PAT := <PERSONAL_ACCESS_TOKEN>
#   GIT_USER := <GITHUB_USERNAME>

.PHONY: help
help:
	@echo "Commands:"
	@echo "  make build                 			Build containers"
	@echo "  make rebuild               			Rebuild containers"
	@echo "  make up                    			Start containers"
	@echo "  make down                  			Stop containers"
	@echo "  make restart               			Restart services"
	@echo "  make logs                  			View logs"
	@echo "  make clean                 			Clean up"
	@echo ""
	@echo "Development Commands:"
	@echo "  make install-uv            			Install uv package manager"
	@echo "  make create-venv           			Create virtual environment"
	@echo "  make install-dev 			        Install development dependencies"
	@echo "  make install               			Install package"
	@echo "  make run                   			Run the server"
	@echo ""
	@echo "Test Commands:"
	@echo "  make test-setup      					Set up test environment (create required directories)"
	@echo "  make test            					Run all tests with coverage"
	@echo "  make test-server-api 					Run server API tests"
	@echo "  make test-server-api-unit				Run server API unit tests"
	@echo "  make test-parquet-export 				Run Parquet export tests"
	@echo "  make test-keyval     					Run key-value tests"
	@echo "  make test-payload    					Run payload tests"
	@echo "  make test-playbook   					Run playbook tests"
	@echo "  make test-control-flow-workbook			Run control flow workbook tests"
	@echo "  make test-control-flow-workbook-runtime		Run control flow workbook tests with runtime execution"
	@echo "  make test-control-flow-workbook-full		Full integration test (reset DB, restart server, run runtime tests)"
	@echo "  make test-http-duckdb-postgres			Run HTTP DuckDB Postgres tests"
	@echo "  make test-http-duckdb-postgres-runtime		Run HTTP DuckDB Postgres tests with runtime execution"
	@echo "  make test-http-duckdb-postgres-full		Full integration test (reset DB, restart server, register credentials, run runtime tests)"
	@echo "  make test-playbook-composition			Run playbook composition tests"
	@echo "  make test-playbook-composition-runtime		Run playbook composition tests with runtime execution"
	@echo "  make test-playbook-composition-full		Full integration test (reset DB, restart server, register credentials, run runtime tests)"
	@echo "  make test-playbook-composition-k8s		Kubernetes-friendly test (restart server, register credentials, run runtime tests, skip DB reset)"
	@echo ""
	@echo "Kubernetes Commands:"
	@echo "  make k8s-kind-create          			Create kind cluster (or use existing) and set kubectl context"
	@echo "  make k8s-kind-delete          			Delete kind cluster"
	@echo "  make k8s-kind-recreate        			Recreate kind cluster (delete + create)"
	@echo "  make k8s-reset                			Recreate kind cluster and apply Postgres (delete + create + apply)"
	@echo "  make k8s-postgres-apply       			Apply ONLY Postgres manifests (NAMESPACE=ns)"
	@echo "  make k8s-postgres-delete      			Delete ONLY Postgres manifests (NAMESPACE=ns)"
	@echo "  make k8s-postgres-recreate    			Recreate ONLY Postgres (delete + apply) in namespace"
	@echo "  make docker-build-postgres    			Build postgres-noetl:latest Docker image locally"
	@echo "  make k8s-load-postgres-image  			Load postgres-noetl:latest into kind cluster ($(KIND_CLUSTER))"
	@echo "  make k8s-postgres-deploy      			Build + load image into kind + apply Postgres manifests"
	@echo "  make k8s-postgres-port-forward			Set up port forwarding from localhost:30543 to Postgres (interactive)"
	@echo "  make k8s-postgres-port-forward-bg			Set up background port forwarding from localhost:30543 to Postgres"
	@echo "  make k8s-postgres-port-forward-stop		 	Stop background port forwarding"
	@echo "  make k8s-dev-setup              	 		Complete development setup: deploy Postgres + start port forwarding"
	@echo "  make k8s-platform-deploy        			Deploy complete NoETL platform (Postgres + NoETL server)"
	@echo "  make k8s-platform-status        			Check NoETL platform deployment status"
	@echo "  make k8s-platform-test          			Test the platform with a simple playbook"
	@echo "  make k8s-platform-clean         			Clean up the NoETL platform deployment"
	@echo "  make redeploy-noetl             			Redeploy NoETL with metrics (preserves observability services)"
	@echo "  make postgres-reset-schema    			Recreates noetl schema only in running postgres database instance"
	@echo ""
	@echo "Local Runtime (env + logs):"
	@echo "  make start-server										Start NoETL server using .env.server or .env (logs/logs/server.log)"
	@echo "  make stop-server										Stop NoETL server"
	@echo "  make server-status										Check NoETL server status and port"
	@echo "  make worker-start										Start NoETL worker using .env.worker or .env (logs/worker.log)"
	@echo "  make worker-stop										Stop NoETL workers (supports multiple instances)"
	@echo "  make clean-logs										Remove NoETL log files"
	@echo "  make noetl-start										Start NoETL runtime"
	@echo "  make noetl-stop										Stop NoETL runtime"
	@echo "  make noetl-restart										Restart NoETL runtime"
	@echo "  make validate-playbooks\t\t\t\tValidate playbooks for iterator+metadata schema"
	@echo "  make noetl-run PLAYBOOK=examples/weather/weather_loop_example HOST=localhost PORT=8082	Execute specific playbook"
	@echo "  make noetl-execute PLAYBOOK=examples/weather/weather_loop_example				Execute specific playbook"
	@echo "  make export-execution-logs ID=222437726840946688 HOST=localhost PORT=8082			Dump execution to logs for specific ID"
	@echo "  make noetl-execute-watch ID=222437726840946688 HOST=localhost PORT=8082			Watch status with live updates"
	@echo "  make noetl-execute-status ID=222437726840946688 > logs/status.json					Get status for specific ID"
	@echo "  make noetl-validate-status FILE=logs/status.json							Validate and clean up a status.json file"
	@echo "  make register-examples HOST=localhost PORT=8082			Register example catalog playbooks"
	@echo "  make register-test-playbooks HOST=localhost PORT=8082		Register test fixture playbooks"
	@echo "  make register-credential FILE=tests/fixtures/credentials/pg_local.json HOST=localhost PORT=8082	Register one credential payload"
	@echo "  make register-test-credentials HOST=localhost PORT=8082			Upload all test fixture credentials"
	@echo ""
	@echo "Observability Commands:"
	@echo "  make unified-deploy                        		Deploy unified NoETL platform with observability (recommended)"
	@echo "  make unified-recreate-all                  		Complete recreation: cleanup + rebuild + redeploy everything"
	@echo "  make unified-health-check                  		Check health of unified deployment components"
	@echo "  make unified-grafana-credentials           		Get Grafana credentials for unified deployment"
	@echo "  make unified-port-forward-start           		Start port-forwards for unified deployment"
	@echo "  make unified-port-forward-stop            		Stop port-forwards for unified deployment"  
	@echo "  make unified-port-forward-status          		Check port-forward status for unified deployment"
	@echo "  make observability-grafana-credentials    		Get Grafana credentials (auto-detects unified or legacy)"
	@echo "  make observability-deploy                 		Deploy observability stack (legacy separate namespace)"
	@echo "  make observability-port-forward-start     		Start port-forwards (legacy)"
	@echo "  make observability-port-forward-stop      		Stop port-forwards (legacy)"

docker-login:
	echo $(PAT) | docker login ghcr.io -u $(GIT_USER) --password-stdin

#docker-login:
#	@echo "Logging in to GitHub Container Registry"
#	@echo $$PAT | docker login ghcr.io -u noetl --password-stdin

.PHONY: build
build:
	@echo "Building UI assets"
	set -a; [ -f .env.docker ] && . .env.docker; set +a; bash tools/build_ui.sh
	@echo "Building Docker images"
	docker compose -f $(COMPOSE_FILE) -p $(PROJECT_NAME) build

.PHONY: rebuild
rebuild:
	@echo "Building UI assets first with no cache"
	@bash tools/build_ui.sh
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

.PHONY: clean install-uv create-venv install-dev uv-lock run test test-server-api test-server-api-unit test-parquet-export test-keyval test-payload test-playbook test-control-flow-workbook test-control-flow-workbook-runtime test-control-flow-workbook-full test-http-duckdb-postgres test-http-duckdb-postgres-runtime test-http-duckdb-postgres-full test-playbook-composition test-playbook-composition-runtime test-playbook-composition-full test-playbook-composition-k8s test-setup build-uv publish encode-playbook register-playbook execute-playbook register-examples register-test-playbooks start-workers stop-multiple clean-logs

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

test-control-flow-workbook: test-setup
	$(VENV)/bin/pytest -v tests/test_control_flow_workbook.py

test-control-flow-workbook-runtime: test-setup
	@echo "Running control flow workbook tests with runtime execution..."
	@echo "This requires a running NoETL server. Use 'make noetl-restart' if needed."
	NOETL_RUNTIME_TESTS=true $(VENV)/bin/pytest -v tests/test_control_flow_workbook.py

test-control-flow-workbook-full: noetl-stop postgres-reset-schema noetl-start
	@echo "Running full integration test for control flow workbook..."
	@echo "This will stop services, reset database, restart server, and run runtime tests"
	@sleep 2  # Give server time to start
	$(MAKE) test-control-flow-workbook-runtime

test-http-duckdb-postgres: test-setup
	$(VENV)/bin/pytest -v tests/test_scheduler_basic.py

test-http-duckdb-postgres-runtime: test-setup
	@echo "Running HTTP DuckDB Postgres tests with runtime execution..."
	@echo "This requires a running NoETL server and proper credentials (pg_local, gcs_hmac_local)."
	@echo "Use 'make noetl-restart' if needed."
	NOETL_RUNTIME_TESTS=true $(VENV)/bin/pytest -v tests/test_http_duckdb_postgres.py

test-http-duckdb-postgres-full: noetl-stop postgres-reset-schema noetl-start
	@echo "Running full integration test for HTTP DuckDB Postgres..."
	@echo "This will stop services, reset database, restart server, register credentials, and run runtime tests"
	@sleep 2  # Give server time to start
	@echo "Registering required credentials..."
	$(MAKE) register-credential FILE=tests/fixtures/credentials/pg_local.json HOST=$(NOETL_HOST) PORT=$(NOETL_PORT)
	$(MAKE) register-credential FILE=tests/fixtures/credentials/gcs_hmac_local.json HOST=$(NOETL_HOST) PORT=$(NOETL_PORT)
	@echo "Running runtime tests..."
	$(MAKE) test-http-duckdb-postgres-runtime

test-playbook-composition: test-setup
	$(VENV)/bin/pytest -v tests/test_playbook_composition.py

test-playbook-composition-runtime: test-setup
	@echo "Running playbook composition tests with runtime execution..."
	@echo "This requires a running NoETL server and registered credentials (pg_local, gcs_hmac_local)."
	@echo "Use 'make noetl-restart' and 'make register-test-credentials' if needed."
	NOETL_RUNTIME_TESTS=true $(VENV)/bin/pytest -v tests/test_playbook_composition.py

test-playbook-composition-full: noetl-stop postgres-reset-schema noetl-start
	@echo "Running full integration test for playbook composition..."
	@echo "This will stop services, reset database, restart server, register credentials, and run runtime tests"
	@sleep 2  # Give server time to start
	@echo "Registering required credentials..."
	$(MAKE) register-credential FILE=tests/fixtures/credentials/pg_local.json HOST=$(NOETL_HOST) PORT=$(NOETL_PORT)
	$(MAKE) register-credential FILE=tests/fixtures/credentials/gcs_hmac_local.json HOST=$(NOETL_HOST) PORT=$(NOETL_PORT)
	@echo "Running runtime tests..."
	$(MAKE) test-playbook-composition-runtime

test-playbook-composition-k8s: noetl-restart
	@echo "Running Kubernetes-friendly integration test for playbook composition..."
	@echo "This will restart server, register credentials, and run runtime tests (skipping DB reset)"
	@sleep 2  # Give server time to start
	@echo "Registering required credentials..."
	$(MAKE) register-credential FILE=tests/fixtures/credentials/pg_local.json HOST=$(NOETL_HOST) PORT=$(NOETL_PORT)
	$(MAKE) register-credential FILE=tests/fixtures/credentials/gcs_hmac_local.json HOST=$(NOETL_HOST) PORT=$(NOETL_PORT)
	@echo "Running runtime tests..."
	$(MAKE) test-playbook-composition-runtime

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


.PHONY: start-server stop-server worker-start worker-stop

.PHONY: start-server stop-server noetl-start noetl-stop

start-server:
	@mkdir -p logs
	@set -a; \
	if [ -f .env ]; then . .env; fi; \
	if [ -f .env.server ]; then . .env.server; fi; \
	set +a; \
	# Optional schema init: prefer NOETL_INIT_DB=true; fallback to NOETL_SCHEMA_VALIDATE=true for backward compat
	INIT_DB_FLAG=""; \
	if [ "$${NOETL_INIT_DB:-}" = "true" ]; then \
	  INIT_DB_FLAG="--init-db"; \
	elif [ "$${NOETL_SCHEMA_VALIDATE:-}" = "true" ]; then \
	  INIT_DB_FLAG="--init-db"; \
	fi; \
	mkdir -p ~/.noetl; \
	cli="$(VENV)/bin/noetl"; \
	if [ ! -x "$$cli" ]; then cli="noetl"; fi; \
	if command -v setsid >/dev/null 2>&1; then \
	  setsid nohup "$$cli" server start $$INIT_DB_FLAG </dev/null >> logs/server.log 2>&1 & \
	else \
	  nohup "$$cli" server start $$INIT_DB_FLAG </dev/null >> logs/server.log 2>&1 & \
	fi; \
	sleep 3; \
	if [ -f ~/.noetl/noetl_server.pid ] && ps -p $$(cat ~/.noetl/noetl_server.pid) >/dev/null 2>&1; then \
	  echo "NoETL server started: PID=$$(cat ~/.noetl/noetl_server.pid) | Port: $(NOETL_PORT) | logs at logs/server.log"; \
	else \
	  echo "Server failed to stay up. Last 50 log lines:"; \
	  tail -n 50 logs/server.log || true; \
	  exit 1; \
	fi

stop-server:
	@if [ -f ~/.noetl/noetl_server.pid ]; then \
	  pid=$$(cat ~/.noetl/noetl_server.pid); \
	  kill -TERM $$pid 2>/dev/null || true; \
	  sleep 3; \
	  if ps -p $$pid >/dev/null 2>&1; then kill -KILL $$pid 2>/dev/null || true; fi; \
	  rm -f ~/.noetl/noetl_server.pid; \
	  rm -f logs/server.pid; \
	  echo "NoETL server stop: PID=$$pid"; \
	else \
	  $(VENV)/bin/noetl server stop -f || noetl server stop -f || true; \
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
			cli="$(VENV)/bin/noetl"; if [ ! -x "$$cli" ]; then cli="noetl"; fi; \
			nohup "$$cli" worker start > "$$log_file" 2>&1 & \
		sleep 1; \
		pid_file=$$HOME/.noetl/noetl_worker_$${worker_name}.pid; \
		if [ -f $$pid_file ]; then \
			echo "NoETL worker started: PID=$$(cat $$pid_file) | logs at $$log_file"; \
		else \
			echo "Worker failed to start — check $$log_file"; \
		fi'

worker-stop:
	@echo "Stopping NoETL workers..."
	-@$(VENV)/bin/noetl worker stop || noetl worker stop || true


clean-logs:
	@rm -rf logs/*

register-examples:
	examples/register_examples.sh $(PORT) $(HOST)

register-test-playbooks:
	tests/fixtures/register_test_playbooks.sh $(PORT) $(HOST)

start-workers:
	scripts/start_workers.sh

stop-workers:
	scripts/stop_workers.sh

noetl-start: clean-logs start-server start-workers register-examples

noetl-stop: stop-workers stop-server

noetl-restart: noetl-stop noetl-start server-status

.PHONY: noetl-run noetl-execute noetl-execute-status noetl-execute-watch noetl-validate-status

NOETL_BIN ?= python -m noetl.main
PLAYBOOK ?= examples/weather_loop_example
HOST ?= localhost
PORT ?= 8082
ID ?=

.ONESHELL:
SHELL := /bin/bash
.SHELLFLAGS := -eo pipefail -c

# noetl execute status "$(noetl execute playbook "examples/weather_loop_example" --host localhost --port 8082 --json | tee >(jq -C . >&2) | jq -r '.result.execution_id // .execution_id // .id')" --host localhost --port 8082 --json | jq -C .

noetl-run:
	@cli="$(VENV)/bin/noetl"; \
	if [ ! -x "$$cli" ]; then cli="noetl"; fi; \
	out="$$("$$cli" execute playbook $(PLAYBOOK) --host $(HOST) --port $(PORT) --json 2>/dev/null)"; \
	if [ -z "$$out" ]; then \
	  echo "Failed to start execution or parse execution_id" >&2; exit 1; \
	fi; \
	printf '%s\n' "$$out" | jq -C . >&2 || true; \
	eid="$$(printf '%s\n' "$$out" | jq -r '.result.execution_id // .execution_id // .id' || true)"; \
	if [[ -z "$$eid" || "$$eid" == "null" ]]; then \
	  echo "Failed to start execution or parse execution_id" >&2; \
	  exit 1; \
	fi; \
	"$$cli" execute status "$$eid" --host $(HOST) --port $(PORT) --json | jq -C .

noetl-execute:
	@cli="$(VENV)/bin/noetl"; if [ ! -x "$$cli" ]; then cli="noetl"; fi; \
	set +e; out="$$( $$cli execute playbook $(PLAYBOOK) --host $(HOST) --port $(PORT) --json 2>&1 )"; rc=$$?; set -e; \
	if [ $$rc -ne 0 ] && ! printf '%s\n' "$$out" | grep -q '{'; then \
	  set +e; out2="$$( $$cli execute playbook $(PLAYBOOK) --host $(HOST) --port $(PORT) 2>&1 )"; rc2=$$?; set -e; \
	  json1="$$(printf '%s\n' "$$out2" | sed -n 's/.*\({.*}\).*/\1/p' | head -n1)"; \
	  if [ -n "$$json1" ]; then printf '%s\n' "$$json1" | jq -C . || printf '%s\n' "$$json1"; else printf '%s\n' "$$out2"; fi; \
	  exit $$rc2; \
	elif printf '%s\n' "$$out" | jq -e . >/dev/null 2>&1; then \
	  printf '%s\n' "$$out" | jq -C .; \
	else \
	  printf '%s\n' "$$out"; \
	fi;
	@if [ "$${rc:-1}" -eq 0 ]; then \
		 eid="$$(printf '%s\n' "$$out" | jq -r '.result.execution_id // .execution_id // .id // empty' 2>/dev/null)"; \
	  if [ -n "$$eid" ] && [ "$$eid" != "null" ]; then \
	    echo "Detected execution_id=$$eid; exporting logs (workflow, transition, event_log, queue) to logs/"; \
	    $(MAKE) export-transition ID=$$eid >/dev/null 2>&1 || true; \
	    $(MAKE) export-workflow ID=$$eid >/dev/null 2>&1 || true; \
	    $(MAKE) export-event-log ID=$$eid >/dev/null 2>&1 || true; \
	    $(MAKE) export-queue ID=$$eid >/dev/null 2>&1 || true; \
		  fi; \
	fi;
	@exit $$rc

noetl-execute-status:
	@cli="$(VENV)/bin/noetl"; if [ ! -x "$$cli" ]; then cli="noetl"; fi; \
	set +e; out="$$( $$cli execute status $(ID) --host $(HOST) --port $(PORT) --json 2>&1 )"; rc=$$?; set -e; \
	if printf '%s\n' "$$out" | jq -e . >/dev/null 2>&1; then \
	  printf '%s\n' "$$out" | jq -C .; \
	else \
	  printf '%s\n' "$$out"; \
	fi; \
	exit $$rc

noetl-execute-watch:
	@if [ -z "$(ID)" ]; then \
	  echo "Usage: make noetl-execute-watch ID=<execution_id> [HOST=localhost] [PORT=8082]"; \
	  exit 1; \
	fi
	@cli="$(VENV)/bin/noetl"; if [ ! -x "$$cli" ]; then cli="noetl"; fi; \
	echo "Watching execution $(ID) at $(HOST):$(PORT) (Ctrl-C to stop)"; \
	while true; do \
	  set +e; out_json="$$( $$cli execute status $(ID) --host $(HOST) --port $(PORT) --json 2>&1 )"; rc=$$?; set -e; \
	  if printf '%s\n' "$$out_json" | jq -e . >/dev/null 2>&1; then \
	    status="$$(printf '%s\n' "$$out_json" | jq -r '.status // .result.status // .normalized_status // "unknown"')"; \
	    evcount="$$(printf '%s\n' "$$out_json" | jq -r '.events | length // 0')"; \
	    last_line="$$(printf '%s\n' "$$out_json" | jq -r '.events[-1] | select(.) | (.timestamp // "") + "  " + (.node_name // "") + " (" + (.event_type // "") + ") " + ((.status // .normalized_status // .result.status // "") | tostring)')"; \
	    echo "status: $$status | events: $$evcount"; \
	    if [ -n "$$last_line" ]; then echo "last:   $$last_line"; fi; \
	    n="$(LAST)"; \
	    if [ -n "$$n" ] && [ "$$n" -gt 0 ] 2>/dev/null; then \
	      echo "last $$n events:"; \
	      printf '%s\n' "$$out_json" | jq -r --argjson n "$$n" '(.events // []) as $$e | (if ($$e|length)>0 then ($$e | (if (length > $$n) then .[-$$n:] else . end) | map((.timestamp // "") + "  " + (.node_name // "") + " (" + (.event_type // "") + ") " + ((.status // .normalized_status // .result.status // "")|tostring)) | .[]) else empty end)'; \
	    fi; \
	    case "$$status" in completed|failed|error|canceled) break;; esac; \
	  else \
	    if [ $$rc -ne 0 ]; then \
	      set +e; out_plain="$$( $$cli execute status $(ID) --host $(HOST) --port $(PORT) 2>&1 )"; rc2=$$?; set -e; \
	      json_line="$$(printf '%s\n' "$$out_plain" | sed -n 's/.*\({.*}\).*/\1/p' | head -n1)"; \
	      if [ -n "$$json_line" ]; then \
	        printf '%s\n' "$$json_line" | jq -C . || printf '%s\n' "$$json_line"; \
	      else \
	        printf '%s\n' "$$out_plain"; \
	      fi; \
	      break; \
	    else \
	      printf '%s\n' "$$out_json"; \
	    fi; \
	  fi; \
	  sleep 1; \
	done

noetl-validate-status:
	@file="$(FILE)"; if [ -z "$$file" ]; then file="status.json"; fi; \
	if [ ! -f "$$file" ]; then \
	  echo "Usage: make noetl-validate-status FILE=/path/to/status.json"; \
	  echo "Error: file not found: $$file"; \
	  exit 1; \
	fi; \
	clean_file="$$file.clean"; \
	sed -E 's/\x1b\[[0-9;]*m//g' "$$file" > "$$clean_file"; \
	jq -r -f scripts/status_validate.jq "$$clean_file"

# === Export execution data to JSON files under logs/ ===
.PHONY: export-event-log export-queue export-runtime export-execution-logs

# Usage:
#   make export-execution-logs ID=<execution_id>
#   or individually:
#   make export-event-log ID=<execution_id>
#   make export-queue ID=<execution_id>
#   make export-runtime

export-event-log:
	@mkdir -p logs
	@set -a; [ -f .env ] && . .env; set +a; \
	export PGHOST=$${POSTGRES_HOST:-$$PGHOST} PGPORT=$${POSTGRES_PORT:-$$PGPORT} PGUSER=$${POSTGRES_USER:-$$PGUSER} PGPASSWORD=$${POSTGRES_PASSWORD:-$$PGPASSWORD} PGDATABASE=$${POSTGRES_DB:-$$PGDATABASE}; \
	if [ -z "$(ID)" ]; then \
	  echo "ID not provided; selecting latest execution_id..."; \
	  export ID=$$(psql -Atc "SELECT execution_id FROM noetl.event WHERE event_type IN ('execution_start','playbook_started') ORDER BY timestamp DESC LIMIT 1"); \
	fi; \
	psql -v ON_ERROR_STOP=1 -Atc "WITH rows AS (SELECT execution_id, event_id, parent_event_id, parent_execution_id, timestamp, event_type, node_id, node_name, node_type, status, duration, context, result, meta, error, loop_id, loop_name, iterator, items, current_index, current_item, worker_id, distributed_state, context_key, context_value, trace_component, stack_trace FROM noetl.event WHERE execution_id = $(ID) ORDER BY timestamp) SELECT coalesce(json_agg(row_to_json(rows)),'[]'::json) FROM rows;" > logs/event.json; \
	ln -sf event.json logs/event_log.json; \
	[ -s logs/event.json ] && (jq . logs/event.json >/dev/null 2>&1 && jq . logs/event.json > logs/event.json.tmp && mv logs/event.json.tmp logs/event.json || true) || true; \
	echo "Wrote logs/event.json (symlinked to event_log.json) for execution $(ID)"

export-queue:
	@mkdir -p logs
	@set -a; [ -f .env ] && . .env; set +a; \
	export PGHOST=$${POSTGRES_HOST:-$$PGHOST} PGPORT=$${POSTGRES_PORT:-$$PGPORT} PGUSER=$${POSTGRES_USER:-$$PGUSER} PGPASSWORD=$${POSTGRES_PASSWORD:-$$PGPASSWORD} PGDATABASE=$${POSTGRES_DB:-$$PGDATABASE}; \
	if [ -z "$(ID)" ]; then \
	  echo "ID not provided; selecting latest execution_id..."; \
	  export ID=$$(psql -Atc "SELECT execution_id FROM noetl.event WHERE event_type IN ('execution_start','playbook_started') ORDER BY timestamp DESC LIMIT 1"); \
	fi; \
	# Include queue rows for the parent execution and any child executions started with meta.parent_execution_id = $(ID)
	psql -v ON_ERROR_STOP=1 -Atc "WITH all_execs AS ( \
	  SELECT $(ID)::bigint AS execution_id \
	  UNION \
	  SELECT DISTINCT execution_id \
	  FROM noetl.event \
	  WHERE event_type = 'execution_start' \
	    AND meta::text LIKE '%"parent_execution_id": "$(ID)"%' \
	), q AS ( \
	  SELECT id, created_at, available_at, lease_until, last_heartbeat, status, execution_id, node_id, action, context, priority, attempts, max_attempts, worker_id \
	  FROM noetl.queue \
	  WHERE execution_id IN (SELECT execution_id FROM all_execs) \
	  ORDER BY id \
	) SELECT coalesce(json_agg(row_to_json(q)),'[]'::json) FROM q;" > logs/queue.json; \
	[ -s logs/queue.json ] && (jq . logs/queue.json >/dev/null 2>&1 && jq . logs/queue.json > logs/queue.json.tmp && mv logs/queue.json.tmp logs/queue.json || true) || true; \
	echo "Wrote logs/queue.json for execution $(ID)"

export-runtime:
	@mkdir -p logs
	@set -a; [ -f .env ] && . .env; set +a; \
	export PGHOST=$${POSTGRES_HOST:-$$PGHOST} PGPORT=$${POSTGRES_PORT:-$$PGPORT} PGUSER=$${POSTGRES_USER:-$$PGUSER} PGPASSWORD=$${POSTGRES_PASSWORD:-$$PGPASSWORD} PGDATABASE=$${POSTGRES_DB:-$$PGDATABASE}; \
	psql -v ON_ERROR_STOP=1 -Atc "SELECT coalesce(json_agg(row_to_json(r)),'[]'::json) FROM noetl.runtime r;" > logs/runtime.json; \
	[ -s logs/runtime.json ] && (jq . logs/runtime.json >/dev/null 2>&1 && jq . logs/runtime.json > logs/runtime.json.tmp && mv logs/runtime.json.tmp logs/runtime.json || true) || true; \
	echo "Wrote logs/runtime.json"

export-execution-logs: export-event-log export-queue export-runtime

# Convenience: export logs for the most recent execution when ID is not provided
.PHONY: export-latest
export-latest:
	@$(MAKE) -s export-event-log
	@$(MAKE) -s export-queue
	@$(MAKE) -s export-runtime
	@echo "Exported latest execution logs to logs/event.json and logs/queue.json"

export-transition:
	@mkdir -p logs
	@set -a; [ -f .env ] && . .env; set +a; \
	export PGHOST=$${POSTGRES_HOST:-$$PGHOST} PGPORT=$${POSTGRES_PORT:-$$PGPORT} PGUSER=$${POSTGRES_USER:-$$PGUSER} PGPASSWORD=$${POSTGRES_PASSWORD:-$$PGPASSWORD} PGDATABASE=$${POSTGRES_DB:-$$PGDATABASE}; \
	psql -v ON_ERROR_STOP=1 -Atc "SELECT coalesce(json_agg(row_to_json(t)),'[]'::json) FROM noetl.transition t WHERE execution_id = $(ID)" > logs/transition.json; \
	[ -s logs/transition.json ] && (jq . logs/transition.json >/dev/null 2>&1 && jq . logs/transition.json > logs/transition.json.tmp && mv logs/transition.json.tmp logs/transition.json || true) || true; \
	echo "Wrote logs/transition.json"

export-workflow:
	@mkdir -p logs
	@set -a; [ -f .env ] && . .env; set +a; \
	export PGHOST=$${POSTGRES_HOST:-$$PGHOST} PGPORT=$${POSTGRES_PORT:-$$PGPORT} PGUSER=$${POSTGRES_USER:-$$PGUSER} PGPASSWORD=$${POSTGRES_PASSWORD:-$$PGPASSWORD} PGDATABASE=$${POSTGRES_DB:-$$PGDATABASE}; \
	psql -v ON_ERROR_STOP=1 -Atc "SELECT coalesce(json_agg(row_to_json(w)),'[]'::json) FROM noetl.workflow w WHERE execution_id = $(ID)" > logs/workflow.json; \
	[ -s logs/workflow.json ] && (jq . logs/workflow.json >/dev/null 2>&1 && jq . logs/workflow.json > logs/workflow.json.tmp && mv logs/workflow.json.tmp logs/workflow.json || true) || true; \
	echo "Wrote logs/workflow.json"

export-workbook:
	@mkdir -p logs
	@set -a; [ -f .env ] && . .env; set +a; \
	export PGHOST=$${POSTGRES_HOST:-$$PGHOST} PGPORT=$${POSTGRES_PORT:-$$PGPORT} PGUSER=$${POSTGRES_USER:-$$PGUSER} PGPASSWORD=$${POSTGRES_PASSWORD:-$$PGPASSWORD} PGDATABASE=$${POSTGRES_DB:-$$PGDATABASE}; \
	psql -v ON_ERROR_STOP=1 -Atc "SELECT coalesce(json_agg(row_to_json(wb)),'[]'::json) FROM noetl.workbook wb WHERE execution_id = $(ID)" > logs/workbook.json; \
	[ -s logs/workbook.json ] && (jq . logs/workbook.json >/dev/null 2>&1 && jq . logs/workbook.json > logs/workbook.json.tmp && mv logs/workbook.json.tmp logs/workbook.json || true) || true; \
	echo "Wrote logs/workbook.json"

# === Credential helpers ===
.PHONY: register-credential register-test-credentials

register-credential:
	@if [ -z "$(FILE)" ]; then \
	  echo "Usage: make register-credential FILE=tests/fixtures/credentials/pg_local.json [HOST=localhost] [PORT=8082]"; \
	  exit 1; \
	fi; \
	url="http://$(HOST):$(PORT)/api/credentials"; \
	echo "POST $$url < $(FILE)"; \
	if command -v jq >/dev/null 2>&1; then \
	  curl -sS -X POST "$$url" -H 'Content-Type: application/json' --data-binary @"$(FILE)" | jq -C .; \
	else \
	  curl -sS -X POST "$$url" -H 'Content-Type: application/json' --data-binary @"$(FILE)"; \
	fi

register-test-credentials:
	@set -e; \
	shopt -s nullglob; \
	for f in tests/fixtures/credentials/*.json; do \
	  echo "Registering credential payload: $$f"; \
	  $(MAKE) -s register-credential FILE="$$f" HOST=$(HOST) PORT=$(PORT); \
	done; \
	shopt -u nullglob; \
	echo "Credential payloads registered."

export-all-event-log:
	@mkdir -p logs
	@set -a; [ -f .env ] && . .env; set +a; \
	export PGHOST=$${POSTGRES_HOST:-$$PGHOST} PGPORT=$${POSTGRES_PORT:-$$PGPORT} PGUSER=$${POSTGRES_USER:-$$PGUSER} PGPASSWORD=$${POSTGRES_PASSWORD:-$$PGPASSWORD} PGDATABASE=$${POSTGRES_DB:-$$PGDATABASE}; \
	psql -v ON_ERROR_STOP=1 -Atc "WITH rows AS (SELECT execution_id, event_id, parent_event_id, timestamp, event_type, node_id, node_name, node_type, status, duration, context, result, meta, error, loop_id, loop_name, iterator, items, current_index, current_item, worker_id, distributed_state, context_key, context_value, stack_trace FROM noetl.event ORDER BY timestamp) SELECT coalesce(json_agg(row_to_json(rows)),'[]'::json) FROM rows;" > logs/event.json; \
	ln -sf event.json logs/event_log.json; \
	[ -s logs/event.json ] && (jq . logs/event.json >/dev/null 2>&1 && jq . logs/event.json > logs/event.json.tmp && mv logs/event.json.tmp logs/event.json || true) || true; \
	echo "Wrote logs/event.json (symlinked to event_log.json)"

noetl-dump-lineage:
	@if [ -z "$(ID)" ]; then \
	  echo "Usage: make noetl-dump-lineage ID=<parent_execution_id> [HOST=localhost] [PORT=8082]"; \
	  exit 1; \
	fi; \
	url="http://$(HOST):$(PORT)/api/events/by-execution/$(ID)"; \
	printf "Parent: %s\n" "$(ID)"; \
	# Dump loop_iteration events and their event_ids
	curl -s "$${url}" | sed -E 's/\x1b\[[0-9;]*m//g' > /tmp/ev_$(ID).json; \
	jq -r '\nEvents: ' /tmp/ev_$(ID).json >/dev/null 2>&1 || true; \
	echo "Loop iterations:"; \
	jq -r '.events[] | select(.event_type=="loop_iteration") | "  iter: " + (.node_name // "") + " idx=" + ((.context.index // 0)|tostring) + " event_id=" + (.event_id // "")' /tmp/ev_$(ID).json || true; \
	# Attempt to dump child executions discovered via child execution_start with parent_execution_id
	echo "Children:"; \
	# naive scan: iterate all executions and print those with matching parent_execution_id
	curl -s "http://$(HOST):$(PORT)/api/executions" | jq -r '.[]?.id' 2>/dev/null | while read -r cid; do \
	  [ -z "$$cid" ] && continue; \
	  curl -s "http://$(HOST):$(PORT)/api/events/by-execution/$$cid" | sed -E 's/\x1b\[[0-9;]*m//g' > /tmp/ev_$$cid.json 2>/dev/null || true; \
	  pid=$$(jq -r '.events[]?|select(.event_type=="execution_start")|.metadata.parent_execution_id // empty' /tmp/ev_$$cid.json 2>/dev/null); \
	  pstep=$$(jq -r '.events[]?|select(.event_type=="execution_start")|.metadata.parent_step // empty' /tmp/ev_$$cid.json 2>/dev/null); \
	  if [ "$$pid" = "$(ID)" ]; then \
	    term=$$(jq -r '.events[]?|select(.event_type=="execution_complete")|.output_result // {} | @json' /tmp/ev_$$cid.json 2>/dev/null); \
	    echo "  child_execution_id=$$cid parent_step=$$pstep result=$$term"; \
	  fi; \
	done



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
	@echo "  - You can now run 'make start-server' to start the NoETL server"
	@echo "  - Run 'make k8s-postgres-port-forward-stop' to stop port forwarding"

# === Platform Deployment Targets ===
.PHONY: k8s-platform-deploy
k8s-platform-deploy:
	@echo "Deploying complete NoETL platform..."
	@./k8s/deploy-platform.sh
	@echo ""
	@echo "🎉 NoETL Platform deployed successfully!"
	@echo "📋 Available endpoints:"
	@echo "  - Health Check: http://localhost:30082/api/health"
	@echo "  - API Documentation: http://localhost:30082/docs"
	@echo "  - Main API: http://localhost:30082/"
	@echo ""

.PHONY: redeploy-noetl
redeploy-noetl:
	@echo "Redeploying NoETL with metrics functionality..."
	@echo "This will preserve observability services and reset schema safely."
	@./k8s/redeploy-noetl.sh
	@echo ""
	@echo "🎉 NoETL redeployed successfully with metrics!"
	@echo "📊 New metrics endpoints:"
	@echo "  - Prometheus metrics: http://localhost:30082/api/metrics/prometheus"
	@echo "  - Metrics query API: http://localhost:30082/api/metrics/query"
	@echo "  - Self-report: http://localhost:30082/api/metrics/self-report"
	@echo ""
	@echo "🚀 Quick start:"
	@echo "  curl http://localhost:30082/api/health"
	@echo "  curl http://localhost:30082/api/catalog/playbooks"
	@echo ""
	@echo "🛠️  CLI access:"
	@echo "  kubectl exec -it deployment/noetl -- noetl --help"
	@echo ""
	@echo "🗑️  To clean up:"
	@echo "  make k8s-platform-clean"

.PHONY: k8s-platform-clean  
k8s-platform-clean:
	@echo "Cleaning up NoETL platform deployment..."
	@if ! $(KUBECTL) cluster-info >/dev/null 2>&1; then \
		echo "No active Kubernetes cluster detected. Skipping cleanup."; \
	else \
		echo "Deleting NoETL deployment..."; \
		$(KUBECTL) delete deployment noetl --ignore-not-found || true; \
		$(KUBECTL) delete service noetl --ignore-not-found || true; \
		$(KUBECTL) delete configmap noetl-config --ignore-not-found || true; \
		$(KUBECTL) delete secret noetl-secret --ignore-not-found || true; \
		echo "Deleting Postgres deployment..."; \
		$(KUBECTL) -n postgres delete deployment postgres --ignore-not-found || true; \
		$(KUBECTL) -n postgres delete service postgres --ignore-not-found || true; \
		$(KUBECTL) -n postgres delete configmap postgres-config --ignore-not-found || true; \
		$(KUBECTL) -n postgres delete configmap postgres-config-files --ignore-not-found || true; \
		$(KUBECTL) -n postgres delete secret postgres-secret --ignore-not-found || true; \
		$(KUBECTL) -n postgres delete pvc postgres-pvc --ignore-not-found || true; \
		$(KUBECTL) delete pv postgres-pv --ignore-not-found || true; \
		$(KUBECTL) delete namespace postgres --ignore-not-found || true; \
		echo "Deleting Kind cluster..."; \
		$(KIND) delete cluster --name $(KIND_CLUSTER) || true; \
		echo "Platform cleanup completed."; \
	fi

.PHONY: k8s-platform-status
k8s-platform-status:
	@echo "NoETL Platform Status:"
	@echo "======================"
	@if ! $(KUBECTL) cluster-info >/dev/null 2>&1; then \
		echo "❌ No active Kubernetes cluster detected."; \
		echo "   Run 'make k8s-platform-deploy' to deploy the platform."; \
	else \
		echo "📊 Cluster Info:"; \
		$(KUBECTL) cluster-info | head -2 || true; \
		echo ""; \
		echo "🐘 Postgres Status:"; \
		$(KUBECTL) get pods -n postgres -l app=postgres || echo "   No Postgres pods found"; \
		echo ""; \
		echo "🚀 NoETL Status:"; \
		$(KUBECTL) get pods -l app=noetl || echo "   No NoETL pods found"; \
		echo ""; \
		echo "🌐 Services:"; \
		$(KUBECTL) get svc | grep -E "(noetl|TYPE)" || echo "   No NoETL services found"; \
		echo ""; \
		echo "🔗 Quick Access:"; \
		if $(KUBECTL) get pods -l app=noetl | grep -q "1/1.*Running"; then \
			echo "  ✅ Health Check: curl http://localhost:30082/api/health"; \
			echo "  📚 API Docs: http://localhost:30082/docs"; \
		else \
			echo "  ⏳ NoETL is not ready yet. Check pod status above."; \
		fi; \
	fi

.PHONY: k8s-platform-test
k8s-platform-test:
	@echo "Testing NoETL platform with a simple playbook..."
	@if ! $(KUBECTL) get pods -l app=noetl | grep -q "1/1.*Running"; then \
		echo "❌ NoETL is not running. Run 'make k8s-platform-deploy' first."; \
		exit 1; \
	fi
	@echo "Creating test playbook..."
	@mkdir -p /tmp/noetl-test
	@echo 'name: hello-world-test' > /tmp/noetl-test/hello-world-test.yaml
	@echo 'version: "1.0.0"' >> /tmp/noetl-test/hello-world-test.yaml
	@echo 'description: "Test playbook for NoETL platform"' >> /tmp/noetl-test/hello-world-test.yaml
	@echo '' >> /tmp/noetl-test/hello-world-test.yaml
	@echo 'steps:' >> /tmp/noetl-test/hello-world-test.yaml
	@echo '  - name: test_step' >> /tmp/noetl-test/hello-world-test.yaml
	@echo '    type: python' >> /tmp/noetl-test/hello-world-test.yaml
	@echo '    parameters:' >> /tmp/noetl-test/hello-world-test.yaml
	@echo '      code: |' >> /tmp/noetl-test/hello-world-test.yaml
	@echo '        print("🎉 NoETL Platform is working!")' >> /tmp/noetl-test/hello-world-test.yaml
	@echo '        print("✅ Python step executed successfully")' >> /tmp/noetl-test/hello-world-test.yaml
	@echo '        return {"status": "success", "message": "Platform test completed"}' >> /tmp/noetl-test/hello-world-test.yaml
	@echo "Copying playbook to container..."
	@$(KUBECTL) cp /tmp/noetl-test/hello-world-test.yaml $$($(KUBECTL) get pods -l app=noetl -o jsonpath='{.items[0].metadata.name}'):/opt/noetl/data/hello-world-test.yaml
	@echo "Registering playbook..."
	@$(KUBECTL) exec deployment/noetl -- noetl register /opt/noetl/data/hello-world-test.yaml --host localhost --port 8082
	@echo "Executing playbook..."
	@$(KUBECTL) exec deployment/noetl -- noetl run hello-world-test --host localhost --port 8082
	@echo "✅ Platform test completed successfully!"

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
	echo "Applying schema DDL via noetl CLI..."; \
	cli="$(VENV)/bin/noetl"; \
	if [ ! -x "$$cli" ]; then cli="noetl"; fi; \
	if $$cli db apply-schema --ensure-role; then \
	  echo "Schema applied using packaged DDL."; \
	else \
	  echo "noetl CLI apply-schema failed; trying local DDL fallback..."; \
	  if [ -f noetl/database/ddl/postgres/schema_ddl.sql ]; then \
	    psql -v ON_ERROR_STOP=1 -f noetl/database/ddl/postgres/schema_ddl.sql ; \
	  else \
	    echo "Could not apply schema (no CLI and no local DDL)."; exit 1; \
	  fi; \
	fi


#[GCP]##################################################################################################################
.PHONY: gcp-credentials
gcp-credentials:
	@mkdir -p ./secrets
	@gcloud auth application-default login
	@rmdir ./secrets/application_default_credentials.json
	@cp $$HOME/.config/gcloud/application_default_credentials.json ./secrets/application_default_credentials.json
	@echo "Credentials copied to ./secrets/application_default_credentials.json"

.PHONY: observability-deploy observability-redeploy observability-port-forward-start observability-port-forward-stop observability-port-forward-status observability-grafana-credentials observability-provision-dashboards observability-import-dashboards observability-provision-datasources unified-deploy unified-recreate-all unified-health-check unified-grafana-credentials unified-port-forward-start unified-port-forward-stop unified-port-forward-status
observability-deploy:
	@bash k8s/observability/deploy.sh

observability-redeploy:
	@bash k8s/observability/redeploy.sh

observability-port-forward-start:
	@bash k8s/observability/port-forward.sh start

observability-port-forward-stop:
	@bash k8s/observability/port-forward.sh stop

observability-port-forward-status:
	@bash k8s/observability/port-forward.sh status

observability-grafana-credentials:
	@if kubectl get ns noetl-platform >/dev/null 2>&1; then \
		echo "[INFO] Found unified deployment, using noetl-platform namespace"; \
		bash k8s/observability/grafana-credentials.sh noetl-platform; \
	elif kubectl get ns observability >/dev/null 2>&1; then \
		echo "[INFO] Found legacy deployment, using observability namespace"; \
		bash k8s/observability/grafana-credentials.sh observability; \
	else \
		echo "[ERROR] Neither noetl-platform nor observability namespace found."; \
		echo "Hint: Deploy with './k8s/deploy-unified-platform.sh' or 'make observability-deploy'"; \
		exit 1; \
	fi

observability-provision-dashboards:
	@bash k8s/observability/provision-grafana.sh observability

observability-provision-datasources:
	@bash k8s/observability/provision-datasources.sh observability

observability-import-dashboards:
	@bash k8s/observability/import-dashboards.sh observability --wait

# Unified deployment targets (recommended)
unified-deploy:
	@echo "[INFO] Deploying unified NoETL platform with observability"
	@bash k8s/deploy-unified-platform.sh

unified-grafana-credentials:
	@echo "[INFO] Getting Grafana credentials for unified deployment"
	@bash k8s/observability/grafana-credentials.sh noetl-platform

unified-port-forward-start:
	@echo "[INFO] Starting port-forwards for unified deployment"
	@bash k8s/observability/port-forward-unified.sh start

unified-port-forward-stop:
	@echo "[INFO] Stopping port-forwards for unified deployment"
	@bash k8s/observability/port-forward-unified.sh stop

unified-port-forward-status:
	@echo "[INFO] Checking port-forward status for unified deployment"
	@bash k8s/observability/port-forward-unified.sh status

unified-recreate-all:
	@echo "[INFO] Complete recreation: cleanup + rebuild + redeploy everything"
	@echo "[INFO] This will delete all clusters, rebuild Docker images, and redeploy from scratch"
	@echo "y" | bash k8s/recreate-all.sh

unified-health-check:
	@echo "[INFO] Running health check for unified deployment"
	@bash k8s/health-check.sh
