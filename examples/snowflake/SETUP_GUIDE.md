# Snowflake Integration Setup Guide for NoETL

## Overview

The NoETL Snowflake plugin provides native integration with Snowflake Data Cloud, enabling you to:
- Execute SQL queries and DDL statements
- Work with Snowflake's semi-structured data (VARIANT, ARRAY, OBJECT)
- Manage warehouses, databases, and schemas
- Integrate Snowflake into data pipelines
- Use unified authentication system

## Prerequisites

1. **Snowflake Account**: You need an active Snowflake account
2. **Python Environment**: Python 3.12+ with NoETL installed
3. **Snowflake Connector**: Automatically installed with NoETL

## Snowflake Account Setup

### Step 1: Create or Access Snowflake Account

If you don't have a Snowflake account:
1. Go to https://signup.snowflake.com/
2. Sign up for a free trial (30 days, $400 credit)
3. Choose your cloud provider (AWS, Azure, or GCP)
4. Select your region
5. Note your **Account Identifier** (looks like `xy12345.us-east-1`)

### Step 2: Find Your Account Identifier

**Method 1: From Snowflake UI**
1. Log into Snowflake Web UI
2. Look at the URL: `https://<account_identifier>.snowflakecomputing.com/`
3. The account identifier is the first part before `.snowflakecomputing.com`

**Method 2: Using SQL**
```sql
SELECT CURRENT_ACCOUNT() as account_name,
       CURRENT_REGION() as region;
```

Your full account identifier format:
- **Legacy format**: `<account_name>.<region>` (e.g., `xy12345.us-east-1`)
- **New format**: `<org_name>-<account_name>` (e.g., `myorg-myaccount`)

### Step 3: Create Snowflake User for NoETL

It's recommended to create a dedicated user for NoETL:

```sql
-- Connect as ACCOUNTADMIN or user with CREATE USER privilege

-- Create role for NoETL
CREATE ROLE IF NOT EXISTS NOETL_ROLE;

-- Grant warehouse access
GRANT USAGE ON WAREHOUSE COMPUTE_WH TO ROLE NOETL_ROLE;
GRANT OPERATE ON WAREHOUSE COMPUTE_WH TO ROLE NOETL_ROLE;

-- Grant database and schema access
-- Option 1: Grant to existing database
GRANT USAGE ON DATABASE <YOUR_DATABASE> TO ROLE NOETL_ROLE;
GRANT USAGE ON ALL SCHEMAS IN DATABASE <YOUR_DATABASE> TO ROLE NOETL_ROLE;
GRANT CREATE SCHEMA ON DATABASE <YOUR_DATABASE> TO ROLE NOETL_ROLE;

-- Option 2: Create new database for testing
CREATE DATABASE IF NOT EXISTS NOETL_TEST;
GRANT ALL PRIVILEGES ON DATABASE NOETL_TEST TO ROLE NOETL_ROLE;
GRANT ALL PRIVILEGES ON ALL SCHEMAS IN DATABASE NOETL_TEST TO ROLE NOETL_ROLE;
GRANT ALL PRIVILEGES ON FUTURE SCHEMAS IN DATABASE NOETL_TEST TO ROLE NOETL_ROLE;

-- Create user
CREATE USER IF NOT EXISTS noetl_user
  PASSWORD = 'YOUR_SECURE_PASSWORD'
  DEFAULT_ROLE = NOETL_ROLE
  DEFAULT_WAREHOUSE = COMPUTE_WH
  DEFAULT_NAMESPACE = NOETL_TEST.PUBLIC
  MUST_CHANGE_PASSWORD = FALSE;

-- Grant role to user
GRANT ROLE NOETL_ROLE TO USER noetl_user;

-- Verify user creation
SHOW USERS LIKE 'noetl_user';
SHOW GRANTS TO USER noetl_user;
```

### Step 4: Create and Configure Warehouse

```sql
-- If using default COMPUTE_WH, ensure it's running
SHOW WAREHOUSES LIKE 'COMPUTE_WH';

-- Or create a dedicated warehouse for NoETL
CREATE WAREHOUSE IF NOT EXISTS NOETL_WH
  WAREHOUSE_SIZE = 'X-SMALL'
  AUTO_SUSPEND = 60
  AUTO_RESUME = TRUE
  INITIALLY_SUSPENDED = TRUE
  COMMENT = 'Warehouse for NoETL tasks';

-- Grant access
GRANT USAGE ON WAREHOUSE NOETL_WH TO ROLE NOETL_ROLE;
GRANT OPERATE ON WAREHOUSE NOETL_WH TO ROLE NOETL_ROLE;
```

### Step 5: Test Connection

Test your setup using SnowSQL or the Web UI:

```sql
-- Log in as noetl_user and run:
SELECT CURRENT_USER() as user,
       CURRENT_ROLE() as role,
       CURRENT_WAREHOUSE() as warehouse,
       CURRENT_DATABASE() as database,
       CURRENT_SCHEMA() as schema;

-- Test warehouse
USE WAREHOUSE COMPUTE_WH;
SELECT 'Connection successful!' as status;
```

## NoETL Configuration

### Step 1: Install Dependencies

```bash
# Install NoETL with Snowflake support
cd /Users/kadyapam/projects/noetl/noetl
task install-dev

# Or manually install snowflake connector
uv pip install snowflake-connector-python>=3.16.0
```

### Step 2: Configure Credentials

**Option A: Create credentials file**

1. Copy the template:
```bash
cp examples/snowflake/snowflake_credentials.yaml examples/snowflake/my_snowflake_creds.yaml
```

2. Edit with your credentials:
```yaml
apiVersion: noetl.io/v1
kind: Credential

credentials:
  - key: sf_test
    name: Snowflake Test Account
    type: snowflake
    data:
      account: "xy12345.us-east-1"  # Your account identifier
      user: "noetl_user"
      password: "YOUR_SECURE_PASSWORD"
      warehouse: "COMPUTE_WH"
      database: "NOETL_TEST"
      schema: "PUBLIC"
      role: "NOETL_ROLE"
```

3. Register credentials:
```bash
# Start NoETL server if not running
task noetl:local:start

# Register credentials
.venv/bin/python -m noetl.main auth register \
  examples/snowflake/my_snowflake_creds.yaml \
  --host localhost --port 8083
```

**Option B: Use environment variables**

```bash
# Set environment variables
export SNOWFLAKE_ACCOUNT="xy12345.us-east-1"
export SNOWFLAKE_USER="noetl_user"
export SNOWFLAKE_PASSWORD="YOUR_SECURE_PASSWORD"
export SNOWFLAKE_WAREHOUSE="COMPUTE_WH"
export SNOWFLAKE_DATABASE="NOETL_TEST"
export SNOWFLAKE_SCHEMA="PUBLIC"
export SNOWFLAKE_ROLE="NOETL_ROLE"

# Register env-based credentials
.venv/bin/python -m noetl.main auth register \
  examples/snowflake/snowflake_credentials.yaml \
  --host localhost --port 8083
```

### Step 3: Register Test Playbooks

```bash
# Register simple connection test
.venv/bin/python -m noetl.main catalog register \
  examples/snowflake/snowflake_simple.yaml \
  --host localhost --port 8083

# Register comprehensive test
.venv/bin/python -m noetl.main catalog register \
  examples/snowflake/snowflake_test.yaml \
  --host localhost --port 8083
```

### Step 4: Run Test Playbook

```bash
# Test simple connection
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{"path": "examples/snowflake_simple"}'

# Check execution status
curl -s http://localhost:8083/api/executions?path=examples/snowflake_simple \
  | python3 -m json.tool

# Run comprehensive test
curl -X POST http://localhost:8083/api/executions/run \
  -H "Content-Type: application/json" \
  -d '{"path": "examples/snowflake_test"}'
```

## Playbook Usage Examples

### Basic Query

```yaml
workflow:
  - step: query_snowflake
    type: snowflake
    auth:
      sf:
        type: snowflake
        key: sf_test
    command: |
      SELECT 
        CURRENT_USER() as user,
        CURRENT_DATABASE() as database,
        CURRENT_TIMESTAMP() as timestamp;
```

### With Parameters

```yaml
workload:
  user_id: 12345
  status: "active"

workflow:
  - step: query_with_params
    type: snowflake
    auth:
      sf:
        type: snowflake
        key: sf_test
    command: |
      SELECT * FROM users
      WHERE user_id = {{ workload.user_id }}
        AND status = '{{ workload.status }}';
```

### JSON/VARIANT Data

```yaml
workflow:
  - step: work_with_json
    type: snowflake
    auth:
      sf:
        type: snowflake
        key: sf_test
    command: |
      SELECT 
        id,
        metadata:name::STRING as name,
        metadata:tags as tags,
        ARRAY_SIZE(metadata:tags) as tag_count
      FROM my_table
      WHERE metadata:active = true;
```

### Multiple Statements

```yaml
workflow:
  - step: multi_statement
    type: snowflake
    auth:
      sf:
        type: snowflake
        key: sf_test
    command: |
      CREATE TEMP TABLE temp_data AS
      SELECT * FROM source_table;
      
      UPDATE temp_data
      SET status = 'processed'
      WHERE status IS NULL;
      
      SELECT COUNT(*) as record_count FROM temp_data;
```

## Connection Parameters

### Required Parameters
- `account`: Snowflake account identifier (e.g., `xy12345.us-east-1`)
- `user`: Snowflake username
- `password`: Snowflake password

### Optional Parameters
- `warehouse`: Warehouse to use (default: `COMPUTE_WH`)
- `database`: Default database (can be set per query)
- `schema`: Default schema (default: `PUBLIC`)
- `role`: Role to assume (default: user's default role)
- `authenticator`: Authentication method (default: `snowflake`)
  - `snowflake`: Username/password
  - `externalbrowser`: Browser-based SSO
  - `oauth`: OAuth token

## Troubleshooting

### Connection Errors

**Error**: `250001: Could not connect to Snowflake backend`
- **Solution**: Check account identifier format
- Verify: `https://<account>.snowflakecomputing.com/` is accessible
- Check firewall/network settings

**Error**: `Authentication failed`
- **Solution**: Verify username and password
- Check if user account is locked: `SHOW USERS LIKE '<username>'`
- Ensure role grants are correct

**Error**: `Object does not exist, or operation cannot be performed`
- **Solution**: Grant appropriate privileges
- Check database/schema access
- Verify warehouse is running

### Performance Issues

**Slow queries**:
- Check warehouse size: Increase if needed
- Monitor query history in Snowflake UI
- Use `EXPLAIN` to analyze query plans

**Warehouse auto-suspend**:
- Adjust `AUTO_SUSPEND` setting
- Use `AUTO_RESUME = TRUE` for automatic startup

### Common Issues

**Issue**: Warehouse suspended
```sql
-- Resume warehouse
ALTER WAREHOUSE COMPUTE_WH RESUME;
```

**Issue**: Need to check permissions
```sql
SHOW GRANTS TO ROLE NOETL_ROLE;
SHOW GRANTS TO USER noetl_user;
```

**Issue**: Query timeout
- Increase timeout in connection settings
- Check warehouse size
- Optimize query

## Security Best Practices

1. **Use separate accounts for dev/prod**
2. **Rotate passwords regularly**
3. **Use environment variables for credentials**
4. **Limit role privileges to minimum required**
5. **Enable multi-factor authentication (MFA)**
6. **Monitor query history for unusual activity**
7. **Use resource monitors to control costs**

## Cost Management

1. **Auto-suspend warehouses** when not in use
2. **Use smallest warehouse size** that meets performance needs
3. **Set up resource monitors** with spending limits
4. **Monitor credit usage** in Snowflake UI
5. **Use query result caching** when possible

## MCP Compatibility

The Snowflake plugin follows NoETL's Model Context Protocol (MCP) standards:

- ✅ Unified authentication system support
- ✅ Event logging for observability
- ✅ Standardized error handling
- ✅ Result serialization
- ✅ Template rendering with Jinja2
- ✅ Consistent API interface

## Resources

- **Snowflake Documentation**: https://docs.snowflake.com/
- **NoETL Documentation**: `docs/`
- **Connector Documentation**: https://docs.snowflake.com/en/user-guide/python-connector
- **Free Trial**: https://signup.snowflake.com/

## Support

For issues or questions:
1. Check NoETL logs: `tail -f logs/worker-debug.log`
2. Check Snowflake query history in Web UI
3. Review this documentation
4. Contact NoETL support team

---

**Quick Start Checklist**:
- [ ] Snowflake account created
- [ ] Account identifier noted
- [ ] NoETL user created with appropriate role
- [ ] Warehouse configured and accessible
- [ ] Credentials configured in NoETL
- [ ] Test playbook executed successfully
- [ ] Query results verified in Snowflake UI
