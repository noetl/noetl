#!/bin/bash
# Test script for Snowflake transfer functionality

set -e

echo "═══════════════════════════════════════════════════════════════"
echo "  Snowflake <-> PostgreSQL Transfer - Integration Test"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Colors
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

echo "Step 1: Verify Python imports"
echo "──────────────────────────────────────────────────────────────"
.venv/bin/python << 'PYEOF'
try:
    from noetl.plugin.snowflake import execute_snowflake_task, execute_snowflake_transfer_task
    from noetl.plugin.snowflake.transfer import transfer_snowflake_to_postgres, transfer_postgres_to_snowflake
    print("✓ All Snowflake plugin imports successful")
except ImportError as e:
    print(f"✗ Import error: {e}")
    exit(1)

# Verify transfer functions are callable
import inspect
assert callable(execute_snowflake_transfer_task), "execute_snowflake_transfer_task not callable"
assert callable(transfer_snowflake_to_postgres), "transfer_snowflake_to_postgres not callable"
assert callable(transfer_postgres_to_snowflake), "transfer_postgres_to_snowflake not callable"
print("✓ All transfer functions are callable")

# Check function signatures
sig = inspect.signature(execute_snowflake_transfer_task)
required_params = ['task_config', 'context', 'jinja_env', 'task_with']
for param in required_params:
    assert param in sig.parameters, f"Missing parameter: {param}"
print("✓ Function signatures validated")

print("")
print("All imports and basic functionality verified!")
PYEOF

echo ""
echo "Step 2: Check test files"
echo "──────────────────────────────────────────────────────────────"

files=(
    "tests/fixtures/credentials/sf_test.json"
    "tests/fixtures/credentials/sf_test.json.template"
    "tests/fixtures/playbooks/snowflake_transfer/snowflake_transfer.yaml"
    "tests/fixtures/playbooks/snowflake_transfer/README.md"
    "noetl/plugin/snowflake/transfer.py"
)

for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo -e "${GREEN}✓${NC} $file"
    else
        echo -e "${RED}✗${NC} $file (missing)"
    fi
done

echo ""
echo "Step 3: Validate playbook syntax"
echo "──────────────────────────────────────────────────────────────"

if .venv/bin/python -c "import yaml; yaml.safe_load(open('tests/fixtures/playbooks/snowflake_transfer/snowflake_transfer.yaml'))" 2>/dev/null; then
    echo -e "${GREEN}✓${NC} snowflake_transfer.yaml - Valid YAML syntax"
else
    echo -e "${RED}✗${NC} snowflake_transfer.yaml - YAML syntax error"
    exit 1
fi

echo ""
echo "Step 4: Validate playbook structure"
echo "──────────────────────────────────────────────────────────────"
.venv/bin/python << 'PYEOF'
import yaml

with open('tests/fixtures/playbooks/snowflake_transfer/snowflake_transfer.yaml', 'r') as f:
    playbook = yaml.safe_load(f)

# Check required fields
assert playbook.get('apiVersion') == 'noetl.io/v1', "Invalid apiVersion"
assert playbook.get('kind') == 'Playbook', "Invalid kind"
assert 'metadata' in playbook, "Missing metadata"
assert 'workflow' in playbook, "Missing workflow"

print(f"✓ Playbook name: {playbook['metadata']['name']}")
print(f"✓ Playbook path: {playbook['metadata']['path']}")

# Check workflow steps
workflow = playbook['workflow']
step_names = [step['step'] for step in workflow]
print(f"✓ Workflow has {len(workflow)} steps")

# Verify critical steps exist
critical_steps = ['start', 'setup_pg_table', 'setup_sf_table', 
                  'transfer_sf_to_pg', 'transfer_pg_to_sf', 
                  'verify_pg_data', 'verify_sf_data', 'cleanup', 'end']
for step in critical_steps:
    assert step in step_names, f"Missing critical step: {step}"
    print(f"  ✓ {step}")

print("")
print("All playbook structure checks passed!")
PYEOF

echo ""
echo "Step 5: Check credential templates"
echo "──────────────────────────────────────────────────────────────"
.venv/bin/python << 'PYEOF'
import json

# Check credential structure
with open('tests/fixtures/credentials/sf_test.json', 'r') as f:
    cred = json.load(f)

required_fields = ['name', 'type', 'description', 'data']
for field in required_fields:
    assert field in cred, f"Missing field: {field}"
    value = str(cred.get(field, ''))[:50] if field != 'data' else '<data dict>'
    print(f"✓ {field}: {value}")

# Check data fields
data_fields = ['sf_account', 'sf_user', 'sf_password', 'sf_warehouse', 
               'sf_database', 'sf_schema', 'sf_role']
for field in data_fields:
    assert field in cred['data'], f"Missing data field: {field}"

print(f"✓ All required credential fields present")
PYEOF

echo ""
echo "Step 6: Test transfer module independently"
echo "──────────────────────────────────────────────────────────────"
.venv/bin/python << 'PYEOF'
from noetl.plugin.snowflake.transfer import _convert_value
from decimal import Decimal
from datetime import datetime

# Test value conversion
assert _convert_value(None) is None
assert _convert_value("test") == "test"
assert _convert_value(123) == 123
assert _convert_value(Decimal("123.45")) == 123.45

dt = datetime(2024, 1, 1, 12, 0, 0)
assert _convert_value(dt) == dt.isoformat()

print("✓ Value conversion functions working correctly")

# Test function signatures
from noetl.plugin.snowflake.transfer import transfer_snowflake_to_postgres, transfer_postgres_to_snowflake
import inspect

sig1 = inspect.signature(transfer_snowflake_to_postgres)
assert 'sf_conn' in sig1.parameters
assert 'pg_conn' in sig1.parameters
assert 'source_query' in sig1.parameters
assert 'target_table' in sig1.parameters
assert 'chunk_size' in sig1.parameters
assert 'mode' in sig1.parameters
print("✓ transfer_snowflake_to_postgres signature correct")

sig2 = inspect.signature(transfer_postgres_to_snowflake)
assert 'pg_conn' in sig2.parameters
assert 'sf_conn' in sig2.parameters
print("✓ transfer_postgres_to_snowflake signature correct")

print("")
print("All transfer module tests passed!")
PYEOF

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo -e "  ${GREEN}All validation tests passed!${NC}"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Next steps:"
echo ""
echo "1. Update Snowflake credentials in:"
echo "   tests/fixtures/credentials/sf_test.json"
echo ""
echo "2. Set environment variables:"
echo "   export SF_ACCOUNT=\"your_account.region\""
echo "   export SF_USER=\"your_username\""
echo "   export SF_PASSWORD=\"your_password\""
echo "   export SF_DATABASE=\"TEST_DB\""
echo "   # ... (see README for complete list)"
echo ""
echo "3. Register Snowflake credential:"
echo "   curl -X POST http://localhost:8082/api/credentials \\"
echo "     -H \"Content-Type: application/json\" \\"
echo "     --data-binary @tests/fixtures/credentials/sf_test.json"
echo ""
echo "4. Register and run the playbook:"
echo "   task noetltest:playbook-register -- \\"
echo "     tests/fixtures/playbooks/snowflake_transfer/snowflake_transfer.yaml"
echo ""
echo "   task noetltest:playbook-execute -- \\"
echo "     tests/fixtures/playbooks/snowflake_transfer"
echo ""
echo "See tests/fixtures/playbooks/snowflake_transfer/README.md for complete guide."
echo ""
