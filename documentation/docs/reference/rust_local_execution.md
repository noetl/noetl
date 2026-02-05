# NoETL Rust Local Execution

This document describes the NoETL Rust implementation for local mode execution, including architecture, available tools, configuration options, and the Rhai scripting engine.

## Overview

NoETL supports two execution modes:

| Mode | Description | Use Case |
|------|-------------|----------|
| **Local** | Direct in-process execution via Rust | Development, testing, CI/CD, small playbooks |
| **Distributed** | Server-worker architecture via NATS | Large-scale, long-running, parallel workloads |

Local mode executes playbooks directly in the CLI process without requiring a server or external dependencies.

## Quick Start

```bash
# Execute a playbook in local mode
noetl exec ./playbook.yaml -r local

# With variables
noetl exec ./playbook.yaml -r local --set action=deploy --set env=prod

# Target a specific step
noetl exec ./playbook.yaml -r local --target my_step

# Dry-run (validate only)
noetl exec ./playbook.yaml -r local --dry-run
```

## Architecture

### Crate Structure

```
crates/
├── noetl/           # CLI binary - entry point for local execution
├── tools/           # Shared tool library with registry pattern
├── control-plane/   # Orchestration server (distributed mode)
├── worker-pool/     # Distributed worker implementation
└── gateway/         # HTTP gateway and proxy layer
```

### Local Execution Flow

```
1. Load & Parse Playbook (YAML)
   ↓
2. Validate Capabilities (check executor profile, tools, features)
   ↓
3. Initialize ExecutionContext with workload variables
   ↓
4. Execute Starting Step (default: "start", configurable with --target)
   ↓
5. For Each Step:
   - Execute Tool (if tool defined)
   - Capture Result
   - Extract Variables via "vars" block
   - Evaluate next[].when conditions
   - Execute Next Steps based on conditions
   ↓
6. Recurse Until Workflow Complete
```

## Available Tools

### Local Runtime Tools

| Tool | Description |
|------|-------------|
| `shell` | Execute shell commands |
| `http` | Make HTTP requests with auth support |
| `duckdb` | Query DuckDB databases |
| `rhai` | Execute Rhai scripts for complex logic |
| `playbook` | Call sub-playbooks |
| `noop` | No-operation (routing only) |

### Local Runtime Features

| Feature | Description |
|---------|-------------|
| `jinja2` | Jinja2-style template syntax |
| `case_v1` | Simple case/when/then conditions |
| `case_v2` | Rhai-based conditions |
| `loop_v1` | Basic loop support |
| `vars_v1` | Variable management |

## Tool Specifications

### Shell Tool

Execute shell commands with environment control.

```yaml
- step: run_commands
  tool:
    kind: shell
    cmds:
      - echo "Hello World"
      - ls -la
    shell: bash           # Shell to use (default: bash)
    cwd: /path/to/dir     # Working directory
    env:                  # Environment variables
      MY_VAR: value
    timeout_seconds: 30   # Timeout
    capture: true         # Capture output (default: true)
```

### HTTP Tool

Make HTTP requests with authentication support.

```yaml
- step: api_call
  tool:
    kind: http
    url: "https://api.example.com/endpoint"
    method: POST                    # GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS
    headers:
      Content-Type: application/json
      Authorization: "Bearer {{ token }}"
    params:                         # Query parameters
      page: 1
    body: |                         # Raw body
      {"key": "value"}
    json:                           # JSON body (alternative to body)
      key: value
    timeout_seconds: 30
    follow_redirects: true
    response_type: json             # json|text|binary
    auth:                           # Authentication
      source: adc                   # GCP Application Default Credentials
```

**Authentication Options:**

```yaml
auth:
  source: adc           # GCP ADC (automatic token)
  # or
  type: bearer
  credential: "keychain-name"
  # or
  type: basic
  username: "user"
  password: "pass"
```

### DuckDB Tool

Query DuckDB databases for local data processing.

```yaml
- step: query_data
  tool:
    kind: duckdb
    database: ".noetl/state.duckdb"  # Database path (in-memory if omitted)
    commands: |
      SELECT * FROM resources
      WHERE status = 'active'
    as_objects: true                  # Return results as objects (default)
```

**Use Cases:**
- Local state management
- Data transformation
- Aggregation and reporting
- Caching query results

### Playbook Tool

Call sub-playbooks for modular workflow composition.

```yaml
- step: deploy_infrastructure
  tool:
    kind: playbook
    path: ./infrastructure/postgres.yaml
    args:
      action: deploy
      namespace: "{{ workload.namespace }}"
```

### Noop Tool

No-operation tool for routing-only steps.

```yaml
- step: router
  tool:
    kind: noop
  next:
    - step: path_a
      when: "{{ workload.mode == 'a' }}"
    - step: path_b
      when: "{{ workload.mode == 'b' }}"
```

## Rhai Scripting Engine

Rhai is an embedded scripting language for complex logic, polling operations, and conditional workflows.

### Basic Usage

```yaml
- step: compute
  tool:
    kind: rhai
    code: |
      let x = 10;
      let y = 20;
      let result = x + y;
      log(`Computed: ${result}`);
      result
    args:
      input: "{{ workload.value }}"
```

### Available Functions

#### Logging Functions

```rhai
log(msg)      // Info level logging
print(msg)    // Alias for log
debug(msg)    // Debug level
info(msg)     // Info level
warn(msg)     // Warning level
error(msg)    // Error level
```

#### Time Functions

```rhai
timestamp()      // Unix timestamp as string
timestamp_ms()   // Unix timestamp in milliseconds
sleep(seconds)   // Sleep synchronously (i64)
sleep_ms(millis) // Sleep in milliseconds (i64)
```

#### JSON Functions

```rhai
parse_json(str)  // Parse JSON string into Rhai Dynamic
to_json(value)   // Convert Rhai value to JSON string
```

#### String Functions

```rhai
contains(str, substr)       // Check if string contains substring
contains_any(str, array)    // Check if string contains any from array
```

#### HTTP Functions

```rhai
// Basic requests
http_get(url)               // GET request, returns body
http_post(url, body)        // POST request with body
http_delete(url)            // DELETE request

// Authenticated requests (Bearer token)
http_get_auth(url, token)
http_post_auth(url, body, token)
http_delete_auth(url, token)
```

**HTTP Response Object:**
```rhai
let response = http_get_auth(url, token);
// response.status   - HTTP status code (i64)
// response.body     - Parsed JSON body (Dynamic)
// response.body_raw - Raw response body (string)
```

#### Authentication Functions

```rhai
get_gcp_token()  // Get GCP Application Default Credentials token
```

### Polling Example

Wait for a GKE cluster to become ready:

```yaml
- step: wait_for_cluster
  tool:
    kind: rhai
    code: |
      let token = get_gcp_token();
      let url = `https://container.googleapis.com/v1/projects/${args.project_id}/locations/${args.region}/clusters/${args.cluster_name}`;

      log("");
      log("Waiting for cluster to be ready...");

      let max_retries = 60;
      let retry_count = 0;
      let final_status = "UNKNOWN";

      while retry_count < max_retries {
        retry_count += 1;

        let response = http_get_auth(url, token);

        if response.status == 200 {
          let cluster_status = response.body.status;
          log(`[${timestamp()}] Cluster status: ${cluster_status} (attempt ${retry_count}/${max_retries})`);

          if cluster_status == "RUNNING" {
            log("");
            log("Cluster is now RUNNING");
            final_status = "RUNNING";
            break;
          } else if cluster_status == "ERROR" || cluster_status == "DEGRADED" {
            throw `Cluster reached error state: ${cluster_status}`;
          }
        } else if response.status == 404 {
          log(`[${timestamp()}] Cluster not yet visible`);
        }

        sleep(10);
      }

      if final_status != "RUNNING" {
        throw `Timeout waiting for cluster after ${max_retries * 10} seconds`;
      }

      // Return result as map
      #{ status: final_status, attempts: retry_count }
    args:
      project_id: "{{ workload.project_id }}"
      cluster_name: "{{ workload.cluster_name }}"
      region: "{{ workload.region }}"
```

### Rhai Data Types

```rhai
// Primitives
let num = 42;
let float = 3.14;
let text = "string";
let flag = true;

// Arrays
let arr = [1, 2, 3];
arr.push(4);
let first = arr[0];

// Maps (objects)
let obj = #{ name: "test", value: 100 };
obj.new_field = "added";
let name = obj.name;

// String interpolation
let msg = `Value is ${num}`;
```

## Template Engine

NoETL uses a Jinja2-compatible template engine (Minijinja) for variable substitution.

### Syntax

```yaml
# Variable access
url: "{{ workload.api_url }}/endpoint"

# Filters
name: "{{ input | upper }}"
encoded: "{{ secret | b64encode }}"

# Conditionals in templates
value: "{% if workload.enabled %}active{% else %}inactive{% endif %}"

# Loops in templates
items: "{% for item in list %}{{ item }},{% endfor %}"
```

### Built-in Filters

| Filter | Description |
|--------|-------------|
| `int` | Convert to integer |
| `float` | Convert to float |
| `tojson` | Serialize to JSON |
| `fromjson` | Parse from JSON |
| `upper` | Uppercase string |
| `lower` | Lowercase string |
| `trim` | Trim whitespace |
| `replace(old, new)` | Replace substring |
| `split(delim)` | Split into array |
| `join(delim)` | Join array into string |
| `length` / `len` | Get length |
| `first` | Get first element |
| `last` | Get last element |
| `b64encode` | Base64 encode |
| `b64decode` | Base64 decode |
| `default(value)` / `d` | Default if empty |

### Variable Access

```yaml
# Workload variables
"{{ workload.key }}"

# Step variables (from vars block)
"{{ vars.key }}"

# Previous step results
"{{ step_name }}"            # Full result
"{{ step_name.field }}"      # Nested access

# Built-in variables
"{{ execution_id }}"
"{{ step }}"
```

## Configuration

### Playbook Executor Block

```yaml
executor:
  profile: local              # local|distributed|auto
  version: noetl-runtime/1
  requires:
    tools:
      - shell
      - http
      - rhai
    features:
      - jinja2
      - case_v1
```

### CLI Options

```bash
# Basic execution
noetl exec ./playbook.yaml -r local

# With variables (override workload)
noetl exec ./playbook.yaml -r local --set key=value --set other=value2

# Target specific step (skip to step)
noetl exec ./playbook.yaml -r local --target deploy_step

# Dry-run (validate only, no execution)
noetl exec ./playbook.yaml -r local --dry-run

# Verbose output
noetl exec ./playbook.yaml -r local --verbose

# With input JSON file
noetl exec ./playbook.yaml -r local --input vars.json

# With inline payload
noetl exec ./playbook.yaml -r local --payload '{"key":"value"}'
```

### Environment Variables

```bash
# Logging
RUST_LOG=info,noetl=debug

# GCP authentication (for ADC)
GOOGLE_APPLICATION_CREDENTIALS=/path/to/service-account.json
```

## Execution Context

Every tool receives an execution context with:

```rust
ExecutionContext {
    execution_id: i64,           // Unique execution ID
    step: String,                // Current step name
    variables: HashMap<...>,     // All available variables
    secrets: HashMap<...>,       // Decrypted secrets
    call_index: usize,           // Call index within step
}
```

## Error Handling

### Tool Errors

| Error Type | Description |
|------------|-------------|
| `NotFound` | Tool not registered |
| `Configuration` | Invalid tool config |
| `Process` | Process execution failed |
| `Timeout` | Operation timed out |
| `Template` | Template rendering error |
| `Database` | Database operation failed |
| `Script` | Script execution error |
| `Http` | HTTP request failed |
| `Authentication` | Auth error |

### Tool Result Structure

```rust
ToolResult {
    status: ToolStatus,        // Success|Error
    data: Option<Value>,       // Result data
    error: Option<String>,     // Error message
    stdout: Option<String>,    // Command stdout
    stderr: Option<String>,    // Command stderr
    exit_code: Option<i32>,    // Process exit code
    duration_ms: Option<u64>,  // Execution time
}
```

## Local vs Distributed Comparison

| Feature | Local | Distributed |
|---------|-------|-------------|
| **Execution** | In-process Rust | NATS workers |
| **Parallelism** | Sequential | Parallel (worker pool) |
| **Long-running** | Blocks CLI | Async via server |
| **State Storage** | Memory/DuckDB | PostgreSQL |
| **Dependencies** | None | NATS, PostgreSQL |
| **Tools** | shell, http, duckdb, rhai | + python, postgres, snowflake |
| **Features** | case_v1/v2, loop_v1, vars_v1 | + loop_v2 (pagination), event sourcing |

## Examples

### Simple Shell Workflow

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: build_deploy
  path: automation/build

executor:
  profile: local
  version: noetl-runtime/1

workload:
  action: build
  image: myapp

workflow:
  - step: start
    tool:
      kind: shell
      cmds:
        - echo "Starting {{ workload.action }}"
    next:
      - step: build
        when: "{{ workload.action == 'build' }}"
      - step: deploy
        when: "{{ workload.action == 'deploy' }}"

  - step: build
    tool:
      kind: shell
      cmds:
        - docker build -t {{ workload.image }} .
    next:
      - step: end

  - step: deploy
    tool:
      kind: shell
      cmds:
        - kubectl apply -f manifests/
    next:
      - step: end

  - step: end
    tool:
      kind: noop
```

### HTTP API Workflow

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: api_workflow

executor:
  profile: local

workload:
  api_url: https://api.example.com

workflow:
  - step: start
    tool:
      kind: http
      url: "{{ workload.api_url }}/status"
      method: GET
    vars:
      status: "{{ result.status }}"
    next:
      - step: process
        when: "{{ vars.status == 'ready' }}"
      - step: wait
        when: "{{ vars.status != 'ready' }}"

  - step: process
    tool:
      kind: http
      url: "{{ workload.api_url }}/data"
      method: POST
      json:
        action: process
    next:
      - step: end

  - step: wait
    tool:
      kind: rhai
      code: |
        log("Waiting for API to be ready...");
        sleep(5);
        "retry"
    next:
      - step: start

  - step: end
    tool:
      kind: noop
```

### GCP Infrastructure with Rhai

```yaml
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: gcp_cluster

executor:
  profile: local

workload:
  project_id: my-project
  cluster_name: my-cluster
  region: us-central1

workflow:
  - step: start
    tool:
      kind: shell
      cmds:
        - echo "Creating GKE cluster {{ workload.cluster_name }}"
    next:
      - step: create_cluster

  - step: create_cluster
    tool:
      kind: http
      url: "https://container.googleapis.com/v1/projects/{{ workload.project_id }}/locations/{{ workload.region }}/clusters"
      method: POST
      auth:
        source: adc
      headers:
        Content-Type: application/json
      body: |
        {
          "cluster": {
            "name": "{{ workload.cluster_name }}",
            "autopilot": { "enabled": true }
          }
        }
    next:
      - step: wait_ready

  - step: wait_ready
    tool:
      kind: rhai
      code: |
        let token = get_gcp_token();
        let url = `https://container.googleapis.com/v1/projects/${args.project}/locations/${args.region}/clusters/${args.cluster}`;

        let retries = 0;
        while retries < 60 {
          let resp = http_get_auth(url, token);
          if resp.status == 200 && resp.body.status == "RUNNING" {
            log("Cluster is ready!");
            return #{ status: "ready" };
          }
          log(`Waiting... (${retries}/60)`);
          sleep(10);
          retries += 1;
        }
        throw "Timeout waiting for cluster";
      args:
        project: "{{ workload.project_id }}"
        cluster: "{{ workload.cluster_name }}"
        region: "{{ workload.region }}"
    next:
      - step: end

  - step: end
    tool:
      kind: noop
```

## Best Practices

1. **Use local mode for development** - Faster iteration without server setup
2. **Leverage Rhai for polling** - Avoid complex shell loops
3. **Use DuckDB for local state** - Persist data between runs
4. **Validate playbooks** - Use `--dry-run` before execution
5. **Structure workflows modularly** - Use sub-playbooks for reusability
6. **Handle errors gracefully** - Use `next[].when` conditions for error paths
