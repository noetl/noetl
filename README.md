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
noetl catalog register path/to/playbook.yaml
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

The project includes example in the `catalog/playbooks` directory:

`weather_example.yaml`: A simple playbook that fetches weather data for given cities and checks if the temperature exceeds a threshold.

## Testing

Several test scripts to verify that the functionality works correctly:

### Running the Tests

run the tests using the Makefile or Python:

#### Using the Makefile

```bash
make test-setup
make test
make test-server-api
make test-server-api-unit
make test-parquet-export
make test-keyval
```

#### Using Python Directly

```bash
pytest -v --cov=noetl tests/
python tests/test_server_api.py
python tests/test_server_api_unit.py
python tests/test_parquet_export.py
```

### Test Descriptions

1. **Server API Tests** (`test_server_api.py`):
   - Starts the server in a separate process on port 8083 (different from the default 8082 to avoid conflicts)
   - Tests uploading a playbook to the catalog
   - Tests listing playbooks from the catalog
   - Tests executing a playbook synchronously
   - Tests executing a playbook asynchronously
   - Cleans up after the tests

2. **Server API Unit Tests** (`test_server_api_unit.py`):
   - Tests the catalog service functions (register, fetch, list)
   - Tests the agent service functions (execute)
   - Uses mocking to isolate the functionality being tested

3. **Parquet Export Tests** (`test_parquet_export.py`):
   - Runs the agent with the `--export` option to generate a Parquet file
   - Tries to read the generated Parquet file using DuckDB
   - Verifies that the file can be read without errors

4. **Key-Value Tests** (`test_keyval.py`):
   - Tests the key-value storage functionality
   - Verifies that keys can be set, retrieved, and deleted

5. **Payload Tests** (`test_payload.py`):
   - Tests the payload handling functionality
   - Verifies that payloads can be properly processed

6. **Playbook Tests** (`test_playbook.py`):
   - Tests the playbook execution functionality
   - Verifies that playbooks can be loaded and executed correctly

## Troubleshooting

1. Check that Postgres is running and accessible
2. Check that the playbook YAML file is valid
3. Check the log files for error messages
4. Make sure the environment variables are set correctly
5. Ensure the required directories exist:
   - `data/input` - for input payload files
   - `data/exports` - for exported execution data
   ```bash
   mkdir -p data/input data/exports
   ```
6. If using the `--input` option, make sure the payload.json file exists and has the correct format
7. If using the `--export` option, make sure the exports directory exists and is writable

### Port Already in Use

If you see an error like `[Errno 48] error while attempting to bind on address ('0.0.0.0', 8082): [errno 48] address already in use` when starting the server, there are several options:

1. Use a different port:
   ```bash
   noetl server --port 8083
   ```

2. Force start the server by killing the process using the port:
   ```bash
   noetl server --port 8082 --force
   ```

3. Use the standalone killer.py script:
   ```bash
   # Using the module directly
   python -m noetl.killer 8082

   # Using the installed command (after pip install)
   noetl-port-killer 8082

   # With verbose output
   noetl-port-killer 8082 --verbose

   # After freeing the port, start the server
   noetl server --port 8082
   ```

4. Manually kill the process:
   ```bash
   # mac/linux
   lsof -i :8082 
   kill -9 <PID> 

   # windows
   netstat -ano | findstr :8082  
   taskkill /F /PID <PID> 
   ```

## License
NoETL is available under the MIT License.
