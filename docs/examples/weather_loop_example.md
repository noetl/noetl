# Weather Example Playbook Documentation

## Overview
The `weather_example.yaml` playbook demonstrates an advanced weather data workflow that iterates over multiple cities, fetches weather data for each, evaluates temperature conditions, and processes city districts. It showcases loops, nested loops, conditional branching, and integration with PostgreSQL.

## Playbook Details
- **API Version**: noetl.io/v1
- **Kind**: Playbook
- **Name**: weather_example
- **Path**: workflows/examples/weather_example
- **Description**: Advanced weather data workflow with loops and conditions

## Purpose
This playbook demonstrates:
- Iterating over collections using loops
- Nested loops for hierarchical data processing
- Conditional workflow branching based on data evaluation
- Filtering loop items with conditions
- Aggregating results from multiple iterations
- Integration with PostgreSQL for data storage
- Complex data processing and decision making

## Workload Configuration

### Environment Variables
The playbook uses the following environment variables with default fallbacks:

| Variable | Default | Description |
|----------|---------|-------------|
| `job.uuid` | Generated UUID | Unique job identifier |

### Additional Configuration
- **State**: ready (controls workflow execution)
- **Cities**: List of cities (London, Paris, Berlin) with coordinates
- **Temperature Threshold**: 26°C
- **Base URL**: https://api.open-meteo.com/v1

## Workflow Steps

### 1. Start Step
- **Description**: Start Weather Analysis Workflow
- **Condition**: Checks if workload.state is "ready"
- **Next**: city_loop (if ready) or end (if not ready)

### 2. City Loop Step
- **Description**: Iterate over cities
- **Loop Configuration**:
  - Collection: workload.cities
  - Iterator: city
- **Next**: fetch_and_evaluate (for each city)

### 3. Fetch and Evaluate Step
- **Description**: Fetch and evaluate weather for one city
- **Type**: workbook
- **Workbook**: evaluate_weather_directly
- **Parameters**:
  - city: Current city in the loop
  - base_url: API base URL
  - threshold: Temperature threshold
- **Next**: Based on temperature evaluation:
  - alert_step and get_city_districts (if temperature > threshold)
  - log_step and get_city_districts (if temperature ≤ threshold)

### 4. Get City Districts Step
- **Description**: Fetch the districts of the city
- **Type**: workbook
- **Workbook**: get_city_districts
- **Parameters**:
  - city: Current city name
- **Next**: district_loop

### 5. District Loop Step
- **Description**: Iterate over districts of the city
- **Loop Configuration**:
  - Collection: districts
  - Iterator: district
  - Filter: Excludes districts named "Mordor"
- **Next**: process_district (for each district)

### 6. Process District Step
- **Description**: Process a single district
- **Type**: workbook
- **Workbook**: process_district
- **Parameters**:
  - city: Current city
  - district: Current district
- **Next**: end_district_loop

### 7. End District Loop Step
- **Description**: End of the district loop
- **Loop End**: district_loop
- **Result**: Collects outputs from district processing
- **Next**: end_city_loop

### 8. End City Loop Step
- **Description**: End of the city loop
- **Loop End**: city_loop
- **Result**: Collects alerts from all cities
- **Next**: aggregate_alerts

### 9. Aggregate Alerts Step
- **Description**: Aggregate results after all city loops complete
- **Type**: workbook
- **Workbook**: aggregate_alerts_task
- **Parameters**:
  - alerts: Collected alerts from all cities
- **Next**: 
  - log_aggregate_result
  - global_alert_step (if any city triggered an alert)
  - end (if no alerts)

### 10. Log Aggregate Result Step
- **Description**: Log the aggregated alert summary
- **Type**: workbook
- **Workbook**: log_aggregate_result_task
- **Parameters**:
  - summary: Alert summary
- **Next**: store_aggregate_result

### 11. Global Alert Step
- **Description**: Send a global alert if any city triggered an alert
- **Type**: workbook
- **Workbook**: global_alert_task
- **Parameters**:
  - summary: Alert summary
- **Next**: store_aggregate_result

### 12. Store Aggregate Result Step
- **Description**: Store the aggregated alert summary in PostgreSQL
- **Type**: workbook
- **Workbook**: store_aggregate_result_task_postgres_pipeline
- **Parameters**:
  - summary: Alert summary
- **Next**: end

### 13. End Step
- **Description**: End of workflow

## Workbook Tasks

### Evaluate Weather Directly Task (`evaluate_weather_directly`)

#### Purpose
Fetches weather data from the Open-Meteo API and evaluates if the temperature exceeds the threshold.

#### Parameters
- **city**: City object with name, latitude, and longitude
- **threshold**: Temperature threshold for alerting
- **base_url**: Base URL for the API

#### Operations
1. **API Request**:
   - Constructs a request to the Open-Meteo forecast API
   - Includes latitude, longitude, and hourly temperature parameters

2. **Data Processing**:
   - Extracts temperature data from the API response
   - Calculates the maximum temperature
   - Determines if an alert is needed based on the threshold

3. **Return Value**:
   ```json
   {
     "city": "City Name",
     "max_temp": 25.5,
     "alert": true
   }
   ```

### Get City Districts Task (`get_city_districts`)

#### Purpose
Fetches the districts of a city from a geo-service API.

#### Parameters
- **city**: City name

#### Operations
- Makes an HTTP GET request to a geo-service API
- Returns a list of districts for the city

### Process District Task (`process_district`)

#### Purpose
Processes a single district of a city.

#### Parameters
- **city**: City object
- **district**: District object

#### Operations
- Performs processing on the district
- Returns a result object with city name, district name, processed status, and timestamp

### Aggregate Alerts Task (`aggregate_alerts_task`)

#### Purpose
Aggregates alerts from all cities and determines if a global alert is needed.

#### Parameters
- **alerts**: List of alert objects from all cities

#### Operations
- Counts the number of cities with alerts
- Creates a summary with alert cities and count
- Determines if a global alert is needed

### Store Aggregate Result Task (`store_aggregate_result_task_postgres_pipeline`)

#### Purpose
Stores the aggregated alert summary in DuckDB and PostgreSQL.

#### Parameters
- **summary**: Alert summary object

#### Operations
1. **Database Setup**:
   - Connects to DuckDB
   - Installs and loads PostgreSQL extension
   - Attaches PostgreSQL database

2. **Data Storage**:
   - Creates tables in DuckDB and PostgreSQL if they don't exist
   - Inserts the alert summary into both databases

## Running the Playbook

### Direct Execution
```bash
noetl agent -f playbook/weather_example.yaml
```

### Register and Execute from Catalog
```bash
# Register in the catalog
noetl playbook --register playbook/weather_example.yaml

# Execute from the catalog
noetl playbook --execute --path "workflows/examples/weather_example"
```

### Execute with Custom Parameters
```bash
noetl playbook --execute --path "workflows/examples/weather_example" --payload '{
  "cities": [
    {
      "name": "New York",
      "lat": 40.71,
      "lon": -74.01
    }
  ],
  "temperature_threshold": 30
}'
```

## Advanced Features Demonstrated

### 1. Loop Iteration
The playbook demonstrates how to iterate over collections using the `loop` construct:
```yaml
- step: city_loop
  desc: "Iterate over cities"
  loop:
    in: "{{ workload.cities }}"
    iterator: city
    filter: "{{}}"
```

### 2. Nested Loops
The playbook shows how to implement nested loops for hierarchical data processing:
```yaml
- step: district_loop
  desc: "Iterate over districts of the city"
  loop:
    in: "{{ districts }}"
    iterator: district
    filter: "{{ district.name != 'Mordor' }}"
```

### 3. Loop Filtering
The district loop demonstrates filtering items in a loop using a condition:
```yaml
filter: "{{ district.name != 'Mordor' }}"
```

### 4. Loop Result Collection
The playbook shows how to collect results from loop iterations:
```yaml
- step: end_district_loop
  desc: "End of the district loop"
  end_loop: district_loop
  result:
    district_loop_output: "{{ output }}"
```

### 5. Database Integration
The playbook demonstrates integration with PostgreSQL for data storage:
```yaml
- name: store_aggregate_result_task_postgres_pipeline
  type: python
  with:
    summary: "{{ summary }}"
  code: |
    # Code that stores data in PostgreSQL
```