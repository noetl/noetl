# NoETL Weather Examples

This directory contains example playbooks and a Jupyter notebook that demonstrate how to use NoETL to fetch and analyze weather data from the Open-Meteo API.

## Setup Options

### Option 1: Local Setup

1. Create and activate a virtual environment.
```
❯ python -m venv .venv
```

2. Activate virtual environment.
```
❯ source .venv/bin/activate
```

3. Install NoETL and required dependencies.
```
❯ pip install -e .
```

### Option 2: Docker Setup

You can run the notebook in a Docker container using the following commands:

```
❯ make build
❯ make up
```

Access the Jupyter notebook at:
```
http://localhost:8899
```

The notebook will be available at: `/home/jovyan/examples/weather/weather_examples.ipynb`

## Weather Example Playbooks

This directory contains two example playbooks:

1. `weather_example.yaml`: A simple weather data workflow for a single city
2. `weather_loop_example.yaml`: A more complex workflow that processes multiple cities and demonstrates advanced NoETL features

### Simple Weather Example (`weather_example.yaml`)

The `weather_example.yaml` playbook demonstrates a basic workflow for fetching weather data for a single city and determining if the temperature exceeds a specified threshold.

#### Key Features:

- **API Integration**: Fetches real-time weather data from the Open-Meteo API
- **Conditional Branching**: Takes different actions based on temperature thresholds
- **Parameter Customization**: Configurable city and temperature threshold

#### Workflow Breakdown:

| Step | Description | Task Used |
| :--- | :--- | :--- |
| **1. `start`** | Initiates the workflow and checks if the state is ready. | N/A |
| **2. `fetch_weather`** | Fetches weather data for the specified city from the Open-Meteo API and determines if the temperature exceeds the threshold. | `fetch_weather` |
| **3a. `report_warm`** | If the temperature exceeds the threshold, reports warm weather. | Python inline code |
| **3b. `report_cold`** | If the temperature is below the threshold, reports cold weather. | Python inline code |
| **4. `end`** | Marks the end of the workflow. | N/A |

#### Usage:

```sh
noetl playbooks --register examples/weather/weather_example.yaml
noetl playbooks --execute --path "examples/weather_example" --payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}], "temperature_threshold": 20}'
```

### Weather Loop Example (`weather_loop_example.yaml`)

The `weather_loop_example.yaml` playbook demonstrates a more complex workflow that processes multiple cities, evaluates weather conditions, and aggregates results.

#### Key Features:

- **Loops**: Iterates over multiple cities and their districts
- **Nested Workflows**: Demonstrates complex workflow structures with nested steps
- **Conditional Execution**: Uses conditions to determine execution paths
- **Data Aggregation**: Aggregates results across all cities
- **Database Integration**: Stores results in both DuckDB and PostgreSQL

#### Workflow Breakdown:

| Step | Description |
| :--- | :--- |
| **1. `start`** | Initiates the workflow and checks if the state is ready. |
| **2. `city_loop`** | Iterates over the list of cities. |
| **3. `fetch_and_evaluate`** | Fetches and evaluates weather data for each city. |
| **4a. `alert_step`** | If the temperature exceeds the threshold, sends an alert. |
| **4b. `log_step`** | If the temperature is below the threshold, logs the result. |
| **5. `get_city_districts`** | Fetches the districts of the city. |
| **6. `district_loop`** | Iterates over the districts of the city. |
| **7. `process_district`** | Processes each district. |
| **8. `end_district_loop`** | Ends the district loop. |
| **9. `end_city_loop`** | Ends the city loop. |
| **10. `aggregate_alerts`** | Aggregates results after all city loops complete. |
| **11. `log_aggregate_result`** | Logs the aggregated alert summary. |
| **12. `global_alert_step`** | If any city triggered an alert, sends a global alert. |
| **13. `store_aggregate_result`** | Stores the aggregated alert summary in DuckDB/Postgres. |
| **14. `end`** | Marks the end of the workflow. |

#### Usage:

```sh
noetl playbooks --register examples/weather/weather_loop_example.yaml
noetl playbooks --execute --path "examples/weather_loop_example" --payload '{"cities": [{"name": "New York", "lat": 40.71, "lon": -74.01}, {"name": "London", "lat": 51.51, "lon": -0.13}], "temperature_threshold": 25}'
```

## Jupyter Notebook: Weather Examples

The `weather_examples.ipynb` notebook demonstrates how to use NoETL with the weather example playbooks. It covers:

1. Registering the weather playbooks with the NoETL catalog
2. Executing the playbooks with custom payloads
3. Validating the results by querying the tables created in Postgres and DuckDB
4. Visualizing the temperature data from the playbook executions

### Key Features:

- **API Integration**: Shows how to interact with the NoETL API to register and execute playbooks
- **Database Queries**: Demonstrates how to query Postgres using the NoETL API's `/postgres/execute` endpoint
- **Data Export**: Shows how to export execution data to DuckDB for further analysis
- **Data Visualization**: Includes visualizations of temperature data using matplotlib
- **Registration and execution workflow**: Provides a complete workflow from playbook registration to result analysis

### Prerequisites:

Before running the notebook, make sure you have:

1. The NoETL server running
2. Postgres database running
3. The weather example playbooks available in the `examples/weather` directory

This notebook is designed to run in the Jupyter container provided by the NoETL docker-compose setup.

### What is in it:

- How to register playbooks with the NoETL catalog
- How to execute playbooks with custom payloads
- How to query the Postgres database to validate execution results
- How to export data to DuckDB for further analysis
- How to visualize temperature data from playbook executions

This workflow can be adapted for other NoETL playbooks to register, execute, and analyze their results.