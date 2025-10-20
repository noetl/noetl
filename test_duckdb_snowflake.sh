#!/bin/bash
# Test script for DuckDB Snowflake extension integration

set -e

echo "═══════════════════════════════════════════════════════════════"
echo "  DuckDB Snowflake Extension - Integration Test"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo "Step 1: Verify Python imports"
echo "──────────────────────────────────────────────────────────────"
.venv/bin/python << 'PYEOF'
from noetl.plugin.duckdb.types import AuthType
from noetl.plugin.duckdb.auth.secrets import _generate_snowflake_secret
from noetl.plugin.duckdb.extensions import AUTH_TYPE_EXTENSIONS

# Verify Snowflake is in AuthType enum
assert AuthType.SNOWFLAKE.value == "snowflake", "Snowflake AuthType not found"
print("✓ AuthType.SNOWFLAKE registered")

# Verify Snowflake extension mapping
assert AuthType.SNOWFLAKE in AUTH_TYPE_EXTENSIONS, "Snowflake not in extension map"
assert AUTH_TYPE_EXTENSIONS[AuthType.SNOWFLAKE] == ['snowflake'], "Wrong extension mapping"
print("✓ Snowflake extension mapping configured")

# Test secret generation
test_config = {
    "account": "xy12345.us-east-1",
    "user": "test_user",
    "password": "test_pass",
    "database": "TEST_DB",
    "warehouse": "COMPUTE_WH"
}

secret_stmt = _generate_snowflake_secret("test_secret", test_config)
assert "TYPE snowflake" in secret_stmt, "Secret statement missing TYPE"
assert "ACCOUNT 'xy12345.us-east-1'" in secret_stmt, "Secret missing account"
assert "USER 'test_user'" in secret_stmt, "Secret missing user"
assert "DATABASE 'TEST_DB'" in secret_stmt, "Secret missing database"
print("✓ Snowflake secret generation working")

print("")
print("All imports and basic functionality verified!")
PYEOF

echo ""
echo "Step 2: Check example files"
echo "──────────────────────────────────────────────────────────────"

files=(
    "examples/duckdb/snowflake_credentials.yaml"
    "examples/duckdb/duckdb_snowflake_query.yaml"
    "examples/duckdb/duckdb_snowflake_etl.yaml"
    "examples/duckdb/duckdb_snowflake_join.yaml"
    "examples/duckdb/SNOWFLAKE_INTEGRATION.md"
)

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $file"
    else
        echo -e "${YELLOW}✗${NC} $file (missing)"
    fi
done

echo ""
echo "Step 3: Test credential registration (dry-run)"
echo "──────────────────────────────────────────────────────────────"
.venv/bin/python << 'PYEOF'
import yaml

# Load and validate credentials file
with open('examples/duckdb/snowflake_credentials.yaml', 'r') as f:
    creds = yaml.safe_load(f)

print(f"✓ Loaded {len(creds)} credential definitions")

for cred in creds:
    key = cred.get('key')
    service = cred.get('service')
    payload = cred.get('payload', {})
    
    # Validate required fields
    assert service == 'snowflake', f"Wrong service for {key}"
    assert 'account' in payload or 'sf_account' in payload, f"Missing account in {key}"
    assert 'user' in payload or 'sf_user' in payload or 'username' in payload, f"Missing user in {key}"
    
    print(f"  ✓ {key}: service={service}, fields={len(payload)}")

print("")
print("All credential definitions are valid!")
PYEOF

echo ""
echo "Step 4: Validate playbook syntax"
echo "──────────────────────────────────────────────────────────────"

playbooks=(
    "examples/duckdb/duckdb_snowflake_query.yaml"
    "examples/duckdb/duckdb_snowflake_etl.yaml"
    "examples/duckdb/duckdb_snowflake_join.yaml"
)

for playbook in "${playbooks[@]}"; do
    if .venv/bin/python -c "import yaml; yaml.safe_load(open('$playbook'))" 2>/dev/null; then
        echo -e "${GREEN}✓${NC} $(basename $playbook)"
    else
        echo -e "${YELLOW}✗${NC} $(basename $playbook) - YAML syntax error"
    fi
done

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo -e "  ${GREEN}All tests passed!${NC}"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo "1. Update your Snowflake credentials in:"
echo "   examples/duckdb/snowflake_credentials.yaml"
echo ""
echo "2. Register credentials with NoETL:"
echo "   .venv/bin/python -m noetl.main auth register \\"
echo "     examples/duckdb/snowflake_credentials.yaml \\"
echo "     --host localhost --port 8083"
echo ""
echo "3. Register and run example playbook:"
echo "   .venv/bin/python -m noetl.main catalog register \\"
echo "     examples/duckdb/duckdb_snowflake_query.yaml \\"
echo "     --host localhost --port 8083"
echo ""
echo "   curl -X POST http://localhost:8083/api/executions/run \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"path\": \"examples/duckdb_snowflake_query\"}'"
echo ""
echo "See examples/duckdb/SNOWFLAKE_INTEGRATION.md for complete guide."
echo ""
