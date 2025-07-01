# How to Run the Multi-Playbook Example

This guide explains how to run the `multi_playbook_example.yaml` playbook, which demonstrates NoETL's advanced orchestration capabilities by calling multiple child playbooks sequentially, passing data between them, and aggregating results.

## Workflow Overview

This playbook demonstrates a complex orchestration pattern that:
1. **Calls multiple child playbooks** in sequence with data dependencies
2. **Passes results between playbooks** using NoETL's inter-playbook communication
3. **Aggregates and stores results** from all executed playbooks
4. **Demonstrates real-world integration scenarios** combining secrets, APIs, and data processing

## Workflow Execution Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                       MULTI-PLAYBOOK ORCHESTRATION WORKFLOW                      │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   START     │───▶│ Run Secrets      │───▶│ Run Weather     │───▶│ Run Load Dict   │
│             │    │ Test Playbook    │    │ Example         │    │ Test Playbook   │
└─────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
                             │                        │                        │
                             ▼                        ▼                        ▼
                   ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
                   │ • Retrieve       │    │ • Use secret    │    │ • Process       │
                   │   Google secret  │    │   from step 1   │    │   weather data  │
                   │ • Return secret  │    │ • Fetch weather │    │   from step 2   │
                   │   metadata       │    │ • London data   │    │ • Load to files │
                   │                  │    │ • Return JSON   │    │ • Return paths  │
                   └──────────────────┘    └─────────────────┘    └─────────────────┘

┌─────────────────┐    ┌─────────────────┐
│ Store Results   │───▶│      END        │
│ & Aggregate     │    │   Workflow      │
└─────────────────┘    │   Complete      │
         │              └─────────────────┘
         ▼              
┌─────────────────┐    
│ • Collect all   │    
│   playbook      │    
│   results       │    
│ • Store in      │    
│   DuckDB        │    
│ • Store in      │    
│   PostgreSQL    │    
└─────────────────┘    
```

## System Connections and Data Flows

### 1. Inter-Playbook Communication Flow
```
Parent Playbook ──→ Child Playbook 1 ──→ Child Playbook 2 ──→ Child Playbook 3
├─ Pass input params     ├─ Return results     ├─ Receive data      ├─ Process data
├─ Execute child         ├─ Pass to next       ├─ Execute logic     ├─ Return results
└─ Receive outputs       └─ Continue chain     └─ Pass to next      └─ Final aggregation
```

### 2. Data Dependency Chain
```
secrets_test → weather_example → load_dict_test → store_results
├─ Google Secret      ├─ Weather API data    ├─ File processing   ├─ All results
├─ Secret metadata    ├─ London temperature  ├─ Data validation   ├─ JSON aggregation
└─ Auth status        └─ JSON response       └─ Storage paths     └─ Database storage
```

### 3. Storage and Database Flow
```
Results Aggregation
├─ DuckDB (In-Memory Processing)
│   ├─ Create playbook_results table
│   ├─ Insert JSON data from all playbooks
│   └─ Timestamp execution
└─ PostgreSQL (Persistent Storage)
    ├─ Create playbook_results table
    ├─ Store aggregated results
    └─ Maintain execution history
```

## Detailed Workflow Steps

### Phase 1: Secret Management Playbook
**Step**: `run_secrets_test`
- **Calls**: `workflows/examples/secrets_test`
- **Purpose**: Validates Google Secret Manager integration
- **Input Parameters**:
  - `secret_name`: Google Secret name to retrieve
  - `GOOGLE_CLOUD_PROJECT`: GCP project ID
- **Returns**: Secret metadata and retrieval status
- **Data Passed Forward**: `secret_result` → weather_example

### Phase 2: Weather API Integration Playbook  
**Step**: `run_weather_example`
- **Calls**: `workflows/examples/weather_example`
- **Purpose**: Fetches weather data from external API
- **Input Parameters**:
  - `cities`: Array of city data (London with coordinates)
  - `base_url`: Open-Meteo API endpoint
  - `temperature_threshold`: Temperature filtering threshold (26°C)
  - `secret_from_previous`: Results from secrets_test
- **Returns**: Weather API response data for London
- **Data Passed Forward**: `weather_result` → load_dict_test

### Phase 3: Data Processing Playbook
**Step**: `run_load_dict_test`
- **Calls**: `workflows/data/load_dict_test`
- **Purpose**: Processes and validates weather data
- **Input Parameters**:
  - `baseFilePath`: Base path for data files
  - `bucket`: Storage bucket configuration
  - `pg_*`: PostgreSQL connection parameters
  - `weather_data`: Weather results from previous step
- **Returns**: File processing results and storage paths
- **Data Passed Forward**: `load_dict_result` → store_results

### Phase 4: Results Aggregation
**Step**: `store_results`
- **Type**: DuckDB workbook task
- **Purpose**: Aggregates all playbook results into databases
- **Operations**:
  - Creates tables in both DuckDB and PostgreSQL
  - Stores JSON results from all three child playbooks
  - Maintains execution metadata and timestamps

## Child Playbook Integration Patterns

### 1. **Sequential Dependency Pattern**
```yaml
- step: run_playbook_a
  call:
    type: playbook
    path: workflows/examples/playbook_a
  next:
    - step: run_playbook_b
      with:
        data_from_a: "{{ run_playbook_a }}"
```

### 2. **Data Passing Pattern**
```yaml
- step: run_playbook_b
  call:
    type: playbook
    path: workflows/examples/playbook_b
    with:
      input_data: "{{ previous_step_result }}"
      additional_param: "{{ workload.some_value }}"
```

### 3. **Result Aggregation Pattern**
```yaml
- step: aggregate_results
  call:
    type: workbook
    name: aggregation_task
    with:
      result_1: "{{ playbook_1_result }}"
      result_2: "{{ playbook_2_result }}"
      result_3: "{{ playbook_3_result }}"
```

## Use Cases for Multi-Playbook Orchestration

### 1. **Complex ETL Pipelines**
- **Scenario**: Multi-stage data processing with validation steps
- **Pattern**: Extract → Transform → Validate → Load → Audit
- **Benefits**: Modular components, reusable transforms, independent testing

### 2. **API Integration Workflows**
- **Scenario**: Authentication → Data Fetch → Processing → Storage
- **Pattern**: Get OAuth Token → Call APIs → Transform Data → Store Results
- **Benefits**: Secure credential handling, API rate limiting, error isolation

### 3. **Multi-Source Data Aggregation**
- **Scenario**: Combining data from multiple external sources
- **Pattern**: Source A → Source B → Source C → Merge → Validate → Store
- **Benefits**: Parallel processing, source isolation, unified output

### 4. **Business Process Automation**
- **Scenario**: End-to-end business workflow automation
- **Pattern**: Trigger → Validate → Process → Notify → Archive
- **Benefits**: Process visibility, step-by-step validation, audit trails

### 5. **Testing and Validation Workflows**
- **Scenario**: Comprehensive system testing with multiple components
- **Pattern**: Setup → Test A → Test B → Test C → Cleanup → Report
- **Benefits**: Isolated test execution, result aggregation, comprehensive reporting

## Data Structure Examples

### Input Parameters Structure
```json
{
  "secret_name": "projects/my-project/secrets/postgres-password",
  "GOOGLE_CLOUD_PROJECT": "my-gcp-project",
  "cities": [
    {
      "name": "London",
      "lat": 51.51,
      "lon": -0.13
    }
  ],
  "temperature_threshold": 26
}
```

### Inter-Playbook Data Flow
```json
{
  "secrets_test_result": {
    "secret_retrieved": true,
    "secret_metadata": {...},
    "execution_time": "2025-06-30T19:00:00Z"
  },
  "weather_example_result": {
    "london_temperature": 22.5,
    "weather_data": {...},
    "api_response_time": 150
  },
  "load_dict_test_result": {
    "files_processed": 3,
    "validation_status": "passed",
    "storage_paths": [...]
  }
}
```

### Final Aggregated Results
```json
{
  "execution_id": "uuid-12345",
  "timestamp": "2025-06-30T19:05:00Z",
  "playbook_results": {
    "secrets_result": {...},
    "weather_result": {...},
    "load_dict_result": {...}
  },
  "execution_summary": {
    "total_playbooks": 3,
    "total_execution_time": "2m 15s",
    "success_rate": "100%"
  }
}
```

## Prerequisites

### Environment Setup
```bash
# Required environment variables
export GOOGLE_CLOUD_PROJECT="google-project-id"
export GOOGLE_SECRET_POSTGRES_PASSWORD="projects/google-project/secrets/postgres-password"
export ENVIRONMENT="dev"
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="5434"
export POSTGRES_USER="noetl"
export POSTGRES_PASSWORD="noetl"
export POSTGRES_DB="noetl"
```

### Required Child Playbooks
1. **secrets_test.yaml** - Must exist at `workflows/examples/secrets_test`
2. **weather_example.yaml** - Must exist at `workflows/examples/weather_example`
3. **load_dict_test.yaml** - Must exist at `workflows/data/load_dict_test`

### Required Infrastructure
1. **Google Secret Manager** with accessible secrets
2. **PostgreSQL Database** for persistent storage
3. **Internet Access** for weather API calls
4. **NoETL Server** with all child playbooks registered

## Running the Playbook

### 1. Register All Required Playbooks
```bash
# Register child playbooks first
noetl playbook --register playbook/secrets_test.yaml --port 8080
noetl playbook --register playbook/weather_example.yaml --port 8080
noetl playbook --register playbook/load_dict_test.yaml --port 8080

# Register the orchestrator playbook
noetl playbook --register playbook/multi_playbook_example.yaml --port 8080
```

### 2. Execute the Orchestration Workflow
```bash
noetl playbook --execute --path "workflows/examples/multi_playbook_example" --port 8080 --payload '{
  "GOOGLE_CLOUD_PROJECT": "my-gcp-project",
  "secret_name": "projects/my-project/secrets/postgres-dev-password",
  "ENVIRONMENT": "dev",
  "POSTGRES_HOST": "localhost",
  "POSTGRES_PORT": "5434",
  "POSTGRES_USER": "noetl",
  "POSTGRES_PASSWORD": "noetl",
  "POSTGRES_DB": "noetl"
}'
```

### 3. Monitor Multi-Playbook Execution
The orchestrator will:
- Execute each child playbook in sequence
- Pass results between playbooks automatically
- Aggregate all results at the end
- Store comprehensive execution logs

## Key Features

### NoETL Orchestration Features
- **Inter-Playbook Communication**: Seamless data passing between playbooks
- **Sequential Execution**: Controlled workflow dependency management
- **Result Aggregation**: Centralized collection of distributed results
- **Error Handling**: Comprehensive error propagation and handling
- **Template Variable Resolution**: Dynamic parameter passing and interpolation

### Advanced Workflow Patterns
- **Pipeline Orchestration**: Multi-stage data processing pipelines
- **Service Integration**: Multiple external service coordination
- **Data Dependency Management**: Complex data flow orchestration
- **Result Persistence**: Multi-database storage strategies
- **Execution Tracking**: Comprehensive audit trails and metadata

### Real-World Applications
- **Microservices Coordination**: Orchestrating multiple microservice calls
- **Data Pipeline Management**: Managing complex ETL/ELT workflows
- **API Integration**: Coordinating multiple API interactions
- **Business Process Automation**: End-to-end business workflow automation
- **Testing Orchestration**: Comprehensive multi-component testing

## Expected Output

### Execution Flow
1. **Secrets Test**: Validates Google Secret Manager access
2. **Weather Example**: Fetches London weather data using retrieved secrets
3. **Load Dict Test**: Processes weather data and validates storage
4. **Store Results**: Aggregates all results into databases

### Database Results
**DuckDB Table**: `playbook_results`
- Temporary in-memory storage for processing
- JSON columns for each playbook result
- Execution metadata and timestamps

**PostgreSQL Table**: `playbook_results`
- Persistent storage for long-term retention
- Complete execution history
- Queryable JSON data for analysis

## Troubleshooting

### Common Issues
1. **Child Playbook Not Found**: Ensure all child playbooks are registered
2. **Data Passing Errors**: Verify template variable syntax and data structure
3. **Authentication Failures**: Check Google Cloud credentials and secret access
4. **Database Connection Issues**: Validate PostgreSQL connectivity and permissions

### Debug Steps
1. **Check Child Playbook Status**: Verify all dependencies are registered and functional
2. **Validate Data Flow**: Check template variable resolution at each step
3. **Monitor Execution Logs**: Review NoETL server logs for detailed error information
4. **Test Individual Playbooks**: Execute child playbooks independently to isolate issues

### Validation Queries
```sql
-- Check aggregated results in Postgres
SELECT 
  execution_id,
  timestamp,
  secrets_result->>'secret_retrieved' as secret_status,
  weather_result->>'london_temperature' as temperature,
  load_dict_result->>'files_processed' as files_count
FROM playbook_results 
ORDER BY timestamp DESC;

-- Verify execution history
SELECT COUNT(*) as total_executions,
       MIN(timestamp) as first_execution,
       MAX(timestamp) as last_execution
FROM playbook_results;
```

## Best Practices for Multi-Playbook Design

### 1. **Modular Design**
- Keep child playbooks focused on single responsibilities
- Design for reusability across different orchestration scenarios
- Maintain clear input/output contracts

### 2. **Error Handling**
- Implement comprehensive error handling in child playbooks
- Design graceful failure modes for critical dependencies
- Provide meaningful error messages for troubleshooting

### 3. **Data Management**
- Use consistent data structures across playbooks
- Validate data at each handoff point
- Document expected input/output schemas

### 4. **Performance Optimization**
- Consider parallel execution where dependencies allow
- Optimize data passing to minimize payload sizes
- Implement appropriate timeouts for external calls

### 5. **Security Considerations**
- Minimize credential passing between playbooks
- Use secure secret management throughout the chain
- Implement appropriate access controls for each component
