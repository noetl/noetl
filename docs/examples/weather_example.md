# Weather Playbook Documentation

## Overview
The `weather.yaml` playbook demonstrates a simple weather data workflow that fetches weather data for a city, checks if the temperature exceeds a threshold, and reports whether it's warm or cold.

## Playbook Details
- **API Version**: noetl.io/v1
- **Kind**: Playbook
- **Name**: weather
- **Path**: workflows/examples/weather
- **Description**: Simple weather data workflow

## Purpose
This playbook demonstrates:
- Fetching weather data from an external API
- Conditional workflow branching based on data evaluation
- Using Python tasks for data processing and reporting
- Template variable usage and context passing between steps

## Workload Configuration

### Environment Variables
The playbook uses the following environment variables with default fallbacks:

| Variable | Default | Description |
|----------|---------|-------------|
| `job.uuid` | Generated UUID | Unique job identifier |

### Additional Configuration
- **State**: ready (controls workflow execution)
- **Cities**: List containing New York with coordinates
- **Temperature Threshold**: 20°C
- **Base URL**: https://api.open-meteo.com/v1

## Workflow Steps

### 1. Start Step
- **Description**: Start weather workflow
- **Condition**: Checks if workload.state is "ready"
- **Next**: fetch_weather (if ready) or end (if not ready)

### 2. Fetch Weather Step
- **Description**: Fetch weather data for the city
- **Type**: workbook
- **Workbook**: fetch_weather
- **Parameters**:
  - city: First city from the cities list
  - base_url: API base URL
  - threshold: Temperature threshold
- **Next**: Based on temperature evaluation:
  - report_warm (if temperature > threshold)
  - report_cold (if temperature ≤ threshold)

### 3. Report Warm Step
- **Description**: Report warm weather
- **Type**: python
- **Parameters**:
  - city: City object
  - temperature: Maximum temperature
- **Next**: end

### 4. Report Cold Step
- **Description**: Report cold weather
- **Type**: python
- **Parameters**:
  - city: City object
  - temperature: Maximum temperature
- **Next**: end

### 5. End Step
- **Description**: End of workflow

## Workbook Tasks

### Fetch Weather Task (`fetch_weather`)

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
     "alert": true,
     "threshold": 20
   }
   ```

## Running the Playbook

### Direct Execution
```bash
noetl agent -f playbook/weather.yaml
```

### Register and Execute from Catalog
```bash
# Register in the catalog
noetl playbook --register playbook/weather.yaml

# Execute from the catalog
noetl playbook --execute --path "workflows/examples/weather"
```

### Execute with Custom Parameters
```bash
noetl playbook --execute --path "workflows/examples/weather" --payload '{
  "cities": [
    {
      "name": "London",
      "lat": 51.51,
      "lon": -0.13
    }
  ],
  "temperature_threshold": 15
}'
```

## Example Output
When the temperature exceeds the threshold:
```
It's warm in New York (25.5°C)
```

When the temperature is below the threshold:
```
It's cold in New York (15.2°C)
```