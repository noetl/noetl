# How to Run the Postgres Test Playbook

This guide explains how to run the `postgres_test.yaml` playbook, which demonstrates PostgreSQL task execution, JSONB data handling, and advanced SQL operations using NoETL's native PostgreSQL integration.

## Workflow Overview

This playbook demonstrates PostgreSQL-specific functionality:
1. Creates PostgreSQL tables with advanced data types (JSONB)
2. Defines custom PostgreSQL functions
3. Inserts data with complex JSON structures
4. Performs advanced queries with JSONB operations
5. Updates data using JSONB manipulation functions

## Workflow Execution Diagram

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                          POSTGRES TEST WORKFLOW EXECUTION                        │
└─────────────────────────────────────────────────────────────────────────────────┘

┌─────────────┐    ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   START     │───▶│ Setup Tables     │───▶│ Insert Data     │───▶│ Query Data      │
│             │    │                  │    │                 │    │                 │
└─────────────┘    └──────────────────┘    └─────────────────┘    └─────────────────┘
                             │                        │                        │
                             ▼                        ▼                        ▼
                   ┌──────────────────┐    ┌─────────────────┐    ┌─────────────────┐
                   │ • DROP/CREATE    │    │ • Insert test   │    │ • Select all    │
                   │   tables         │    │   user data     │    │   users         │
                   │ • Define JSONB   │    │ • Insert JSONB  │    │ • Filter by     │
                   │   schema         │    │   metadata      │    │   active status │
                   │ • Create custom  │    │ • Add multiple  │    │ • Search JSON   │
                   │   functions      │    │   records       │    │   arrays        │
                   └──────────────────┘    └─────────────────┘    └─────────────────┘

┌─────────────────┐    ┌─────────────────┐
│ Update Data     │───▶│      END        │
│                 │    │   Workflow      │
└─────────────────┘    │   Complete      │
         │              └─────────────────┘
         ▼              
┌─────────────────┐    
│ • Query ages    │    
│ • Update JSONB  │    
│   fields        │    
│ • Verify        │    
│   changes       │    
└─────────────────┘    
```

## System Connections and Data Flows

### 1. Database Connection Flow
```
NoETL Workflow ──→ PostgreSQL Database
├─ Host: localhost:5434 (default)        ├─ Direct Connection
├─ Database: noetl                       ├─ Native postgres task type
├─ User: noetl (default)                 ├─ No intermediate processing
├─ Password: noetl (default)             └─ SQL execution engine
└─ Authentication: Direct credentials
```

### 2. Data Operations Flow
```
PostgreSQL Database Operations
├─ DDL Operations (CREATE, DROP)
│   ├─ Table creation with JSONB columns
│   ├─ Function definitions (PL/pgSQL)
│   └─ Schema management
├─ DML Operations (INSERT, UPDATE, SELECT)
│   ├─ JSONB data insertion
│   ├─ Complex JSON queries
│   └─ JSONB field updates
└─ Advanced Features
    ├─ JSONB operators (->>, ->, ?)
    ├─ JSONB functions (jsonb_set)
    └─ Custom function calls
```

### 3. Data Structure Flow
```
Test Data Structure
├─ User Table Schema
│   ├─ id: SERIAL PRIMARY KEY
│   ├─ name: VARCHAR(100)
│   ├─ email: VARCHAR(100) UNIQUE
│   ├─ metadata: JSONB
│   └─ created_at: TIMESTAMP
└─ JSONB Metadata Structure
    ├─ age: INTEGER
    ├─ active: BOOLEAN
    └─ tags: TEXT ARRAY
```

## Detailed Workflow Steps

### Phase 1: Table Setup
1. **Setup Tables**:
   - Drops existing `postgres_test_users` table if it exists
   - Creates new table with JSONB column for metadata
   - Defines custom PL/pgSQL function `get_json_field()`
   - Sets up proper indexes and constraints

### Phase 2: Data Insertion
2. **Insert Data**:
   - Inserts test user data with complex JSONB metadata
   - Demonstrates template variable usage with `{{ workload.test_data }}`
   - Adds multiple records with different JSONB structures
   - Shows JSONB casting from text to JSONB type

### Phase 3: Data Querying
3. **Query Data**:
   - **Query 1**: Selects all users with formatted timestamps
   - **Query 2**: Filters users by JSONB field (`active = true`)
   - **Query 3**: Searches for users with specific tags in JSONB arrays

### Phase 4: Data Updates
4. **Update Data**:
   - Queries specific JSONB fields (extracts age)
   - Updates JSONB fields using `jsonb_set()` function
   - Verifies changes by querying updated values

## Sample Data Structure

### Test User Data (from workload)
```json
{
  "name": "Test User",
  "email": "test@example.com",
  "metadata": {
    "age": 30,
    "active": true,
    "tags": ["test", "example", "jsonb"]
  }
}
```

### Additional Test Data
```json
{
  "name": "Another User",
  "email": "another@example.com",
  "metadata": {
    "age": 25,
    "active": false,
    "tags": ["another", "test"]
  }
}
```

## Key SQL Operations Demonstrated

### 1. Table Creation with JSONB
```sql
CREATE TABLE postgres_test_users (
  id SERIAL PRIMARY KEY,
  name VARCHAR(100) NOT NULL,
  email VARCHAR(100) UNIQUE NOT NULL,
  metadata JSONB,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 2. Custom Function Definition
```sql
CREATE OR REPLACE FUNCTION get_json_field(data JSONB, field TEXT)
RETURNS TEXT AS $$
BEGIN
  RETURN data->>field;
END
$$ LANGUAGE plpgsql;
```

### 3. JSONB Data Insertion
```sql
INSERT INTO postgres_test_users (name, email, metadata)
VALUES (
  'Test User',
  'test@example.com',
  '{"age": 30, "active": true, "tags": ["test", "example"]}'::JSONB
);
```

### 4. JSONB Query Operations
```sql
-- Filter by JSONB field
SELECT * FROM postgres_test_users 
WHERE metadata->>'active' = 'true';

-- Search JSONB arrays
SELECT * FROM postgres_test_users 
WHERE metadata->'tags' ? 'test';

-- Extract JSONB values
SELECT id, name, metadata->>'age' as age 
FROM postgres_test_users;
```

### 5. JSONB Update Operations
```sql
-- Update JSONB field
UPDATE postgres_test_users 
SET metadata = jsonb_set(metadata, '{active}', 'false'::jsonb) 
WHERE id = 1;
```

## Prerequisites

### Environment Setup
```bash
# Required environment variables
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="5434"
export POSTGRES_USER="noetl"
export POSTGRES_PASSWORD="noetl"
export POSTGRES_DB="noetl"
```

### Required Infrastructure
1. **PostgreSQL Database** (version 12+ recommended for full JSONB support)
2. **NoETL Server** running with PostgreSQL connectivity
3. **Database Permissions** for creating tables, functions, and data manipulation

## Running the Playbook

### 1. Register the Playbook
```bash
noetl playbook --register playbook/postgres_test.yaml --port 8080
```

### 2. Execute the Workflow
```bash
noetl playbook --execute --path "workflows/examples/postgres_test"
```

### 3. Alternative Execution with Custom Parameters
```bash
noetl playbook --execute --path "workflows/examples/postgres_test" --port 8080 --payload '{
  "POSTGRES_HOST": "localhost",
  "POSTGRES_PORT": "5434",
  "POSTGRES_USER": "noetl",
  "POSTGRES_PASSWORD": "noetl",
  "POSTGRES_DB": "noetl"
}'
```

## Key Features Demonstrated

### PostgreSQL-Specific Features
- **Native PostgreSQL Integration**: Direct SQL execution without intermediate processing
- **JSONB Support**: Advanced JSON operations and querying
- **PL/pgSQL Functions**: Custom function definition and usage
- **Data Types**: SERIAL, VARCHAR, JSONB, TIMESTAMP handling
- **Constraints**: PRIMARY KEY, UNIQUE constraints

### NoETL Framework Features
- **Template Variables**: Dynamic data injection using `{{ workload.variable }}`
- **JSON Templating**: Complex object handling with `| tojson` filter
- **Multi-step Workflows**: Sequential task execution with dependencies
- **Workbook Task Execution**: PostgreSQL tasks defined in workbook section and referenced in workflow steps
- **Error Handling**: Automatic rollback and error reporting

### Advanced SQL Operations
- **JSONB Operators**:
  - `->`: Get JSON object field
  - `->>`: Get JSON object field as text
  - `?`: Check if key/element exists
- **JSONB Functions**:
  - `jsonb_set()`: Update JSONB fields
  - `::JSONB`: Type casting
- **Complex Queries**: Multi-condition filtering and JSON array searches

## Expected Output

### Step 1: Table Setup
- Creates `postgres_test_users` table
- Defines `get_json_field()` function
- Returns success confirmation

### Step 2: Data Insertion
- Inserts 2 user records
- Returns insertion confirmation with row counts

### Step 3: Data Querying
- **Query 1**: Returns all users with full metadata
- **Query 2**: Returns only active users (`active: true`)
- **Query 3**: Returns users with "test" tag

### Step 4: Data Updates
- Shows user ages extracted from JSONB
- Updates user ID 1's active status to false
- Confirms the update by showing new active status

## Troubleshooting

### Common Issues
1. **PostgreSQL Connection**: Verify database is running and accessible
2. **Permission Errors**: Ensure user has CREATE, INSERT, UPDATE, SELECT permissions
3. **JSONB Syntax**: Check JSON formatting and JSONB casting
4. **Function Creation**: Verify PL/pgSQL language is enabled

### Debug Steps
1. Check NoETL server logs for PostgreSQL connection details
2. Test database connectivity manually using `psql`
3. Verify table creation by checking `\dt` in psql
4. Validate JSONB data using PostgreSQL JSONB validation functions

### Validation Queries
```sql
-- Check table structure
\d postgres_test_users

-- Verify data insertion
SELECT COUNT(*) FROM postgres_test_users;

-- Check JSONB structure
SELECT metadata FROM postgres_test_users LIMIT 1;

-- Validate custom function
SELECT get_json_field('{"test": "value"}'::JSONB, 'test');
```

## Use Cases

This playbook is ideal for:
- **Learning PostgreSQL JSONB operations**
- **Testing NoETL PostgreSQL integration**
- **Prototyping JSON-based data models**
- **Validating complex SQL operations**
- **Understanding NoETL templating system**
