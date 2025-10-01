[Taskfile](documents/taskfile.md) is used as task runner/build tool.  
The following tools are available for in-cluster troubleshooting: [Tshoot](manifests/tshoot/README.md)

After deployment, the following components are available on the host system:
- Noetl API server: http://localhost:8082/api/
- Grafana: http://localhost:3000
  - with login: **admin**; password: **admin**
- Postgers: **localhost:54321**
  - with login: **noetl**; password: **noetl**

---
#### Requirements:
- docker  
- kind
- kubeclt
- yq

Install **kind**, **kubectl**, **yq** on MacOS:
```
brew install kind
brew install kubectl
brew install yq
```  

<br>
<br>  

## Spin up kind cluster

### 1. Create **noetl** kind cluster
```
task kind-create-cluster
```  
    
### 2. Deploy Postgres
```
task deploy-postgres
``` 
This command deploys Postgres 17.4 to the **noetl** cluster. The `pgdata` folder of the Postgres pod will be mounted to the `ci/kind/data` (excluded with **.gitignore**) folder on the host system . This ensures that Postgres data is preserved even if all Docker volumes are pruned.  
The Postgres port will be exposed as `54321` on the host system. With this configuration, Postgres running in the **noetl** kind cluster will be available to applications on the host machine at `localhost:54321` with login `noetl` and password `noetl`

### 3. Build noetl
```
task docker-build-noetl
```
The image will be built with a temporary tag in the following format: YYYY-MM-DD-hh-mm.
This temporary tag will be saved in `.noetl_last_build_tag.txt.` This file contains the last temporary tag, which is later used for deployment.
>[!CAUTION]  
>By default, this command builds the Docker image without using cache.
>To enable cache, run the command with the `cache` argument:   
>`task docker-build-noetl -- cache`  
>or in short form:  
>`task dbn -- cache`  
>Combined commands such as `task bring-all` do not accept arguments and always perform the build without using cache.

### 4. Upload the built image to the **noetl** kind cluster
```
task load-noetl-image
```

### 5. (Optional) Check all images available in the **noetl** kind cluster with the following command
```
task show-kind-images
```

### 6. Deploy noetl
```
task deploy-noetl
```
The noetl service port 8082 is exposed as port 8082 on the host system. Container folders `/opt/noetl/data` and `/opt/noetl/logs` are mounted to the host folders `ci/kind/cache/noetl-data` and `ci/kind/cache/noetl-logs`,respectively. The container status can be checked at http://localhost:8082/api/health


## Install Victoria Metrics stack

### 1. Add Victoria Metrics Helm repository
```
task add-victoriametrics-helm-repo
```

### 2. Add Metrics Server Helm repository
```
task add-metrics-server-helm-repo
```

### 3. (Optional) Check available Helm chart versions
```
helm search repo vm/victoria-metrics-k8s-stack -l
helm search repo vm/victoria-metrics-operator -l
helm search repo metrics-server/metrics-server -l
```
Version 0.60.1 is currently used for the Victoria Metrics stack deployment.  
Version 0.54.0 is currently used for the Victoria Metrics operator deployment.  
Version 3.13.0 is currently used for the Metrics Server deployment.  

### 4. Install Metrics Server
```
task deploy-metrics-server
```

### 5. Install Victoria Metrics operator
To have control over an order of managed resources removal or to be able to remove a whole namespace with managed resources it’s recommended to disable operator in k8s-stack chart (victoria-metrics-operator.enabled: false) and install it separately. [Link to the official documentation](https://docs.victoriametrics.com/helm/victoria-metrics-k8s-stack/#install-operator-separately) 
```
task deploy-vmstack-operator
```

### 6. Install Victoria Metrics stack
```
task deploy-vmstack
```
After deployment, Grafana is available at http://localhost:3000 with the login `admin` and password `admin`.  

---

The following command performs all the above steps in a single run.
```
task deploy-monitoring
```

<br>
<br>

---  

Other available commands can be listed by running the `task` command without arguments:
```
task
```
For example, the following command performs these steps:
- Builds noetl image with a dynamic tag
- Creates a kind Kubernetes cluster
- Loads the built noetl image into the kind cluster
- Deploys monitoring components, including:
  - Metrics Server
  - Victoria Metrics operator
  - Victoria Metrics stack
- Deploys Postgers
- Deploys the noetl API server and worker
```
task bring-all
```
