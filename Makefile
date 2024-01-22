GHCR_USERNAME=noetl
VERSION="0.1.0"
K8S_DIR=k8s

# define get_nats_port
# $(shell kubectl get svc nats -n nats -o=jsonpath='{.spec.ports[0].nodePort}')
# endef
# NATS_URL=nats://localhost:$(call get_nats_port)

NATS_URL=nats://localhost:32222

PYTHON := python3.11
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

install-helm:
	@echo "Installing Helm..."
	@brew install helm
	@echo "Helm installation complete."


install-nats-tools:
	@echo "Tapping nats-io/nats-tools..."
	@brew tap nats-io/nats-tools
	@echo "Installing nats from nats-io/nats-tools..."
	@brew install nats-io/nats-tools/nats
	@echo "NATS installation complete."

#all: build-all push-all delete-all deploy-all

.PHONY: venv requirements activate-venv activate-help install-helm install-nats-tools



#[BUILD]#######################################################################
.PHONY: build-cli remove-cli-image rebuild-cli

build-cli:
	@echo "Building CLI image..."
	docker build --build-arg PRJ_PATH=../../ -f $(CLI_DOCKERFILE) -t $(CLI_SERVICE_TAG) .

remove-cli-image:
	@echo "Removing CLI image..."
	docker rmi $(CLI_SERVICE_TAG)

rebuild-cli: remove-cli-image build-cli


clean:
	docker rmi $$(docker images -f "dangling=true" -q)


#[TAG]#######################################################################
.PHONY: tag-cli

tag-cli:
	@echo "Tagging CLI image"
	docker tag $(CLI_SERVICE_TAG) ghcr.io/$(GHCR_USERNAME)/noetl-cli:$(CLI_VERSION)


#[PUSH]#######################################################################
.PHONY: push-cli
.PHONY: docker-login push-all

push-all: push-cli

docker-login:
	@echo "Logging in to GitHub Container Registry"
	@echo $$PAT | docker login ghcr.io -u noetl --password-stdin

push-cli: tag-cli docker-login
	@echo "Pushing CLI image to GitHub Container Registry"
	docker push ghcr.io/$(GHCR_USERNAME)/noetl-cli:$(CLI_VERSION)

#[NATS]#######################################################################
.PHONY: nats-create-noetl nats-delete-noetl nats-reset-noetl purge-noetl stream-ls

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

#[WORKFLOW COMMANDS]######################################################################

register-plugin: activate-venv
    ifeq ($(PLUGIN_NAME),)
	    @echo "Usage: make register-plugin PLUGIN_NAME=\"http-handler:0_1_0\" IMAGE_URL=\"local/noetl-http-handler:latest\""
    else
	    $(PYTHON) noetl/cli.py register plugin  $(PLUGIN_NAME) $(IMAGE_URL)
    endif

list-plugins: activate-venv
	$(PYTHON) noetl/cli.py list plugins

describe-plugin: activate-venv
	$(PYTHON) noetl/cli.py describe plugin $(filter-out $@,$(MAKECMDGOALS))

register-playbook: activate-venv
    ifeq ($(WORKFLOW),)
	    @echo "Usage: make register-playbook WORKFLOW=playbooks/time/fetch-world-time.yaml"
    else
	    $(PYTHON) noetl/cli.py register playbook $(WORKFLOW)
    endif

list-playbooks: activate-venv
	$(PYTHON) noetl/cli.py list playbooks

%:
	@:
describe-playbook: activate-venv %
	$(PYTHON) noetl/cli.py describe playbook $(filter-out $@,$(MAKECMDGOALS))

run-playbook-fetch-time-and-notify-slack: activate-venv
	$(PYTHON) noetl/cli.py run playbook fetch-time-and-notify-slack '{"TIMEZONE":"$(TIMEZONE)","NOTIFICATION_CHANNEL":"$(NOTIFICATION_CHANNEL)"}'


.PHONY: register-playbook list-playbooks list-plugins describe-playbook describe-plugin run-playbook-fetch-time-and-notify-slack

.PHONY: show-events show-commands
show-events:
	$(PYTHON) noetl/cli.py show events

show-commands:
	$(PYTHON) noetl/cli.py show commands


#[KUBECTL COMMANDS]######################################################################

.PHONY: logs
logs:
	kubectl logs -f -l 'app in (noetl-api, noetl-dispatcher, noetl-http-handler, noetl-registrar)'


#[PIP UPLOAD]############################################################################
.PHONY: pip-upload

pip-upload:
	rm -rf dist/*
	$(PYTHON) setup.py sdist bdist_wheel
	$(PYTHON) -m twine upload dist/*
