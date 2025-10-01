## In-Cluster Troubleshooting

Two pod deployments are available for troubleshooting inside the cluster:  
- `psql-tshoot.yaml` – allows connections to PostgreSQL via the cluster service.
- `curl-tshoot.yaml` – allows making HTTP requests (curl) to specific services.

---

## Checking Postgres

#### 1. Deploy `psql-tshoot.yaml`:

```
kubectl config use-context kind-noetl
kubectl apply -f ci/manifests/tshoot/psql-tshoot.yaml
```

*(Run this command from the root of the repository.)*

#### 2. Connect to the pod:
   The easiest way is with **K9s**: select the pod, then press `s` to open a shell.

#### 3. Run the following command inside the pod:

```
psql -h postgres.postgres.svc.cluster.local -p 5432 -U noetl -d demo_noetl -c "SELECT * FROM noetl.catalog;"
```

#### Alternative: Verify from the PostgreSQL pod itself

You can also connect directly to the PostgreSQL pod and run:

```
psql -U noetl -d demo_noetl -c "SELECT * FROM noetl.catalog;"
```

#### Alternative: Verify from the host system

If you have a local **psql** client installed, you can run:

```
psql -h localhost -p 54321 -U noetl -d demo_noetl -c "SELECT * FROM noetl.catalog;"
```

All commands above will prompt for a password.  
The password is: `noetl`

---

## Checking the noetl API server

#### 1. Deploy `curl-tshoot.yaml`:

```
kubectl config use-context kind-noetl
kubectl apply -f ci/manifests/tshoot/curl-tshoot.yaml
```

*(Run this command from the root of the repository.)*

#### 2. Connect to the pod:
With **K9s**, select the pod and press `s` to open a shell.

#### 3. Run the following command inside the pod to verify availability via the Kubernetes service:
```
curl http://noetl.noetl.svc.cluster.local:8082/api/health
```

---

## Tips
#### Install **K9s**, **psql** on macOS:
```
brew install k9s
brew install postgresql@17
```
