# Install ingress controller

```
helm install ingress-nginx ingress-nginx/ingress-nginx -n ingress-nginx --create-namespace
```

## Create streams

```bash
make nats-all
```
## Deploy applications

```bash
make deploy-all
```

## Run commands via CLI

```
python3.11 ./noetl/cli.py register workflow ./workflows/time/get-current-time.yaml
python3.11 ./noetl/cli.py describe plugin registrar
python3.11 ./noetl/cli.py describe workflow get-current-time
python3.11 ./noetl/cli.py list plugins
python3.11 ./noetl/cli.py list workflows
```
