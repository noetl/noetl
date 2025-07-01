# Not Only ETL

__NoETL__ is an automation framework for data processing and mlops orchestration.

## Prerequisites

1. Python 3.12+
2. Postgres database
3. Docker
4. Folders created:
   - `data/input` - for input payload files
   - `data/exports` - for exported execution data

## Installation

### Local Installation

1. Install uv package manager:
   ```bash
   make install-uv
   ```

2. Python virtual environment:
   ```bash
   make create-venv
   ```

3. Activate the virtual environment:
   ```bash
   source .venv/bin/activate
   ```

4. Install dependencies:
   ```bash
   make install
   ```

### Docker Installation

1. Build the Docker containers:
   ```bash
   make build
   ```

2. Start the Docker containers:
   ```bash
   make up
   ```

## Running NoETL

### Running the NoETL Server

The NoETL server provides a REST API for managing and executing playbooks.

#### Local Server

```bash
noetl server
```

Options:
- `--host`: Server host (default: 0.0.0.0)
- `--port`: Server port (default: 8082)
- `--reload`: Enable auto-reload for development (default: False)

Example:
```bash
noetl server --port 8082
```

#### Docker Server

The server:
```bash
make up
```

### Using the CLI

NoETL provides a command-line interface.

#### Catalog Management

Register a playbook in the catalog:
```bash
# noetl playbook --register path/to/playbook.yaml
noetl playbook --register playbook/secrets_test.yaml --host localhost --port 8080
noetl playbook --register playbook/load_dict_test.yaml --port 8080
noetl playbook --register playbook/weather_example.yaml --port 8080
```

#### Executing Playbooks

Execute a playbook from the catalog:
```bash
noetl execute <playbook_path> <version> [options]
```

Options:
- `--input`, `-i`: Path to the input JSON file
- `--async`, `-a`: Execute the playbook asynchronously
- `--host`: API host (default: 0.0.0.0)
- `--port`: API port (default: 8082)

## API Endpoints

The NoETL API provides the following endpoints:

### Playbook Execution

- `POST /playbook/execute`: Execute a playbook synchronously
- `POST /playbook/execute-async`: Execute a playbook asynchronously

### Catalog Management

- `POST /catalog/register`: Register a playbook in the catalog
- `GET /catalog/`: View the catalog
- `POST /catalog/upload`: Upload a playbook to the catalog

### Events

- `GET /events/`: View events
- `POST /events/emit`: Emit an event

## Monitoring Execution

```bash
noetl execute path/playbook 1.0.0 --async
```
The event ID is returned when executing a playbook asynchronously.  

view the events in the web interface at:
```
http://localhost:8082/events/query?event_id=<event_id>
```

## 1. Running the NoETL Agent

There are two ways to run the NoETL agent from the command line:

### 1.1. Using the `noetl agent` Command

run the NoETL agent using the `noetl agent` command:

```bash
source .venv/bin/activate

noetl agent -f ./catalog/playbooks/weather_example.yaml --debug
```

all options:

```bash
noetl agent \
  -f ./catalog/playbooks/weather_example.yaml \
  --mock \
  -o plain \
  --export ./data/exports/execution_data.parquet \
  --mlflow \
  --pgdb "dbname=noetl user=noetl password=noetl host=localhost port=5434" \
  --input ./data/input/payload.json \
  --debug
```

Command line with payload:

```bash
noetl agent \
  -f ./catalog/playbooks/weather_example.yaml \
  --payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}], "temperature_threshold": 20}' \
  --debug
```

merge mode to merge payload input data with playbook's workload data:

```bash
noetl agent \
  -f ./catalog/playbooks/weather_example.yaml \
  --payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}], "temperature_threshold": 20}' \
  --merge \
  --debug
```

### 1.2. Using the `agent.py` script

run the agent using the `agent.py` script:

```bash
source .venv/bin/activate

python noetl/agent.py -f ./catalog/playbooks/weather_example.yaml --debug
```

all options:

```bash
python noetl/agent.py \
  -f ./catalog/playbooks/weather_example.yaml \
  --mock \
  -o plain \
  --export ./data/exports/execution_data.parquet \
  --mlflow \
  --pgdb "dbname=noetl user=noetl password=noetl host=localhost port=5434" \
  --input ./data/input/payload.json \
  --debug
```

Example with payload string in the command line:

```bash
python noetl/agent.py \
  -f ./catalog/playbooks/weather_example.yaml \
  --payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}], "temperature_threshold": 20}' \
  --debug
```

merge mode that merges payload with workload data:

```bash
python noetl/agent/agent.py \
  -f ./catalog/playbooks/weather_example.yaml \
  --payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}], "temperature_threshold": 20}' \
  --merge \
  --debug
```

### Command Line Options

The agent supports the following command line options:

- `-f, --file`: Path to playbook YAML file (required)
- `--mock`: Run in mock mode
- `-o, --output`: Output format (json or plain)
- `--export`: Export execution data to Parquet file (e.g., ./data/exports/execution_data.parquet)
- `--mlflow`: Use ML model for workflow control (future feature)
- `--pgdb`: Postgres connection string
- `--input`: Path to JSON file with input payload for the playbook
- `--payload`: JSON string with input payload for the playbook
- `--merge`: Whether to merge the input payload with the workload section. Default: False. If omitted, overrides values in the workload with the input payload.
- `--debug`: Debug logging mode

### Input Payload

You can provide the input payload to the agent in two ways:

1. Using the `--input` option: Provide a path to a JSON file containing the payload.
2. Using the `--payload` option: Provide the JSON payload directly as a string on the command line.

The payload should contain the parameters required by the playbook.

By default, the agent will override the workload section with the input payload if `--merge` is omitted. This means that keys in the input payload will replace the corresponding keys in the workload. 
If you use the `--merge` option, the NoETL agent will merge the input payload with the workload section instead of replacing the keys.

For example, if the playbook has a workload section like this:
```yaml
workload:
  cities:
    - name: "London"
      lat: 51.51
      lon: -0.13
  temperature_threshold: 25
  base_url: "https://api.open-meteo.com/v1"
```

And you execute it with `--payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}], "temperature_threshold": 20}'`:
- In override mode (default): The resulting workload will only contain the keys from the payload: `{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}], "temperature_threshold": 20, "base_url": "https://api.open-meteo.com/v1"}`

or `--payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}], "temperature_threshold": 20}' --merge`:
- In merge mode (`--merge`): The resulting workload will be `{"cities": [{"name": "London", "lat": 51.51, "lon": -0.13}, {"name": "New York", "lat": 40.71, "lon": -74.01}], "temperature_threshold": 20, "base_url": "https://api.open-meteo.com/v1"}`

For example, for the weather_example.yaml playbook, you can create a payload.json file with:

```json
{
  "cities": [
    {
      "name": "New York",
      "lat": 40.71,
      "lon": -74.01
    }
  ],
  "temperature_threshold": 20
}
```

## 2. Using the Test Script

The test script to run the agent with the weather example playbook:

```bash
chmod +x bin/test_weather_example.sh

./bin/test_weather_example.sh
```

This script runs the agent with the weather_example.yaml playbook and redirects the output to a log file at `./data/log/agent.log`.

## 3. Using the REST API

The NoETL has a REST API server. To use the API:

### 3.1. Start the NoETL Server

```bash
source .venv/bin/activate

noetl server --host 0.0.0.0 --port 8082
```

if the port is already in use, force start the server by killing the process using the port:
```shell
noetl server --host 0.0.0.0 --port 8082 --force
```

Or use the Makefile:

```bash
make run
```

### 3.2. Register a Playbook in the NoETL Catalog

Before executing a playbook through the  NoETL API, you need to register it in the NoETL catalog:

```bash
PLAYBOOK_BASE64=$(base64 -i ./catalog/playbooks/weather_example.yaml)

curl -X POST "http://localhost:8082/catalog/register" \
  -H "Content-Type: application/json" \
  -d "{\"content_base64\": \"$PLAYBOOK_BASE64\"}"
```

### 3.3. Execute the Agent Synchronously

```bash
curl -X POST "http://localhost:8082/agent/execute" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "workflows/weather/weather_loop_example",
    "version": "0.1.0",
    "input_payload": {
      "cities": [
        {
          "name": "New York",
          "lat": 40.71,
          "lon": -74.01
        }
      ]
    },
    "sync_to_postgres": true
  }'
```

### 3.4. Execute the Agent Asynchronously

```bash
curl -X POST "http://localhost:8082/agent/execute-async" \
  -H "Content-Type: application/json" \
  -d '{
    "path": "workflows/weather/weather_loop_example",
    "version": "0.1.0",
    "input_payload": {
      "cities": [
        {
          "name": "New York",
          "lat": 40.71,
          "lon": -74.01
        }
      ]
    },
    "sync_to_postgres": true
  }'
```

### 3.5. NoETL CLI to Manage Playbooks

Use the NoETL CLI to register and execute playbooks:

#### 3.5.1. Registering a Playbook

```bash
source .venv/bin/activate

noetl playbook --register ./catalog/playbooks/weather_example.yaml

noetl playbook --register ./catalog/playbooks/weather_example.yaml --host localhost --port 8082
```

This command reads the specified file, encodes it in base64, and sends it to the NoETL server for registration. 

#### 3.5.2. Executing a Playbook

To execute a playbook already registered in the catalog:
1. Execute a playbook by path with a JSON string payload
```bash
noetl playbook --execute --path "workflows/weather/weather_loop_example" --payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}]}'
```
2. Execute a playbook using a JSON file for input payload
```bash
noetl playbook --execute --path "workflows/weather/weather_loop_example" --input ./data/input/payload.json
```
3. Execute a playbook using the latest version (omit --version)
```bash
noetl playbook --execute --path "workflows/weather/weather_loop_example" --payload '{"cities": [{"name": "Chicago", "lat": 41.88, "lon": -87.63}]}'
```
4. Execute a playbook on a different server
```bash
noetl playbook --execute --path "workflows/weather/weather_loop_example" --host localhost --port 8082 --payload '{"cities": [{"name": "London", "lat": 51.51, "lon": -0.13}]}'
```
5. Execute a playbook with merge mode (merge payload with workload)
```bash
noetl playbook --execute --path "workflows/weather/weather_loop_example" --payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}], "temperature_threshold": 30}' --merge
```

The server will retrieve the playbook from the catalog based on the provided path and version. If no version is specified, the server will automatically use the latest version available for the given path. 

By default, the server will override the workload section with the input payload. This means that keys in the input payload will replace the corresponding keys in the workload. If you use the `--merge` option, the server will merge the input payload with the workload section instead of replacing the keys.

For example, if the playbook has a workload section like this:
```yaml
workload:
  cities:
    - name: "London"
      lat: 51.51
      lon: -0.13
  temperature_threshold: 25
  base_url: "https://api.example.com"
```

And you execute it with `--payload '{"cities": [{"name": "Paris", "lat": 48.85, "lon": 2.35}]}'`:
- In override mode (default): The resulting workload will only contain the keys from the payload: `{"cities": [{"name": "Paris", "lat": 48.85, "lon": 2.35}]}`
- In merge mode (`--merge`): The resulting workload will be `{"cities": [{"name": "Paris", "lat": 48.85, "lon": 2.35}], "temperature_threshold": 25, "base_url": "https://api.example.com"}`

#### 3.5.3. Command Options

The `playbook` command supports the following options:

- `--register, -r`: Path to the playbook YAML file to register
- `--execute, -e`: Execute a playbook by path
- `--path`: Path of the playbook to execute
- `--version, -v`: Version of the playbook to execute (if omitted, latest version will be used)
- `--input, -i`: Path to JSON file with input payload for the playbook
- `--payload`: JSON string with input payload for the playbook
- `--host`: NoETL server host (default: localhost)
- `--port, -p`: NoETL server port (default: 8082)
- `--sync-to-postgres`: Whether to sync execution data to PostgreSQL (default: true)
- `--merge`: Whether to merge the input payload with the workload section (default: false, which means override)

## 4. Using Docker

You can run the NoETL using Docker:

### 4.1. Build and Start the Docker Containers

```bash
make build
make up
```

### 4.2. Use the API as Described in Section 3

By default, API will be available at `http://localhost:8082`.

## 5. Viewing Results

After running the agent, you can view the results in several ways:

1. Check the output in the terminal (if using `-o plain` or `-o json`)
2. Check the log file (if redirecting output to a log file)
3. Check the PostgreSQL database for execution data
4. Open the Jupyter notebook at `notebook/agent007_mission_report.ipynb` and set the `db_path` variable to the path of the DuckDB database file
5. Examine the exported execution data in the Parquet file (if using the `--export` option)

### Exported Data

When using the `--export` option, the agent exports execution data to a Parquet file. This file contains detailed information about the execution of the playbook, including:

- Step execution details
- Input and output data for each step
- Execution times
- Error information (if any)

You can analyze this data using tools like Pandas, DuckDB, or any other tool that supports Parquet files.

#### Analyzing Execution Data

The project includes a Python script to analyze the execution data:
1. Run the analysis script with default options
```bash
python notebook/execution_data_reader.py
```
2. Run with custom input file and output directory
```bash
python notebook/execution_data_reader.py --input ./my_data.parquet --output-dir ./analysis
```
3. Filter the data
```bash
python notebook/execution_data_reader.py --filter "status = 'success'"
```
4. List all event types in the file
```bash
python notebook/execution_data_reader.py --list-events
```
5. Export results in JSON format
```bash
python notebook/execution_data_reader.py --format json
```

Command-line options:
- `--input PATH`: Path to the input Parquet file
- `--output-dir PATH`: Directory to save output files
- `--filter FILTER`: SQL WHERE clause to filter events
- `--verbose`: Enable verbose output
- `--quiet`: Suppress all output except errors
- `--list-events`: List all event types in the file and exit
- `--list-steps`: List all steps in the file and exit
- `--format FORMAT`: Output format for tables (text, csv, json)
- `--no-plots`: Disable plot generation even if matplotlib is available
- `--help`: Show help message and exit


## Example Playbooks

The project includes several example playbooks in the `playbook/` directory to demonstrate different NoETL capabilities:

### Core Examples

#### 1. Weather Example (`weather_example.yaml`)
A simple playbook that fetches weather data for given cities and checks if the temperature exceeds a threshold. Great for learning basic NoETL concepts.

#### 2. Load Dict Test (`load_dict_test.yaml`)
Demonstrates DuckDB integration with PostgreSQL, including table creation, data manipulation, and cross-database operations.
- **Documentation**: [load_dict_test_example.md](docs/examples/load_dict_test_example.md)
- **Purpose**: Testing DuckDB PostgreSQL extension functionality
- **Use Cases**: Database integration, data transfer workflows, testing setups

#### 3. GCS Secrets Example (`gcs_secrets_example.yaml`)
Shows Google Cloud Storage authentication using Google Secret Manager with secure HMAC credential handling.
- **Documentation**: [gcp_secrets_example.md](docs/examples/gcp_secrets_example.md)
- **Purpose**: Secure cloud storage operations with secrets management
- **Use Cases**: GCS file uploads, secure credential handling, cloud data workflows

### Additional Examples

#### Database Examples
- `postgres_test.yaml`: PostgreSQL database operations and testing
- `gs_duckdb_postgres_example.yaml`: Google Storage with DuckDB and PostgreSQL integration

#### Secrets Management
- `secrets_example.yaml`: Basic secrets handling demonstration
- `secrets_test.yaml`: Secrets functionality testing
- `test_secrets.yaml`: Additional secrets testing scenarios

#### Advanced Workflows
- `multi_playbook_example.yaml`: Demonstrates complex multi-step workflows
- `load_ng_v2.yaml`: Next-generation data loading patterns
- `attach_example.yaml`: File attachment and processing examples

### Quick Start with Examples

#### Running the Weather Example
```bash
# Register the playbook
noetl playbook --register playbook/weather_example.yaml --port 8080

# Execute with custom cities
noetl playbook --execute --path "workflows/weather/weather_loop_example" \
  --payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}], "temperature_threshold": 20}'
```

#### Running the DuckDB Test Example
```bash
# Register the playbook
noetl playbook --register playbook/load_dict_test.yaml --port 8080

# Execute (requires PostgreSQL running)
noetl playbook --execute --path "workflows/data/load_dict_test"
```

#### Running the GCS Secrets Example
```bash
# Register the playbook
noetl playbook --register playbook/gcs_secrets_example.yaml --port 8080

# Execute with your GCP project
noetl playbook --execute --path "workflows/examples/gcs_secrets_example" \
  --payload '{"GOOGLE_CLOUD_PROJECT": "your-project-id"}'
```

### Documentation Structure

Each major example includes comprehensive documentation:
- **Overview**: Purpose and use cases
- **Prerequisites**: Required setup and dependencies
- **Configuration**: Environment variables and parameters
- **Workflow Steps**: Detailed step-by-step execution
- **Troubleshooting**: Common issues and solutions
- **Security Considerations**: Best practices (for cloud examples)

### Example Categories

| Category | Examples | Purpose |
|----------|----------|---------|
| **Basic Workflows** | `weather_example.yaml` | Learning NoETL fundamentals |
| **Database Integration** | `load_dict_test.yaml`, `postgres_test.yaml` | Database operations and testing |
| **Cloud Storage** | `gcs_secrets_example.yaml`, `gs_duckdb_postgres_example.yaml` | Cloud data operations |
| **Secrets Management** | `secrets_example.yaml`, `secrets_test.yaml` | Secure credential handling |
| **Advanced Patterns** | `multi_playbook_example.yaml`, `load_ng_v2.yaml` | Complex workflow patterns |

### Getting Help

For detailed information about any specific playbook:
1. Check the individual README files in the `playbook/` directory
2. Review the HOW_TO_RUN guides:
   - [HOW_TO_RUN.md](playbook/HOW_TO_RUN.md) - General execution guide
   - [HOW_TO_RUN_GCS_SECRETS.md](playbook/HOW_TO_RUN_GCS_SECRETS.md) - GCS-specific guide
   - [HOW_TO_RUN_SUMMARY.md](playbook/HOW_TO_RUN_SUMMARY.md) - Quick reference
3. Consult the main [playbook README](playbook/README.md) for an overview
