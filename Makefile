GHCR_USERNAME=noetl
VERSION=latest
K8S_DIR=k8s


API_SERVICE_NAME=noetl-api
DISPATCHER_SERVICE_NAME=noetl-dispatcher
REGISTRAR_SERVICE_NAME=noetl-registrar

API_DOCKERFILE=docker/api/Dockerfile-api
DISPATCHER_DOCKERFILE=docker/dispatcher/Dockerfile-dispatcher
REGISTRAR_DOCKERFILE=docker/registrar/Dockerfile-registrar

all: build-api build-dispatcher build-registrar
.PHONY: build-api build-dispatcher build-registrar
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
	@echo $$PAT | docker login ghcr.io -u akuksin --password-stdin

tag-api:
	@echo "Tagging API image"
	@docker tag $(API_SERVICE_NAME) ghcr.io/$(GHCR_USERNAME)/noetl-api:$(VERSION)

tag-dispatcher:
	@echo "Tagging Dispatcher image"
	@docker tag $(DISPATCHER_SERVICE_NAME) ghcr.io/$(GHCR_USERNAME)/noetl-dispatcher:$(VERSION)

tag-registrar:
	@echo "Tagging Registrar image"
	@docker tag $(REGISTRAR_SERVICE_NAME) ghcr.io/$(GHCR_USERNAME)/noetl-registrar:$(VERSION)

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

.PHONY: deploy-api deploy-dispatcher deploy-registrar deploy-all


api-all: delete-api build-api tag-api push-api deploy-api
	@echo "NoETL api services to Kubernetes"

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
	@echo "NoETL core services deployed to Kubernetes"


.PHONY: delete-api

delete-api:
	@echo "Deleting NoETL API Service"
	@kubectl delete -f $(K8S_DIR)/noetl-api/deployment.yaml -n noetl
	@kubectl delete -f $(K8S_DIR)/noetl-api/service.yaml -n noetl
	@kubectl delete -f $(K8S_DIR)/noetl-api/ingress.yaml -n noetl
