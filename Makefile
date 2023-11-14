GHCR_USERNAME=noetl
VERSION=latest
K8S_DIR=k8s
define get_nats_port
$(shell kubectl get svc nats -n nats -o=jsonpath='{.spec.ports[0].nodePort}')
endef

NATS_URL=nats://localhost:$(call get_nats_port)
CLI_SERVICE_NAME=noetl-api
API_SERVICE_NAME=noetl-api
DISPATCHER_SERVICE_NAME=noetl-dispatcher
REGISTRAR_SERVICE_NAME=noetl-registrar
CLI_DOCKERFILE=docker/cli/Dockerfile-cli
API_DOCKERFILE=docker/api/Dockerfile-api
DISPATCHER_DOCKERFILE=docker/dispatcher/Dockerfile-dispatcher
REGISTRAR_DOCKERFILE=docker/registrar/Dockerfile-registrar

all: build-all push-all

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

push-api: tag-cli
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

api-all: delete-api build-api tag-api push-api deploy-api
	@echo "Redeploy NoETL api service to Kubernetes"

.PHONY: deploy-api deploy-dispatcher deploy-registrar deploy-api api-all

deploy-api:
	@echo "Deploying NoETL API Service"
	@kubectl apply -f $(K8S_DIR)/noetl-api/deployment.yaml
	@kubectl apply -f $(K8S_DIR)/noetl-api/service.yaml
	@kubectl apply -f $(K8S_DIR)/noetl-api/ingress.yaml

deploy-dispatcher:
	@echo "Deploying NoETL Dispatcher Service"
	@kubectl apply -f $(K8S_DIR)/noetl-dispatcher/deployment.yaml
	@kubectl apply -f $(K8S_DIR)/noetl-dispatcher/service.yaml

deploy-registrar:
	@echo "Deploying NoETL Registrar Service"
	@kubectl apply -f $(K8S_DIR)/noetl-registrar/deployment.yaml
	@kubectl apply -f $(K8S_DIR)/noetl-registrar/service.yaml

deploy-all: deploy-api deploy-dispatcher deploy-registrar
	@echo "Redeploy NoETL core services to Kubernetes"


.PHONY: delete-api

delete-api:
	@echo "Deleting NoETL API Service"
	@kubectl delete -f $(K8S_DIR)/noetl-api/deployment.yaml -n noetl || true
	@kubectl delete -f $(K8S_DIR)/noetl-api/service.yaml -n noetl || true
	@kubectl delete -f $(K8S_DIR)/noetl-api/ingress.yaml -n noetl || true


nats-all: nats-delete-events nats-delete-commands nats-create-events nats-create-commands
	@echo "Reset all NATS streams in Kubernetes"

.PHONY: nats-delete-events nats-delete-commands nats-create-events nats-create-commands nats-all

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

.PHONY: purge-commands purge-events purge-all stream-ls

purge-all: purge-commands purge-events stream-ls
	@echo "Purged NATS events and commands streams"

purge-commands:
	@echo "Purging NATS commands streams"
	@nats stream purge commands --force -s $(NATS_URL)

purge-events:
	@echo "Purging NATS events streams"
	@nats stream purge events --force -s $(NATS_URL)

stream-ls:
	@nats stream ls -s $(NATS_URL)
