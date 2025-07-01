# Load Dict Test Playbook Documentation

## Overview
The `load_dict_test.yaml` playbook is a NoETL DSL playbook designed for testing DuckDB implementation with PostgreSQL integration. It demonstrates basic DuckDB operations including table creation, data manipulation, and cross-database operations using the PostgreSQL extension.

## Playbook Details
- **API Version**: noetl.io/v1
- **Kind**: Playbook
- **Name**: load_dict_test
- **Path**: workflows/data/load_dict_test

## Purpose
This playbook serves as a test case for:
- DuckDB PostgreSQL extension functionality
- Basic SQL operations within DuckDB
- Cross-database data transfer (DuckDB to PostgreSQL)
- Table creation and data insertion workflows

## Workload Configuration

### Environment Variables
The playbook uses the following environment variables with default fallbacks:

| Variable | Default | Description |
|----------|---------|-------------|
| `POSTGRES_HOST` | localhost | PostgreSQL server host |
| `POSTGRES_PORT` | 5434 | PostgreSQL server port |
| `POSTGRES_USER` | noetl | PostgreSQL username |
| `POSTGRES_PASSWORD` | noetl | PostgreSQL password |
| `POSTGRES_DB` | noetl | PostgreSQL database name |

### Additional Configuration
- **Job ID**: Generated using `{{ job.uuid }}`
- **Base File Path**: `/opt/noetl/data/test`
- **Bucket**: `test-bucket`

## Workflow Steps

### 1. Start Step
- **Description**: Start DuckDB Test Workflow
- **Action**: Initiates the workflow and proceeds to the test_duckdb step

### 2. Test DuckDB Step
- **Description**: Test DuckDB implementation
- **Action**: Calls the `duckdb_test_task` workbook
- **Type**: workbook

### 3. End Step
- **Description**: End of workflow
- **Action**: Terminates the workflow

## DuckDB Test Task Operations

The main workbook (`duckdb_test_task`) performs the following operations:

### 1. Extension Management
```sql
INSTALL postgres;
LOAD postgres;
```
- Installs and loads the PostgreSQL extension for DuckDB

### 2. Database Connection
```sql
ATTACH 'dbname={{ workload.pg_db }} user={{ workload.pg_user }} password={{ workload.pg_password }} host={{ workload.pg_host }} port={{ workload.pg_port }}' AS postgres_db (TYPE postgres);
```
- Establishes connection to PostgreSQL database using workload configuration

### 3. Test Data Creation
```sql
CREATE TABLE IF NOT EXISTS test_table AS 
SELECT 1 AS id, 'test1' AS name
UNION ALL
SELECT 2 AS id, 'test2' AS name
UNION ALL
SELECT 3 AS id, 'test3' AS name;
```
- Creates a test table with sample data in DuckDB

### 4. Data Querying
```sql
SELECT * FROM test_table;
```
- Queries the test table to verify data creation

### 5. PostgreSQL Table Creation
```sql
CREATE TABLE IF NOT EXISTS postgres_db.test_table (
    id INTEGER,
    name TEXT
);
```
- Creates a corresponding table in the attached PostgreSQL database

### 6. Data Transfer
```sql
INSERT INTO postgres_db.test_table
SELECT * FROM test_table;
```
- Transfers data from DuckDB to PostgreSQL

### 7. Cross-Database Query
```sql
SELECT * FROM postgres_db.test_table;
```
- Queries data from PostgreSQL to verify successful transfer

### 8. Cleanup
```sql
DROP TABLE IF EXISTS test_table;
```
- Removes the temporary test table from DuckDB

## Workbook Parameters

The workbook includes the following parameters:
- **table**: test_table
- **file**: `{{ workload.baseFilePath }}/test.csv`
- **header**: false
- **bucket**: `{{ workload.bucket }}`

## Prerequisites

### Environment Setup
1. **PostgreSQL Server**: Ensure PostgreSQL is running and accessible
2. **DuckDB**: The system must have DuckDB with PostgreSQL extension support
3. **Network Access**: Connectivity between DuckDB and PostgreSQL instances

### Required Extensions
- DuckDB PostgreSQL extension

## Usage

### Running the Playbook
```bash
noetl playbook --register playbook/load_dict_test.yaml --port 8080
noetl playbook --execute --path "workflows/data/load_dict_test"
```

### Environment Variables Setup
Before running, ensure the following environment variables are set (or use defaults):
```bash
export POSTGRES_HOST=localhost
export POSTGRES_PORT=5434
export POSTGRES_USER=noetl
export POSTGRES_PASSWORD=noetl
export POSTGRES_DB=noetl
```

## Expected Outcomes

### Successful Execution
1. DuckDB PostgreSQL extension loads successfully
2. Connection to PostgreSQL database is established
3. Test table is created in DuckDB with 3 rows of sample data
4. Data is successfully transferred to PostgreSQL
5. Cross-database queries work correctly
6. Cleanup operations complete without errors

### Verification
After execution, you should see:
- Test data in both DuckDB (temporarily) and PostgreSQL
- Successful query results showing id and name columns
- Clean termination with no remaining temporary tables in DuckDB

## Troubleshooting

### Common Issues
1. **Connection Errors**: Verify PostgreSQL credentials and network connectivity
2. **Extension Issues**: Ensure DuckDB PostgreSQL extension is properly installed
3. **Permission Errors**: Check database user permissions for table creation and data insertion

### Error Messages
- **"Extension not found"**: Install DuckDB PostgreSQL extension
- **"Connection refused"**: Check PostgreSQL server status and connection parameters
- **"Permission denied"**: Verify database user has necessary privileges

## Related Files
- Base playbook: `playbook/load_dict_test.yaml`
- Similar examples: `playbook/postgres_test.yaml`
- Environment setup: `docs/environment_setup.md`
