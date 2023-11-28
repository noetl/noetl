GHCR_USERNAME=noetl
VERSION="0.1.0"
K8S_DIR=k8s

# define get_nats_port
# $(shell kubectl get svc nats -n nats -o=jsonpath='{.spec.ports[0].nodePort}')
# endef
# NATS_URL=nats://localhost:$(call get_nats_port)

NATS_URL=nats://localhost:32222

CLI_SERVICE_NAME=noetl-cli
CLI_DOCKERFILE=docker/cli/Dockerfile-cli
CLI_VERSION=latest
CLI_SERVICE_TAG=local/$(CLI_SERVICE_NAME):$(CLI_VERSION)

API_SERVICE_NAME=noetl-api
API_DOCKERFILE=docker/api/Dockerfile-api
API_VERSION=latest
API_SERVICE_TAG=local/$(API_SERVICE_NAME):$(API_VERSION)

DISPATCHER_SERVICE_NAME=noetl-dispatcher
DISPATCHER_DOCKERFILE=docker/dispatcher/Dockerfile-dispatcher
DISPATCHER_VERSION=latest
DISPATCHER_SERVICE_TAG=local/$(DISPATCHER_SERVICE_NAME):$(DISPATCHER_VERSION)

REGISTRAR_SERVICE_NAME=noetl-registrar
REGISTRAR_DOCKERFILE=docker/registrar/Dockerfile-registrar
REGISTRAR_VERSION=latest
REGISTRAR_SERVICE_TAG=local/$(REGISTRAR_SERVICE_NAME):$(REGISTRAR_VERSION)

PYTHON := python
VENV_NAME := .venv
REQUIREMENTS := requirements.txt


.PHONY: venv requirements activate

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


#all: build-all push-all delete-all deploy-all

.PHONY: venv requirements activate-venv activate-help



#[BUILD]#######################################################################
.PHONY: build-cli remove-cli-image rebuild-cli
.PHONY: build-api remove-api-image rebuild-api
.PHONY: build-dispatcher remove-dispatcher-image rebuild-dispatcher
.PHONY: build-registrar remove-registrar-image rebuild-registrar
.PHONY: build-all rebuild-all clean

build-all: build-cli build-api build-dispatcher build-registrar
rebuild-all: rebuild-cli rebuild-api rebuild-dispatcher rebuild-registrar

build-cli:
	@echo "Building CLI image..."
	docker build --build-arg PRJ_PATH=../../ -f $(CLI_DOCKERFILE) -t $(CLI_SERVICE_TAG) .

remove-cli-image:
	@echo "Removing CLI image..."
	docker rmi $(CLI_SERVICE_TAG)

rebuild-cli: remove-cli-image build-cli


build-api:
	@echo "Building API image..."
	docker build --build-arg PRJ_PATH=../../ -f $(API_DOCKERFILE) -t $(API_SERVICE_TAG) .

remove-api-image:
	@echo "Removing API image..."
	docker rmi $(API_SERVICE_TAG)

rebuild-api: remove-api-image build-api


build-dispatcher:
	@echo "Building Dispatcher image..."
	docker build --build-arg PRJ_PATH=../../ -f $(DISPATCHER_DOCKERFILE) -t $(DISPATCHER_SERVICE_TAG) .

remove-dispatcher-image:
	@echo "Removing Dispatcher image..."
	docker rmi $(DISPATCHER_SERVICE_TAG)

rebuild-dispatcher: remove-dispatcher-image build-dispatcher


build-registrar:
	@echo "Building Registrar image..."
	docker build --build-arg PRJ_PATH=../../ -f $(REGISTRAR_DOCKERFILE) -t $(REGISTRAR_SERVICE_TAG) .

remove-registrar-image:
	@echo "Removing Registrar image..."
	docker rmi $(REGISTRAR_SERVICE_TAG)

rebuild-registrar: remove-registrar-image build-registrar


build-shell-handler:
	docker build --build-arg PRJ_PATH=../../ -f $(REGISTRAR_DOCKERFILE) -t $(REGISTRAR_SERVICE_NAME) .


clean:
	docker rmi $$(docker images -f "dangling=true" -q)


#[TAG]#######################################################################
.PHONY: tag-cli tag-api tag-dispatcher tag-registrar

tag-cli:
	@echo "Tagging CLI image"
	docker tag $(CLI_SERVICE_TAG) ghcr.io/$(GHCR_USERNAME)/noetl-cli:$(CLI_VERSION)

tag-api:
	@echo "Tagging API image"
	docker tag $(API_SERVICE_TAG) ghcr.io/$(GHCR_USERNAME)/noetl-api:$(API_VERSION)

tag-dispatcher:
	@echo "Tagging Dispatcher image"
	docker tag $(DISPATCHER_SERVICE_TAG) ghcr.io/$(GHCR_USERNAME)/noetl-dispatcher:$(DISPATCHER_VERSION)

tag-registrar:
	@echo "Tagging Registrar image"
	docker tag $(REGISTRAR_SERVICE_TAG) ghcr.io/$(GHCR_USERNAME)/noetl-registrar:$(REGISTRAR_VERSION)


#[PUSH]#######################################################################
.PHONY: push-cli push-api push-dispatcher push-registrar
.PHONY: docker-login push-all

push-all: push-cli push-api push-dispatcher push-registrar

docker-login:
	@echo "Logging in to GitHub Container Registry"
	@echo $$PAT | docker login ghcr.io -u noetl --password-stdin

push-cli: tag-cli docker-login
	@echo "Pushing CLI image to GitHub Container Registry"
	docker push ghcr.io/$(GHCR_USERNAME)/noetl-cli:$(CLI_VERSION)

push-api: tag-api docker-login
	@echo "Pushing API image to GitHub Container Registry"
	docker push ghcr.io/$(GHCR_USERNAME)/noetl-api:$(API_VERSION)

push-dispatcher: tag-dispatcher docker-login
	@echo "Pushing Dispatcher image to GitHub Container Registry"
	docker push ghcr.io/$(GHCR_USERNAME)/noetl-dispatcher:$(DISPATCHER_VERSION)

push-registrar: tag-registrar docker-login
	@echo "Pushing Registrar image to GitHub Container Registry"
	docker push ghcr.io/$(GHCR_USERNAME)/noetl-registrar:$(REGISTRAR_VERSION)


#[DEPLOY]#######################################################################
.PHONY: create-ns deploy-all deploy-all-local
.PHONY: deploy-api deploy-dispatcher deploy-registrar

deploy-all: create-ns deploy-api deploy-dispatcher deploy-registrar
deploy-all-local: create-ns deploy-api-local deploy-dispatcher-local deploy-registrar-local

create-ns:
	@echo "Creating NoETL namespace..."
	kubectl config use-context docker-desktop
	kubectl apply -f $(K8S_DIR)/noetl/namespace.yaml

deploy-api:
	@echo "Deploying NoETL API service from ghcr.io ..."
	kubectl config use-context docker-desktop
	kubectl apply -f $(K8S_DIR)/noetl/api/deployment.yaml
	kubectl apply -f $(K8S_DIR)/noetl/api/service.yaml

deploy-api-local:
	@echo "Deploying NoETL API service from local image..."
	kubectl config use-context docker-desktop
	kubectl apply -f $(K8S_DIR)/noetl/api-local/deployment.yaml
	kubectl apply -f $(K8S_DIR)/noetl/api-local/service.yaml

deploy-dispatcher:
	@echo "Deploying NoETL Dispatcher service from ghcr.io ..."
	kubectl config use-context docker-desktop
	kubectl apply -f $(K8S_DIR)/noetl/dispatcher/deployment.yaml

deploy-dispatcher-local:
	@echo "Deploying NoETL Dispatcher service from local image..."
	kubectl config use-context docker-desktop
	kubectl apply -f $(K8S_DIR)/noetl/dispatcher-local/deployment.yaml

deploy-registrar:
	@echo "Deploying NoETL Registrar service from ghcr.io ..."
	kubectl config use-context docker-desktop
	kubectl apply -f $(K8S_DIR)/noetl/registrar/deployment.yaml

deploy-registrar-local:
	@echo "Deploying NoETL Registrar service from local image..."
	kubectl config use-context docker-desktop
	kubectl apply -f $(K8S_DIR)/noetl/registrar-local/deployment.yaml


.PHONY: delete-ns delete-all-deploy delete-all-local-deploy
.PHONY: delete-api-deploy delete-dispatcher-deploy delete-registrar-deploy

delete-all-deploy: delete-api-deploy delete-dispatcher-deploy delete-registrar-deploy delete-ns
delete-all-local-deploy: delete-api-local-deploy delete-dispatcher-local-deploy delete-registrar-local-deploy delete-ns

delete-ns:
	@echo "Deleting NoETL namespace..."
	kubectl config use-context docker-desktop
	kubectl delete -f $(K8S_DIR)/noetl/namespace.yaml

delete-api-deploy:
	@echo "Deleting NoETL API Service"
	kubectl config use-context docker-desktop
	kubectl delete -f $(K8S_DIR)/noetl/api/deployment.yaml -n noetl
	kubectl delete -f $(K8S_DIR)/noetl/api/service.yaml -n noetl

delete-api-local-deploy:
	@echo "Deleting NoETL API Service"
	kubectl config use-context docker-desktop
	kubectl delete -f $(K8S_DIR)/noetl/api-local/deployment.yaml -n noetl
	kubectl delete -f $(K8S_DIR)/noetl/api-local/service.yaml -n noetl

delete-dispatcher-deploy:
	@echo "Deleting NoETL Dispatcher Service"
	kubectl config use-context docker-desktop
	@kubectl delete -f $(K8S_DIR)/noetl/dispatcher/deployment.yaml -n noetl


delete-dispatcher-local-deploy:
	@echo "Deleting NoETL Dispatcher Service"
	kubectl config use-context docker-desktop
	@kubectl delete -f $(K8S_DIR)/noetl/dispatcher-local/deployment.yaml -n noetl

delete-registrar-deploy:
	@echo "Deleting NoETL Registrar Service"
	kubectl config use-context docker-desktop
	kubectl delete -f $(K8S_DIR)/noetl/registrar/deployment.yaml -n noetl

delete-registrar-local-deploy:
	@echo "Deleting NoETL Registrar Service"
	kubectl config use-context docker-desktop
	kubectl delete -f $(K8S_DIR)/noetl/registrar-local/deployment.yaml -n noetl



#[NATS]#######################################################################
.PHONY: nats-create-events nats-create-commands nats-create-all


nats-create-all: nats-create-events nats-create-commands


nats-create-events:
	@echo "Creating NATS events"
	kubectl config use-context docker-desktop
	kubectl apply -f $(K8S_DIR)/nats/events/event-stream.yaml -n nats

nats-create-commands:
	@echo "Creating NATS commands"
	kubectl config use-context docker-desktop
	kubectl apply -f $(K8S_DIR)/nats/commands/command-stream.yaml -n nats


.PHONY: nats-delete-events nats-delete-commands nats-delete-all


nats-delete-all: nats-delete-events nats-delete-commands

nats-delete-events:
	@echo "Deleting NATS events"
	kubectl config use-context docker-desktop
	kubectl delete -f $(K8S_DIR)/nats/events/event-stream.yaml -n nats

nats-delete-commands:
	@echo "Deleting NATS commands"
	kubectl config use-context docker-desktop
	kubectl delete -f $(K8S_DIR)/nats/commands/command-stream.yaml -n nats


nats-reset-all: nats-delete-all nats-create-all
	@echo "Reset all NATS streams in Kubernetes"


.PHONY: nats-purge-commands nats-purge-events nats-purge-all nats-stream-ls


nats-purge-all: nats-purge-commands nats-purge-events nats-stream-ls
	@echo "Purged NATS events and commands streams"

nats-purge-commands:
	@echo "Purging NATS commands streams"
	@nats stream purge commands --force -s $(NATS_URL)

nats-purge-events:
	@echo "Purging NATS events streams"
	@nats stream purge events --force -s $(NATS_URL)

nats-stream-ls:
	@nats stream ls -s $(NATS_URL)

.PHONY: purge-commands purge-events purge-all stream-ls

run-api: activate-venv
	bin/api.sh

run-dispatcher: activate-venv
	bin/dispatcher.sh

run-registrar: activate-venv
	bin/registrar.sh

.PHONY: run-api run-dispatcher run-registrar

#[WORKFLOW COMMANDS]######################################################################
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


api-all: delete-api build-api tag-api push-api deploy-api
	@echo "Redeploy NoETL api service to Kubernetes"


install-helm:
	@echo "Installing Helm..."
	@brew install helm
	@echo "Helm installation complete."

# add-nats-repo:
# 	@echo "Adding NATS helm repo..."
# 	@helm repo add nats https://nats-io.github.io/k8s/helm/charts/
# 	@echo "NATS helm repo added."

# add-ingress-repo:
# 	@echo "Adding ingress-nginx helm repo..."
# 	@helm repo add ingress-nginx https://kubernetes.github.io/ingress-nginx
# 	@helm repo update
# 	@echo "ingress-nginx helm repo added."

install-nats-tools:
	@echo "Tapping nats-io/nats-tools..."
	@brew tap nats-io/nats-tools
	@echo "Installing nats from nats-io/nats-tools..."
	@brew install nats-io/nats-tools/nats
	@echo "NATS installation complete."

# set-k8s-context:
# 	@echo "Setting Kubernetes context to docker-desktop..."
# 	@kubectx docker-desktop
# 	@echo "Context set to docker-desktop."

# install-ingress-nginx: add-ingress-repo
# 	@echo "Checking if ingress-nginx is already installed..."
# 	@if ! helm list -n ingress-nginx | grep -q ingress-nginx; then \
#         echo "Installing ingress-nginx..."; \
#         helm install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --create-namespace; \
#         kubectl apply -f https://raw.githubusercontent.com/kubernetes/ingress-nginx/main/deploy/static/provider/cloud/deploy.yaml; \
#         echo "ingress-nginx installed."; \
#     else \
#         echo "ingress-nginx is already installed, skipping installation."; \
#     fi

# install-nats:
# 	@echo "Installing NATS..."
# 	@helm install nats nats/nats --values k8s/nats/values.yaml --namespace nats --create-namespace
# 	@helm helm install nack nats/nack --set jetstream.nats.url=nats://nats:4222 -n nats
# 	@echo "NATS installed."

# install-nats-crd:
# 	@echo "Installing NATS JetStream CRDs..."
# 	@kubectl apply -f kubectl apply -f https://github.com/nats-io/nack/releases/latest/download/crds.yml -n nats
# 	@echo "NATS JetStream CRDs installed."

# .PHONY: install-helm install-nats-tools add-nats-repo set-k8s-context install-ingress-nginx install-nats install-nats-crd

# install-all-nats: set-k8s-context install-helm install-nats-tools add-nats-repo set-k8s-context install-ingress-nginx install-nats install-nats-crd
# 	@echo "All components installed."

# .PHONY: install-all-nats

# .PHONY: register-workflow list-workflows describe-workflow run-current-time-workflow
