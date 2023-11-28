GHCR_USERNAME=noetl
VERSION="0.1.0"
K8S_DIR=k8s
define get_nats_port
$(shell kubectl get svc nats -n nats -o=jsonpath='{.spec.ports[0].nodePort}')
endef

NATS_URL=nats://localhost:$(call get_nats_port)
# NATS_URL=nats://localhost:32222
CLI_SERVICE_NAME=noetl-cli
API_SERVICE_NAME=noetl-api
DISPATCHER_SERVICE_NAME=noetl-dispatcher
REGISTRAR_SERVICE_NAME=noetl-registrar
CLI_DOCKERFILE=docker/cli/Dockerfile-cli
API_DOCKERFILE=docker/api/Dockerfile-api
DISPATCHER_DOCKERFILE=docker/dispatcher/Dockerfile-dispatcher
REGISTRAR_DOCKERFILE=docker/registrar/Dockerfile-registrar

PYTHON := python
VENV_NAME := .venv
REQUIREMENTS := requirements.txt

venv:
	@echo "Creating Python virtual environment..."
	$(PYTHON) -m venv $(VENV_NAME)
	@. $(VENV_NAME)/bin/activate; \
	pip3 install --upgrade pip; \
	deactivate
	@echo "Virtual environment created."

requirements:
	@echo "Installing python requirements..."
	@. $(VENV_NAME)/bin/activate; \
	pip3 install -r $(REQUIREMENTS); \
	$(PYTHON) -m spacy download en_core_web_sm; \
	echo "Requirements installed."

activate-venv:
	@. $(VENV_NAME)/bin/activate;

activate-help:
	@echo "To activate the virtual environment:"
	@echo "source $(VENV_NAME)/bin/activate"

.PHONY: venv requirements activate-venv activate-help


all: build-all push-all delete-all deploy-all

build-all: build-api build-dispatcher build-registrar build-cli
.PHONY: build-api build-dispatcher build-registrar build-cli build-all clean

build-cli:
	docker build --build-arg PRJ_PATH=../../ -f $(CLI_DOCKERFILE) -t $(CLI_SERVICE_NAME) .

build-api:
	docker build --build-arg PRJ_PATH=../../ -f $(API_DOCKERFILE) -t $(API_SERVICE_NAME) .

build-dispatcher:
	docker build --build-arg PRJ_PATH=../../ -f $(DISPATCHER_DOCKERFILE) -t $(DISPATCHER_SERVICE_NAME) .

build-registrar:
	docker build --build-arg PRJ_PATH=../../ -f $(REGISTRAR_DOCKERFILE) -t $(REGISTRAR_SERVICE_NAME) .

build-shell-handler:
	docker build --build-arg PRJ_PATH=../../ -f $(REGISTRAR_DOCKERFILE) -t $(REGISTRAR_SERVICE_NAME) .


clean:
	docker rmi $$(docker images -f "dangling=true" -q)

docker-login:
	@echo "Logging in to GitHub Container Registry"
	@echo $$PAT | docker login ghcr.io -u noetl --password-stdin

tag-cli:
	@echo "Tagging CLI image"
	@docker tag $(CLI_SERVICE_NAME) ghcr.io/$(GHCR_USERNAME)/noetl-cli:$(VERSION)

tag-api:
	@echo "Tagging API image"
	@docker tag $(API_SERVICE_NAME) ghcr.io/$(GHCR_USERNAME)/noetl-api:$(VERSION)

tag-dispatcher:
	@echo "Tagging Dispatcher image"
	@docker tag $(DISPATCHER_SERVICE_NAME) ghcr.io/$(GHCR_USERNAME)/noetl-dispatcher:$(VERSION)

tag-registrar:
	@echo "Tagging Registrar image"
	@docker tag $(REGISTRAR_SERVICE_NAME) ghcr.io/$(GHCR_USERNAME)/noetl-registrar:$(VERSION)

push-cli: tag-cli
	@echo "Pushing CLI image to GitHub Container Registry"
	@docker push ghcr.io/$(GHCR_USERNAME)/noetl-cli:$(VERSION)

push-api: tag-api
	@echo "Pushing API image to GitHub Container Registry"
	@docker push ghcr.io/$(GHCR_USERNAME)/noetl-api:$(VERSION)

push-dispatcher: tag-dispatcher
	@echo "Pushing Dispatcher image to GitHub Container Registry"
	@docker push ghcr.io/$(GHCR_USERNAME)/noetl-dispatcher:$(VERSION)

push-registrar: tag-registrar
	@echo "Pushing Registrar image to GitHub Container Registry"
	@docker push ghcr.io/$(GHCR_USERNAME)/noetl-registrar:$(VERSION)

push-all: push-api push-dispatcher push-registrar

.PHONY: docker-login tag-api tag-dispatcher tag-registrar push-api push-dispatcher push-registrar push-all

set-k8s-context:
	@echo "Setting Kubernetes context to docker-desktop..."
	#@kubectx docker-desktop
	@kubectl config use-context docker-desktop
	@echo "Context set to docker-desktop."

deploy-all: deploy-api deploy-dispatcher deploy-registrar
	@echo "Redeploy NoETL core services to Kubernetes"

deploy-api: set-k8s-context
	@echo "Deploying NoETL API Service"
	@kubectl apply -f $(K8S_DIR)/noetl-api/namespace.yaml
	@kubectl apply -f $(K8S_DIR)/noetl-api/deployment.yaml
	@kubectl apply -f $(K8S_DIR)/noetl-api/service.yaml
	# @kubectl apply -f $(K8S_DIR)/noetl-api/ingress.yaml

deploy-dispatcher: set-k8s-context
	@echo "Deploying NoETL Dispatcher Service"
	@kubectl config use-context docker-desktop
	@kubectl apply -f $(K8S_DIR)/noetl-dispatcher/deployment.yaml
	# @kubectl apply -f $(K8S_DIR)/noetl-dispatcher/service.yaml

deploy-registrar: set-k8s-context
	@echo "Deploying NoETL Registrar Service"
	@kubectl config use-context docker-desktop
	@kubectl apply -f $(K8S_DIR)/noetl-registrar/deployment.yaml
	# @kubectl apply -f $(K8S_DIR)/noetl-registrar/service.yaml

.PHONY: deploy-api deploy-dispatcher deploy-registrar deploy-api api-all


delete-all: set-k8s-context delete-dispatcher delete-registrar delete-api
		@echo "Delete NoETL core services to Kubernetes"

delete-api: set-k8s-context
	@echo "Deleting NoETL API Service"
	@kubectl delete -f $(K8S_DIR)/noetl-api/deployment.yaml -n noetl || true
	@kubectl delete -f $(K8S_DIR)/noetl-api/service.yaml -n noetl || true
	# @kubectl delete -f $(K8S_DIR)/noetl-api/ingress.yaml -n noetl || true
	@kubectl delete -f $(K8S_DIR)/noetl-api/namespace.yaml -n noetl || true

delete-dispatcher: set-k8s-context
	@echo "Deleting NoETL Dispatcher Service"
	@kubectl config use-context docker-desktop
	@kubectl delete -f $(K8S_DIR)/noetl-dispatcher/deployment.yaml -n noetl || true

delete-registrar: set-k8s-context
	@echo "Deleting NoETL Registrar Service"
	@kubectl config use-context docker-desktop
	@kubectl delete -f $(K8S_DIR)/noetl-registrar/deployment.yaml -n noetl || true

.PHONY: delete-all delete-api delete-dispatcher delete-registrar

api-all: delete-api build-api tag-api push-api deploy-api
	@echo "Redeploy NoETL api service to Kubernetes"


destroy-all-nats: set-k8s-context
	@echo "Destroying NATS cluster..."
	@kubectl delete namespace nats || true
	@echo "NATS cluster destroyed."

.PHONY: destroy-all-nats

delete-ingress-nginx: set-k8s-context
	@echo "Deleting ingress-nginx..."
	@helm uninstall ingress-nginx -n ingress-nginx || true
	@kubectl delete namespace ingress-nginx || true
	@echo "ingress-nginx deleted."

.PHONY: delete-ingress-nginx

install-helm:
	@echo "Installing Helm..."
	@brew install helm
	@echo "Helm installation complete."

add-nats-repo:
	@echo "Adding NATS helm repo..."
	@helm repo add nats https://nats-io.github.io/k8s/helm/charts/
	@echo "NATS helm repo added."

add-ingress-repo:
	@echo "Adding ingress-nginx helm repo..."
	@helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
	@helm repo update
	@echo "ingress-nginx helm repo added."

install-nats-tools:
	@echo "Tapping nats-io/nats-tools..."
	@brew tap nats-io/nats-tools
	@echo "Installing nats from nats-io/nats-tools..."
	@brew install nats-io/nats-tools/nats
	@echo "NATS installation complete."


install-ingress-nginx: add-ingress-repo
	@echo "Checking if ingress-nginx is already installed..."
	@if ! helm list -n ingress-nginx | grep -q ingress-nginx; then \
        echo "Installing ingress-nginx..."; \
        helm install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --create-namespace; \
        kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml; \
        echo "ingress-nginx installed."; \
    else \
        echo "ingress-nginx is already installed, skipping installation."; \
    fi

install-nats:
	@echo "Installing NATS..."
	@helm install nats nats/nats --values k8s/nats/values.yaml --namespace nats --create-namespace
	@helm install nack nats/nack --set jetstream.nats.url=nats://nats:4222 -n nats
	@echo "NATS installed."

install-nats-crd:
	@echo "Installing NATS JetStream CRDs..."
	@kubectl apply -f https://github.com/nats-io/nack/releases/latest/download/crds.yml -n nats
	@echo "NATS JetStream CRDs installed."

.PHONY: set-k8s-context install-helm install-nats-tools add-nats-repo install-ingress-nginx install-nats install-nats-crd

install-all-nats: set-k8s-context install-helm install-nats-tools add-nats-repo install-ingress-nginx install-nats install-nats-crd
	@echo "All components installed."

.PHONY: install-all-nats

nats-delete-events:
	@echo "Deleting NATS events"
	@kubectl delete -f $(K8S_DIR)/nats/events/event-stream.yaml -n nats

nats-create-events:
	@echo "Creating NATS events"
	@kubectl apply -f $(K8S_DIR)/nats/events/event-stream.yaml -n nats

nats-delete-commands:
	@echo "Deleting NATS commands"
	@kubectl delete -f $(K8S_DIR)/nats/commands/command-stream.yaml -n nats

nats-create-commands:
	@echo "Creating NATS commands"
	@kubectl apply -f $(K8S_DIR)/nats/commands/command-stream.yaml -n nats

nats-install-all-streams: set-k8s-context nats-create-events nats-create-commands

nats-delete-all-streams: set-k8s-context nats-delete-events nats-delete-commands

nats-all-streams: nats-delete-all-streams nats-install-all-streams
	@echo "Reset all NATS streams in Kubernetes"

.PHONY: nats-install-all-streams nats-delete-all-streams nats-delete-events nats-delete-commands
.PHONY: nats-create-events nats-create-commands nats-all-streams


purge-all: purge-commands purge-events nats-ls
	@echo "Purged NATS events and commands streams"

purge-commands:
	@echo "Purging NATS commands streams"
	@nats stream purge commands --force -s $(NATS_URL)

purge-events:
	@echo "Purging NATS events streams"
	@nats stream purge events --force -s $(NATS_URL)

nats-ls:
	@nats stream ls -s $(NATS_URL)

.PHONY: purge-commands purge-events purge-all stream-ls

run-api: activate-venv
	bin/api.sh

run-dispatcher: activate-venv
	bin/dispatcher.sh

run-registrar: activate-venv
	bin/registrar.sh

.PHONY: run-api run-dispatcher run-registrar

register-workflow: activate-venv
    ifeq ($(WORKFLOW),)
	    @echo "Usage: make register-workflow WORKFLOW=workflows/time/get-current-time.yaml"
    else
	    $(PYTHON) noetl/cli.py register workflow $(WORKFLOW)
    endif

list-workflows: activate-venv
	$(PYTHON) noetl/cli.py list workflows

describe-workflow: activate-venv
	$(PYTHON) noetl/cli.py describe workflow $(filter-out $@,$(MAKECMDGOALS))

run-current-time-workflow: activate-venv
	$(PYTHON) noetl/cli.py run workflow get-current-time '{"sdfasdf":"aSDfasdfasd"}'

.PHONY: register-workflow list-workflows describe-workflow run-current-time-workflow
