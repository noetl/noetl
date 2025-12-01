# Quick Start Guide: Using NoETL as a Submodule

This guide helps you quickly set up a new project that uses NoETL as a git submodule.

## 1. Create New Project

```bash
# Create project directory
mkdir my-noetl-project
cd my-noetl-project

# Initialize git
git init

# Add NoETL as submodule
git submodule add https://github.com/noetl/noetl.git noetl
git submodule update --init --recursive
```

## 2. Copy Bootstrap Files

```bash
# Copy template files to project root
cp noetl/ci/bootstrap/Taskfile-bootstrap.yml ./Taskfile.yml
cp noetl/ci/bootstrap/pyproject-template.toml ./pyproject.toml
cp noetl/ci/bootstrap/gitignore-template ./.gitignore

# Make bootstrap script executable
chmod +x noetl/ci/bootstrap/bootstrap.sh
```

## 3. Customize Project Configuration

Edit `pyproject.toml`:

```toml
[project]
name = "my-noetl-project"  # Change this
version = "0.1.0"
description = "My awesome NoETL project"  # Change this
authors = [
    { name = "Your Name", email = "your.email@example.com" }  # Change this
]

dependencies = [
    # Add your project dependencies here
    "pandas>=2.0.0",
    "requests>=2.31.0",
]
```

## 4. Run Bootstrap

**IMPORTANT:** Run bootstrap first to install all required tools (including `task`).

**Automatic (detects OS):**
```bash
./.noetl/ci/bootstrap/bootstrap.sh
```

**Or specify OS explicitly:**
```bash
# macOS
./.noetl/ci/bootstrap/bootstrap.sh --os macos

# WSL2/Ubuntu
./.noetl/ci/bootstrap/bootstrap.sh --os linux
```

This will:
- ✅ Install system tools automatically:
  - Docker (auto-install & start)
  - **task (Taskfile automation)** ← Required before using any task commands
  - pyenv (Python version manager)
  - tfenv (Terraform version manager)
  - uv (Fast Python package manager)
  - kubectl, helm, kind
  - jq, yq, psql
  - Python 3.12+
- ✅ Create Python venv with your project + NoETL
- ✅ Set up Kind Kubernetes cluster
- ✅ Deploy PostgreSQL and monitoring stack
- ✅ Deploy NoETL server and workers
- ✅ Copy template files (.env.local, .gitignore, pyproject.toml)
- ✅ Create project directories (credentials/, playbooks/, data/, logs/, secrets/)

**Bootstrap takes 5-10 minutes on first run.**

## 5. Configure Environment (Optional)

The bootstrap creates `.env.local` with sensible defaults. Customize if needed:

```bash
# Edit environment configuration
vim .env.local

# Key settings:
# - POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB
# - NOETL_SERVER_HOST, NOETL_SERVER_PORT
# - NOETL_WORKER_POOL_SIZE
# - TZ (timezone - must match across all components)
# - External service credentials (GCP, AWS, Azure, etc.)
```

## 6. Verify Setup

```bash
# Activate venv
source .venv/bin/activate

# List available tasks (task was installed by bootstrap)
task --list

# Verify tools
task bootstrap:verify

# Check infrastructure
task dev:status
```

**Note:** If `task` command is not found, make sure the bootstrap script completed successfully. The script installs `task` automatically.

## 7. Create Your First Playbook

```bash
# Create playbooks directory
mkdir -p playbooks

# Create a simple playbook
cat > playbooks/hello_world.yaml << 'EOF'
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: hello_world
  path: examples/hello_world
workload:
  message: "Hello from NoETL!"
workflow:
  - step: start
    desc: Print hello message
    type: python
    code: |
      def main(input_data):
          message = input_data.get('message', 'Hello!')
          print(f"Message: {message}")
          return {"status": "success", "message": message}
    data:
      message: "{{ workload.message }}"
    next:
      - step: end
  - step: end
    desc: End workflow
EOF
```

## 8. Register and Execute

```bash
# Register playbook
.venv/bin/noetl register playbooks/hello_world.yaml \
  --host localhost --port 8083

# Execute playbook
.venv/bin/noetl execute playbook hello_world \
  --host localhost --port 8083

# Or use task
task playbooks:register
```

## 9. Access Services

**NoETL UI:**
```bash
open http://localhost:8083
```

**Grafana (monitoring):**
```bash
task k8s:port-forward:grafana
open http://localhost:3000
# Username: admin, Password: admin
```

**PostgreSQL:**
```bash
task k8s:port-forward:postgres
psql -h localhost -U noetl -d noetl
# Password: noetl
```

## Project Structure

Your project now looks like this:

```
my-noetl-project/
├── .git/                           # Your project git
├── .gitignore                      # Ignore credentials, venv, etc.
├── .venv/                          # Python venv (project + noetl)
├── Taskfile.yml                    # Your task automation
├── pyproject.toml                  # Your project dependencies
├── README.md                       # Your project docs
│
├── playbooks/                      # Your custom playbooks
│   └── hello_world.yaml
│
├── credentials/                    # Your credentials (gitignored)
│   └── my_service.json
│
├── tests/                          # Your tests
│   └── test_playbooks.py
│
└── noetl/                          # NoETL submodule (read-only)
    ├── ci/
    │   ├── bootstrap/              # Bootstrap scripts
    │   ├── taskfile/               # NoETL taskfiles
    │   ├── kind/                   # Kind cluster config
    │   ├── manifests/              # K8s manifests
    │   └── vmstack/                # Monitoring configs
    └── noetl/                      # NoETL Python package
```

## Common Tasks

```bash
# Development
task dev:start          # Start NoETL infrastructure
task dev:stop           # Stop NoETL infrastructure
task dev:status         # Show infrastructure status

# Playbooks
task playbooks:register # Register all playbooks
task playbooks:list     # List registered playbooks
task playbooks:execute -- hello_world  # Execute specific playbook

# Logs
task k8s:logs:noetl    # NoETL server logs
task k8s:logs:worker   # Worker logs
task k8s:logs:postgres # Postgres logs

# Cleanup
task clean:cache       # Clear local cache
task clean:all         # Clean everything
```

## Next Steps

### Add Credentials

Create credentials for external services:

```bash
mkdir -p credentials

cat > credentials/my_postgres.json << 'EOF'
{
  "name": "my_postgres",
  "type": "postgres",
  "data": {
    "host": "my-db.example.com",
    "port": 5432,
    "user": "myuser",
    "password": "mypassword",
    "database": "mydb"
  }
}
EOF

# Register
.venv/bin/noetl register credentials/my_postgres.json \
  --host localhost --port 8083
```

### Create Complex Playbook

```yaml
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: data_pipeline
  path: pipelines/data_etl
workload:
  source_table: "raw_data"
  target_table: "processed_data"
workbook:
  - name: extract_data
    type: postgres
    auth:
      type: postgres
      credential: my_postgres
    sql: |
      SELECT * FROM {{ workload.source_table }}
      WHERE created_at >= CURRENT_DATE - INTERVAL '1 day'
  
  - name: transform_data
    type: python
    code: |
      import pandas as pd
      def main(input_data):
          df = pd.DataFrame(input_data['rows'])
          # Your transformation logic
          df['processed_at'] = pd.Timestamp.now()
          return df.to_dict('records')
  
  - name: load_data
    type: postgres
    auth:
      type: postgres
      credential: my_postgres
    sql: |
      INSERT INTO {{ workload.target_table }}
      (column1, column2, processed_at)
      VALUES
      {% for row in data %}
      ('{{ row.column1 }}', '{{ row.column2 }}', '{{ row.processed_at }}')
      {{ "," if not loop.last else "" }}
      {% endfor %}

workflow:
  - step: start
    next:
      - step: extract
  
  - step: extract
    type: workbook
    name: extract_data
    next:
      - step: transform
  
  - step: transform
    type: workbook
    name: transform_data
    data:
      rows: "{{ extract.data.rows }}"
    next:
      - step: load
  
  - step: load
    type: workbook
    name: load_data
    data: "{{ transform.data }}"
    next:
      - step: end
  
  - step: end
    desc: Pipeline complete
```

### Add Tests

```bash
mkdir -p tests

cat > tests/test_playbooks.py << 'EOF'
import pytest
import requests

NOETL_API = "http://localhost:8083"

def test_playbook_registered():
    """Test that playbook is registered"""
    response = requests.get(f"{NOETL_API}/api/catalog/playbooks")
    assert response.status_code == 200
    playbooks = response.json()
    assert any(p['name'] == 'hello_world' for p in playbooks)

def test_playbook_execution():
    """Test playbook execution"""
    response = requests.post(
        f"{NOETL_API}/api/broker/execute",
        json={"catalog_path": "examples/hello_world"}
    )
    assert response.status_code == 200
    result = response.json()
    assert result['status'] == 'success'
EOF

# Run tests
pytest tests/
```

## Updating NoETL Submodule

```bash
# Check current version
cd noetl
git log -1 --oneline

# Update to latest
cd noetl
git fetch origin
git checkout master
git pull origin master
cd ..

# Or update to specific version
cd noetl
git checkout v1.0.4
cd ..

# Commit the update
git add noetl
git commit -m "Update noetl submodule to v1.0.4"
```

## Troubleshooting

**Problem: Tools not found after bootstrap**
```bash
# Reload shell
source ~/.bashrc  # Linux
source ~/.zshrc   # macOS

# Or open new terminal
```

**Problem: Docker permission denied (WSL2)**
```bash
sudo usermod -aG docker $USER
newgrp docker
```

**Problem: Port 8083 already in use**
```bash
# Find process using port
lsof -i :8083  # macOS
sudo netstat -tulpn | grep 8083  # Linux

# Kill the process or change NoETL port
# Edit noetl/ci/manifests/noetl/service.yaml
```

**Problem: Cluster won't start**
```bash
# Ensure Docker is running
docker info

# Delete and recreate
task dev:stop
task dev:start
```

## Support

- 📖 Full documentation: `noetl/ci/bootstrap/README.md`
- 🌐 NoETL website: https://noetl.io
- 🐛 Report issues: https://github.com/noetl/noetl/issues
- 💬 Ask questions: Create GitHub discussion

## Example Projects

See `noetl/examples/` for reference implementations:
- `noetl/examples/snowflake/` - Snowflake integration
- `noetl/examples/duckdb/` - DuckDB analytics
- `noetl/examples/weather/` - API integration example
