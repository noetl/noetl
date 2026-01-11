---
sidebar_position: 2
title: Local Playbook Execution
description: Run NoETL playbooks locally without distributed execution
---

# Local Playbook Execution

## Overview

The `noetl run` command enables local execution of NoETL playbooks without requiring a running server, worker, or database. This provides a lightweight way to use playbooks for automation tasks similar to taskfiles or Makefiles.

## Key Features

- **Standalone Execution**: No server/worker infrastructure needed
- **Auto-Discovery**: Automatically finds `noetl.yaml` or `main.yaml` in current directory
- **Target-Based**: Run specific workflow steps like taskfile targets
- **Tool Support**: Shell commands, HTTP requests, and playbook composition
- **Variable Templating**: Jinja2-style template rendering
- **Result Capture**: Store and pass results between steps

## Auto-Discovery

When no playbook file is explicitly specified, `noetl run` automatically searches for playbooks in the current directory with the following priority:

1. **`./noetl.yaml`** (priority)
2. **`./main.yaml`** (fallback)

This enables simplified workflow automation similar to taskfiles:

```bash
# Auto-discover playbook and run from 'start' step
noetl run

# Auto-discover playbook and run specific target
noetl run bootstrap
noetl run deploy
noetl run test

# Auto-discover with variables
noetl run bootstrap --set env=production --verbose
```

### File Resolution Algorithm

The CLI uses a **File-First Strategy** to resolve playbook paths:

1. **Explicit Path Check**: If argument contains `/` or `\` → treat as file path
2. **Extension Check**: If argument ends with `.yaml` or `.yml` → treat as file path
3. **File Existence Check**: Try to find file (as-is, with `.yaml`, with `.yml`)
4. **Auto-Discovery**: If no file found, search for `./noetl.yaml` → `./main.yaml`
5. **Target Handling**: Remaining arguments treated as target step name

**Examples**:

```bash
# Explicit file path (contains /)
noetl run automation/deploy.yaml production

# Explicit file by extension
noetl run deploy.yaml production

# File exists check (tries deploy, deploy.yaml, deploy.yml)
noetl run deploy production

# Auto-discover → treat first arg as target
noetl run bootstrap        # Uses ./noetl.yaml or ./main.yaml, target "bootstrap"

# Auto-discover → default to 'start'
noetl run                  # Uses ./noetl.yaml or ./main.yaml, starts at "start" step
```

## Basic Usage

```bash
# Auto-discover and run specific target
noetl run bootstrap

# Explicit playbook with target
noetl run automation/playbook.yaml deploy

# Auto-discover with variables
noetl run bootstrap --set env=production --set version=v2.5

# Explicit file with JSON payload
noetl run automation/playbook.yaml --payload '{"env":"production","version":"v2.5"}'

# Combine auto-discovery with payload and overrides
noetl run deploy \
  --payload '{"target":"staging","registry":"gcr.io"}' \
  --set target=production

# Verbose output with auto-discovery
noetl run bootstrap --verbose
```

## Supported Tool Types

### Shell Commands

Execute operating system commands:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: shell_example
  
workflow:
  - step: start
    next:
      - step: build
  
  - step: build
    desc: "Build Docker image"
    tool:
      kind: shell
      cmds:
        - "docker build -t myapp:latest ."
        - "docker push myapp:latest"
    next:
      - step: end
  
  - step: end
```

**cmds Format**:
- **String**: Single command or multiline script
- **Array**: Multiple commands executed sequentially

**Example with multiline string**:
```yaml
tool:
  kind: shell
  cmds: |
    echo "Starting build..."
    docker build -t app:latest .
    echo "Build complete"
```

### HTTP Requests

Make REST API calls:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: http_example

workload:
  api_base: "https://api.example.com"
  api_token: "secret-token"

workflow:
  - step: start
    next:
      - step: fetch_data
  
  - step: fetch_data
    desc: "Fetch user data"
    tool:
      kind: http
      method: GET
      url: "{{ workload.api_base }}/users/1"
      headers:
        Authorization: "Bearer {{ workload.api_token }}"
        Content-Type: "application/json"
      params:
        include: "profile,settings"
    vars:
      user_data: "{{ fetch_data.result }}"
    next:
      - step: process_data
  
  - step: process_data
    desc: "Process fetched data"
    tool:
      kind: shell
      cmds:
        - "echo '{{ vars.user_data }}' | jq '.name'"
    next:
      - step: end
  
  - step: end
```

**HTTP Tool Fields**:
- `method`: GET, POST, PUT, DELETE, PATCH (default: GET)
- `url`: Target URL (supports templating)
- `headers`: Optional request headers (map)
- `params`: Optional query parameters (map)
- `body`: Optional request body (string)

**Response Handling**:
- HTTP responses are captured as strings
- Use `vars:` to extract results for later steps
- Reference via `{{ step_name.result }}`

### Playbook Composition

Call other playbooks as sub-workflows:

**Parent Playbook** (`parent.yaml`):
```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: parent_playbook

workload:
  environment: "production"
  version: "v2.5.5"

workflow:
  - step: start
    next:
      - step: call_build
  
  - step: call_build
    desc: "Build application"
    tool:
      kind: playbook
      path: ./build.yaml
      args:
        image_tag: "{{ workload.version }}"
        build_env: "{{ workload.environment }}"
    next:
      - step: call_deploy
  
  - step: call_deploy
    desc: "Deploy application"
    tool:
      kind: playbook
      path: ./deploy.yaml
      args:
        image_tag: "{{ workload.version }}"
        target_env: "{{ workload.environment }}"
    next:
      - step: end
  
  - step: end
```

**Child Playbook** (`build.yaml`):
```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: build_child

workflow:
  - step: start
    next:
      - step: build_image
  
  - step: build_image
    desc: "Build Docker image"
    tool:
      kind: shell
      cmds:
        - "echo 'Building image: {{ workload.image_tag }}'"
        - "echo 'Environment: {{ workload.build_env }}'"
        - "docker build -t app:{{ workload.image_tag }} ."
    next:
      - step: end
  
  - step: end
```

**Argument Passing**:
- Parent passes `args` map to child playbook
- Child receives args as `workload.*` variables
- Example: `args: {image_tag: "v2.5"}` → `{{ workload.image_tag }}`

## Variable System

### Workload Variables

Global variables defined in playbook:

```yaml
workload:
  api_url: "https://api.example.com"
  timeout: 30
  retries: 3

workflow:
  - step: api_call
    tool:
      kind: http
      url: "{{ workload.api_url }}/endpoint"
```

### Command-Line Variables

Override or add variables at runtime using `--set`:

```bash
noetl run playbook.yaml --set api_url=https://staging.api.com --set timeout=60
```

**Variable Format**:
- Key-value pairs: `--set key=value`
- Multiple variables: `--set var1=value1 --set var2=value2`
- Values become available as both `{{ key }}` and `{{ workload.key }}`

### JSON Payload/Workload

Pass multiple variables as JSON object (matches server API behavior):

```bash
# Using --payload parameter
noetl run playbook.yaml --payload '{"target":"production","version":"v2.5.5"}'

# Using --workload alias (same behavior)
noetl run playbook.yaml --workload '{"env":"staging","debug":true}'

# Combine with --set (--set values override payload)
noetl run playbook.yaml \
  --payload '{"target":"production","registry":"gcr.io"}' \
  --set target=staging
```

**Payload Features**:
- **JSON Object**: Must be valid JSON object (not array or primitive)
- **Multiple Variables**: Pass many variables in one parameter
- **Override Precedence**: `--set` values override `--payload` values
- **Variable Accessibility**: Payload variables accessible as `{{ key }}` and `{{ workload.key }}`
- **Alias Support**: `--payload` and `--workload` are interchangeable

**Merge Behavior**:

By default, payload does shallow merge (override) with playbook workload:

```bash
# Shallow merge (default) - payload overrides playbook values
noetl run playbook.yaml --payload '{"target":"staging"}'

# Deep merge - recursively merges nested objects (future support)
noetl run playbook.yaml --payload '{"config":{"debug":true}}' --merge
```

**Example Playbook**:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: deployment_automation

workload:
  target: "development"  # Default value
  registry: "docker.io"
  version: "latest"

workflow:
  - step: start
    tool:
      kind: shell
      cmds:
        - echo "Deploying to {{ target }}"
        - echo "Registry: {{ registry }}"
        - echo "Version: {{ version }}"
```

**Usage Examples**:

```bash
# Use defaults from playbook
noetl run deploy.yaml
# Output: target=development, registry=docker.io, version=latest

# Override with payload
noetl run deploy.yaml --payload '{"target":"production","version":"v2.5.5"}'
# Output: target=production, registry=docker.io, version=v2.5.5

# Override with --set (takes precedence over payload)
noetl run deploy.yaml \
  --payload '{"target":"staging","version":"v2.0"}' \
  --set target=production
# Output: target=production, registry=docker.io, version=v2.0

# Mix payload and individual variables
noetl run deploy.yaml \
  --payload '{"version":"v2.5.5","debug":true}' \
  --set target=production \
  --set registry=gcr.io
# Output: target=production, registry=gcr.io, version=v2.5.5, debug=true
```

**API Compatibility**:

The `--payload` parameter matches the server API's execution request format:

```python
# Server API request
POST /api/run
{
  "playbook": "automation/deploy",
  "args": {"target": "production", "version": "v2.5.5"},
  "merge": false
}

# Equivalent CLI command
noetl run automation/deploy.yaml --payload '{"target":"production","version":"v2.5.5"}'
```

### Vars Extraction

Extract values from step results:

```yaml
- step: fetch_user
  tool:
    kind: http
    url: "{{ workload.api_base }}/users/1"
  vars:
    user_id: "{{ fetch_user.result }}"  # Extract from result
    user_name: "{{ fetch_user.result }}"
  next:
    - step: use_data

- step: use_data
  tool:
    kind: shell
    cmds:
      - "echo 'User: {{ vars.user_id }}'"
```

### Template Rendering

Supported patterns:
- `{{ workload.variable }}` - Workload variables
- `{{ vars.variable }}` - Extracted variables from vars blocks
- `{{ step_name.result }}` - Step execution results

## Target Execution

Run specific workflow steps by name:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: automation_tasks

workflow:
  - step: start
    next:
      - step: test
  
  - step: build
    desc: "Build application"
    tool:
      kind: shell
      cmds:
        - "cargo build --release"
  
  - step: test
    desc: "Run tests"
    tool:
      kind: shell
      cmds:
        - "cargo test"
  
  - step: deploy
    desc: "Deploy to production"
    tool:
      kind: shell
      cmds:
        - "./scripts/deploy.sh production"
```

**Usage**:
```bash
# Run full workflow (starts from "start" step)
noetl run automation_tasks.yaml

# Run only build step
noetl run automation_tasks.yaml build

# Run only deploy step
noetl run automation_tasks.yaml deploy
```

**Default Behavior**:
- If no target specified: starts from `"start"` step
- If target specified: runs from that step only
- If `"start"` step doesn't exist and no target: error

## Conditional Flow Control

Control workflow execution with `case/when/then/else` conditions:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: conditional_deployment

workload:
  environment: "production"
  deploy: "true"

workflow:
  - step: start
    desc: "Route based on environment"
    case:
      - when: "{{ workload.environment }} == production"
        then:
          - step: prod_setup
      - when: "{{ workload.environment }} == staging"
        then:
          - step: staging_setup
        else:
          - step: dev_setup
  
  - step: prod_setup
    tool:
      kind: shell
      cmds:
        - "echo 'Production setup with high availability'"
    next:
      - step: deploy
  
  - step: staging_setup
    tool:
      kind: shell
      cmds:
        - "echo 'Staging setup with standard config'"
    next:
      - step: deploy
  
  - step: dev_setup
    tool:
      kind: shell
      cmds:
        - "echo 'Development setup with debug mode'"
    next:
      - step: deploy
  
  - step: deploy
    desc: "Conditional deployment"
    case:
      - when: "{{ workload.deploy }} == true"
        then:
          - step: deploy_app
          - step: verify_app  # Multiple steps executed in sequence
      - when: "{{ workload.deploy }} != true"
        then:
          - step: skip_deploy
  
  - step: deploy_app
    tool:
      kind: shell
      cmds:
        - "kubectl apply -f deployment.yaml"
  
  - step: verify_app
    tool:
      kind: shell
      cmds:
        - "kubectl rollout status deployment/app"
  
  - step: skip_deploy
    tool:
      kind: shell
      cmds:
        - "echo 'Deployment skipped'"
```

**Conditional Features**:
- **when**: Condition expression (supports `==`, `!=`, truthy checks)
- **then**: Steps to execute if condition is true (can be multiple for sequence execution)
- **else**: Optional steps to execute if condition is false
- **Multiple cases**: First matching condition wins

**Supported Operators**:
- `{{ var }} == value` - Equality check
- `{{ var }} != value` - Inequality check
- `{{ var }}` - Truthy check (not empty, not "false", not "0")

**Priority**: `case` conditions are evaluated before `next` steps

**Example execution**:
```bash
# Production deployment
noetl run deployment.yaml --set workload.environment=production --set workload.deploy=true --verbose

# Staging without deployment
noetl run deployment.yaml --set workload.environment=staging --set workload.deploy=false --verbose

# Development (fallback to else)
noetl run deployment.yaml --set workload.environment=development --verbose
```

## Use Cases

### 1. Build Automation

Replace Makefiles with NoETL playbooks:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: build_automation

workflow:
  - step: clean
    tool:
      kind: shell
      cmds:
        - "rm -rf target/"
        - "cargo clean"
  
  - step: build
    tool:
      kind: shell
      cmds:
        - "cargo build --release"
  
  - step: test
    tool:
      kind: shell
      cmds:
        - "cargo test --all"
```

```bash
noetl run build.yaml clean
noetl run build.yaml build
noetl run build.yaml test
```

### 2. CI/CD Pipelines

Orchestrate deployment steps:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: ci_pipeline

workload:
  registry: "gcr.io/myproject"
  version: "v2.5.5"

workflow:
  - step: start
    next:
      - step: build_image
  
  - step: build_image
    tool:
      kind: shell
      cmds:
        - "docker build -t {{ workload.registry }}/app:{{ workload.version }} ."
    next:
      - step: push_image
  
  - step: push_image
    tool:
      kind: shell
      cmds:
        - "docker push {{ workload.registry }}/app:{{ workload.version }}"
    next:
      - step: deploy_k8s
  
  - step: deploy_k8s
    tool:
      kind: shell
      cmds:
        - "kubectl set image deployment/app app={{ workload.registry }}/app:{{ workload.version }}"
```

### 3. API Testing

Test REST endpoints:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: api_tests

workload:
  api_base: "http://localhost:8080"

workflow:
  - step: start
    next:
      - step: health_check
  
  - step: health_check
    tool:
      kind: http
      url: "{{ workload.api_base }}/health"
    next:
      - step: test_create
  
  - step: test_create
    tool:
      kind: http
      method: POST
      url: "{{ workload.api_base }}/api/users"
      headers:
        Content-Type: "application/json"
      body: '{"name": "Test User", "email": "test@example.com"}'
    vars:
      user_id: "{{ test_create.result }}"
    next:
      - step: test_get
  
  - step: test_get
    tool:
      kind: http
      url: "{{ workload.api_base }}/api/users/{{ vars.user_id }}"
    next:
      - step: test_delete
  
  - step: test_delete
    tool:
      kind: http
      method: DELETE
      url: "{{ workload.api_base }}/api/users/{{ vars.user_id }}"
```

### 4. Multi-Service Orchestration

Coordinate multiple services:

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: service_orchestration

workflow:
  - step: start
    next:
      - step: deploy_database
  
  - step: deploy_database
    tool:
      kind: playbook
      path: ./database/deploy.yaml
      args:
        environment: "staging"
    next:
      - step: deploy_backend
  
  - step: deploy_backend
    tool:
      kind: playbook
      path: ./backend/deploy.yaml
      args:
        environment: "staging"
        db_host: "{{ vars.db_endpoint }}"
    next:
      - step: deploy_frontend
  
  - step: deploy_frontend
    tool:
      kind: playbook
      path: ./frontend/deploy.yaml
      args:
        environment: "staging"
        api_url: "{{ vars.backend_url }}"
```

## Comparison with Distributed Execution

| Feature | Local (`noetl run`) | Distributed (Server/Worker) |
|---------|---------------------|---------------------------|
| Infrastructure | None required | Server + Worker + Database + NATS |
| Use Case | Automation scripts | Production workflows |
| Scalability | Single machine | Distributed execution |
| Event Log | No persistence | Full event tracking |
| Observability | Stdout only | ClickHouse, metrics, traces |
| Authentication | None | Credential vault integration |
| Tool Support | shell, http, playbook | All tools (postgres, duckdb, python, etc.) |
| Resumability | No | Yes (event-driven) |

**When to use local execution**:
- Development and testing
- CI/CD automation
- Build scripts and deployment tasks
- One-off administrative tasks
- Environments without infrastructure

**When to use distributed execution**:
- Production data pipelines
- Complex multi-step workflows
- Long-running processes
- Workflows requiring database integration
- Enterprise environments with credential management

## Command Reference

### noetl run

Execute a playbook locally:

```bash
noetl run <playbook_file> [target] [options]
```

**Arguments**:
- `<playbook_file>`: Path to YAML playbook file (required)
- `[target]`: Optional step name to execute (default: "start")

**Options**:
- `--set <key>=<value>`: Set variable (repeatable)
- `--verbose`: Show detailed execution output

**Examples**:

```bash
# Run entire playbook
noetl run automation/tasks.yaml

# Run specific step
noetl run automation/tasks.yaml deploy

# Pass variables
noetl run automation/tasks.yaml --set env=prod --set version=v2.5

# Verbose output
noetl run automation/tasks.yaml build --verbose

# Combine options
noetl run automation/tasks.yaml deploy \
  --set region=us-east-1 \
  --set cluster=production \
  --verbose

# Override workload variables
noetl run automation/tasks.yaml \
  --set workload.environment=staging \
  --set workload.replicas=3 \
  --verbose
```

## Limitations

Current local execution does NOT support:

1. **Database Tools**: postgres, duckdb, snowflake (requires database connections)
2. **Python Tool**: Execution of embedded Python code
3. **Iterator Tool**: Loop constructs
4. **Event Persistence**: No event log or execution history
5. **Credential Vault**: No credential resolution (use environment variables)
6. **NATS Integration**: No message queue coordination
7. **Observability**: No metrics/traces (only stdout)

**Unsupported Tool Handling**: When a playbook uses tools not supported in local mode (postgres, python, duckdb, iterator, etc.), noetlctl will display a warning message and skip the step:

```
⚠️  Tool not supported in local execution mode
   Supported tools: shell, http, playbook
   For other tools (postgres, duckdb, python, iterator, etc.), use distributed execution
```

The workflow will continue to the next step. To test unsupported tools, use the full distributed execution environment with server/worker infrastructure.

For database operations, Python code execution, and other advanced features, use the full distributed execution environment.

## Best Practices

### 1. Structure for Reusability

Organize playbooks by function:

```
automation/
├── build/
│   ├── rust.yaml
│   ├── docker.yaml
│   └── multiarch.yaml
├── deploy/
│   ├── staging.yaml
│   └── production.yaml
└── test/
    ├── integration.yaml
    └── e2e.yaml
```

### 2. Use Workload Variables

Define defaults, override at runtime:

```yaml
workload:
  environment: "staging"  # Default
  replicas: 3
  timeout: 300

# Override:
# noetl run deploy.yaml --set environment=production --set replicas=5
```

### 3. Composition for Complex Tasks

Break large workflows into smaller playbooks:

```yaml
# main.yaml
workflow:
  - step: build
    tool:
      kind: playbook
      path: ./build/all.yaml
  
  - step: test
    tool:
      kind: playbook
      path: ./test/all.yaml
  
  - step: deploy
    tool:
      kind: playbook
      path: ./deploy/k8s.yaml
```

### 4. Error Handling

Check exit codes in shell commands:

```yaml
- step: deploy
  tool:
    kind: shell
    cmds:
      - "kubectl apply -f deployment.yaml || exit 1"
      - "kubectl rollout status deployment/app || exit 1"
```

### 5. Idempotency

Design steps to be safely re-runnable:

```yaml
- step: create_namespace
  tool:
    kind: shell
    cmds:
      - "kubectl create namespace myapp || true"  # Ignore if exists
```

## Troubleshooting

### Step Not Found Error

```
Error: Step 'start' not found
```

**Solution**: Either add a "start" step or specify a target:
```bash
noetl run playbook.yaml existing_step_name
```

### Template Variable Not Replaced

```
{{ workload.api_url }} appears in output
```

**Cause**: Variable not defined in workload or command line.

**Solution**: Define variable:
```yaml
workload:
  api_url: "https://api.example.com"
```

Or pass via CLI:
```bash
noetl run playbook.yaml --set api_url=https://api.example.com
```

### HTTP Request Failed

```
Error: HTTP request failed with exit code: Some(3)
```

**Cause**: curl not installed or malformed URL.

**Solution**: 
- Install curl: `brew install curl` (Mac) or `apt install curl` (Linux)
- Check URL format in playbook

### Sub-Playbook Path Not Found

```
Error: Failed to resolve playbook path
```

**Cause**: Relative path resolution issue.

**Solution**: Use paths relative to parent playbook location:
```yaml
tool:
  kind: playbook
  path: ./child.yaml  # Relative to parent playbook directory
```

## Example Files

Complete working examples are available in the `automation/examples/` directory:

### 1. HTTP API Example

**File**: [`automation/examples/http_example.yaml`](../../../automation/examples/http_example.yaml)

Demonstrates HTTP GET requests with query parameters and result extraction:

```bash
noetl run automation/examples/http_example.yaml --verbose
```

**What it does**:
- Fetches user data from jsonplaceholder API (GET request)
- Fetches user posts with query parameters
- Extracts results using `vars:` blocks
- Displays captured data using shell commands

**Key features**:
- Template variables: `{{ workload.api_base }}`
- Result capture: `{{ fetch_user.result }}`
- Vars extraction: `{{ vars.user_data }}`
- Query parameters in HTTP requests

**Expected output**:
```
📋 Running playbook: http_example
🔹 Step: fetch_user
   🌐 HTTP GET https://jsonplaceholder.typicode.com/users/1
   📥 Response: {"id": 1, "name": "Leanne Graham", ...}
🔹 Step: fetch_posts
   🌐 HTTP GET https://jsonplaceholder.typicode.com/posts?userId=1
   📥 Response: [{"userId": 1, "id": 1, "title": "...", ...}]
✅ Playbook execution completed successfully
```

### 2. Playbook Composition Example

**Files**: 
- Parent: [`automation/examples/parent_playbook.yaml`](../../../automation/examples/parent_playbook.yaml)
- Child 1: [`automation/examples/build_child.yaml`](../../../automation/examples/build_child.yaml)
- Child 2: [`automation/examples/deploy_child.yaml`](../../../automation/examples/deploy_child.yaml)

Demonstrates calling sub-playbooks with argument passing:

```bash
noetl run automation/examples/parent_playbook.yaml --verbose
```

**What it does**:
- Parent defines workload variables (`environment`, `version`)
- Calls `build_child.yaml` with args (`image_tag`, `build_env`)
- Calls `deploy_child.yaml` with args (`image_tag`, `target_env`)
- Child playbooks receive args as `{{ workload.* }}` variables

**Key features**:
- Playbook composition with `kind: playbook`
- Argument passing via `args:` map
- Template rendering in parent: `{{ workload.version }}`
- Template rendering in child: `{{ workload.image_tag }}`

**Expected output**:
```
📋 Running playbook: playbook_composition_parent
🔹 Step: call_build
   📎 Executing sub-playbook: automation/examples/./build_child.yaml
📋 Running playbook: build_child
🔹 Step: build_image
   Building image with tag: v2.5.5
   Build environment: production
🔹 Step: call_deploy
   📎 Executing sub-playbook: automation/examples/./deploy_child.yaml
📋 Running playbook: deploy_child
🔹 Step: deploy
   Deploying image: v2.5.5
   Target environment: production
✅ Playbook execution completed successfully
```

### 3. Shell Commands Example

**File**: [`automation/examples/test_local.yaml`](../../../automation/examples/test_local.yaml)

Demonstrates shell command execution with both string and array formats:

```bash
# Run full workflow
noetl run automation/examples/test_local.yaml --verbose

# Run specific target
noetl run automation/examples/test_local.yaml list_files --verbose
```

**What it does**:
- Shows multiline string commands
- Shows array of commands
- Demonstrates target-based execution
- Lists files and shows system info

**Key features**:
- `cmds` as multiline string
- `cmds` as array of commands
- Target execution (specific step names)
- Sequential command execution

**Example commands**:
```yaml
# Multiline string format
cmds: |
  echo "Running multiple commands..."
  pwd
  date

# Array format
cmds:
  - "echo 'Command 1'"
  - "echo 'Command 2'"
  - "ls -la"
```

### 4. Build Automation Example

**File**: [`automation/test.yaml`](../../../automation/test.yaml)

Real-world example for NoETL project automation (similar to taskfile):

```bash
# Register test credentials
noetl run automation/test.yaml register_credentials

# Register test playbooks
noetl run automation/test.yaml register_playbooks

# Run specific automation task
noetl run automation/test.yaml <target_name>
```

**What it does**:
- Replaces taskfile commands with playbook targets
- Registers credentials to Kubernetes cluster
- Registers playbooks to catalog
- Provides reusable automation workflows

**Key features**:
- Multiple named steps (targets)
- Calls existing shell scripts
- Uses `kubectl` commands
- Demonstrates real-world CI/CD patterns

### 5. Conditional Flow Example

**File**: [`automation/examples/conditional_flow.yaml`](../../../automation/examples/conditional_flow.yaml)

Demonstrates conditional routing with case/when/then/else:

```bash
# Production deployment
noetl run automation/examples/conditional_flow.yaml --verbose

# Staging environment without deployment
noetl run automation/examples/conditional_flow.yaml \
  --set workload.environment=staging \
  --set workload.deploy=false \
  --verbose
```

**What it does**:
- Routes to different setup steps based on environment (production/staging/dev)
- Conditionally deploys or skips deployment based on flag
- Executes multiple steps in sequence when condition matches

**Key features**:
- `case/when/then/else` conditional routing
- Comparison operators: `==`, `!=`
- Multiple steps in `then` clause
- Else fallback for unmatched conditions

**Expected output**:
```
📋 Running playbook: conditional_flow_example
🔹 Step: start
   ✓ Condition matched: {{ workload.environment }} == production
🔹 Step: prod_setup
   Setting up PRODUCTION environment
   High availability: enabled
🔹 Step: check_deploy
   ✓ Condition matched: {{ workload.deploy }} == true
   ⚡ Executing 2 steps in sequence
🔹 Step: deploy_app
   Deploying application to production...
🔹 Step: verify_deployment
   Verifying deployment...
   Health check: OK
✅ Playbook execution completed successfully
```

### 6. Unsupported Tools Example

**File**: [`automation/examples/unsupported_tools.yaml`](../../../automation/examples/unsupported_tools.yaml)

Demonstrates how noetlctl handles tools not supported in local mode:

```bash
noetl run automation/examples/unsupported_tools.yaml --verbose
```

**What it does**:
- Attempts to use postgres, python, and duckdb tools
- Shows warning messages for unsupported tools
- Continues to next step (shell) which is supported

**Expected output**:
```
🔹 Step: try_postgres
⚠️  Tool not supported in local execution mode
   Supported tools: shell, http, playbook
   For other tools (postgres, duckdb, python, iterator, etc.), use distributed execution
🔹 Step: try_python
⚠️  Tool not supported in local execution mode
   ...
🔹 Step: use_shell
   Shell tool works in local mode!
✅ Playbook execution completed successfully
```

## Running Examples

### Basic Execution

```bash
# Navigate to project root
cd /path/to/noetl

# Run HTTP example
./bin/noetl run automation/examples/http_example.yaml --verbose

# Run composition example
./bin/noetl run automation/examples/parent_playbook.yaml --verbose

# Run shell example
./bin/noetl run automation/examples/test_local.yaml --verbose

# Run specific target from shell example
./bin/noetl run automation/examples/test_local.yaml list_files --verbose
```

### With Variable Overrides

```bash
# Override workload variables
./bin/noetl run automation/examples/parent_playbook.yaml \
  --set workload.environment=staging \
  --set workload.version=v2.6.0 \
  --verbose
```

### Testing Individual Steps

```bash
# Run just the build step
./bin/noetl run automation/examples/parent_playbook.yaml call_build --verbose

# Run just the deploy step
./bin/noetl run automation/examples/parent_playbook.yaml call_deploy --verbose
```

## Creating Your Own Examples

### Template Structure

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: my_example
  path: automation/examples/my_example  # Catalog path

workload:
  # Define default variables here
  environment: "development"
  api_url: "http://localhost:8080"

workflow:
  - step: start
    desc: "Entry point"
    next:
      - step: main_task
  
  - step: main_task
    desc: "Main execution step"
    tool:
      kind: shell  # or http, or playbook
      cmds:
        - "echo 'Environment: {{ workload.environment }}'"
    next:
      - step: end
  
  - step: end
```

### Adding to Examples Directory

1. Create YAML file in `automation/examples/`
2. Test locally: `noetl run automation/examples/your_file.yaml --verbose`
3. Document in this guide with explanation
4. Commit to repository

### Example Naming Convention

- `*_example.yaml` - Feature demonstration files
- `*_child.yaml` - Sub-playbooks for composition examples
- `test_*.yaml` - Testing and validation playbooks
- `automation/test.yaml` - Project-specific automation tasks
