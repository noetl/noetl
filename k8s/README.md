### Build arguments

```bash
make build-all
make rebuild-all

make build-cli
make rebuild-cli

make build-api
make rebuild-api

make build-dispatcher
make rebuild-dispatcher

make build-registrar
make rebuild-registrar
```

### Push arguments


```bash
make push-all

make push-cli
make push-api
make push-dispatcher
make push-registrar
```

### Deployment arguments
#### Images form ghcr.io
```bash
make create-ns
make deploy-all

make deploy-api
make deploy-dispatcher
make deploy-registrar

make delete-ns
make delete-all-deploy

make delete-api-deploy
make delete-dispatcher-deploy
make delete-registrar-deploy
```

#### Locally built images
```bash
make create-ns
make deploy-all-local

make deploy-api-local
make deploy-dispatcher-local
make deploy-registrar-local

make delete-ns
make delete-all-local-deploy

make delete-api-local-deploy
make delete-dispatcher-local-deploy
make delete-registrar-local-deploy
```

### NATS streams arguments
```bash
make nats-reset-all
make nats-create-all
make nats-delete-all

make nats-create-events
make nats-create-commands

make nats-delete-events
make nats-delete-commands

make nats-purge-all
make nats-purge-commands
make nats-purge-events

make nats-stream-ls
```


## Set NOETL_API_URL environment variable

```bash
export NOETL_API_URL=http://localhost:30080/noetl
```

## Run commands via CLI

```
python3.11 ./noetl/cli.py register workflow ./workflows/time/get-current-time.yaml
python3.11 ./noetl/cli.py describe plugin registrar
python3.11 ./noetl/cli.py describe workflow get-current-time
python3.11 ./noetl/cli.py list plugins
python3.11 ./noetl/cli.py list workflows
```
