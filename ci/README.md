[Taskfile](documents/taskfile.md) is used as task runner/build tool. 

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
The Postgres port will be exposed as `54321` on the host system. With this configuration, Postgres running in the **noetl** kind cluster will be available to applications on the host machine at `localhost:54321`.

### 3. Build NOETL
```
task docker-build-noetl
```
The image will be built with a temporary tag in the following format: YYYY-MM-DD-hh-mm.
This temporary tag will be saved in `.noetl_last_build_tag.txt.` This file contains the last temporary tag, which is later used for deployment.

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
The noetl service port `8082` will be exposed as port `8082` on the host system.

<br>
<br>

---
Other available commands can be listed by running the `task` command without arguments:
```
task
```
For example, the following command performs all the above steps in a single run.
```
task bring-up-kind
```
