#!/bin/bash
# Snowflake Plugin Installation Verification Script

echo "═══════════════════════════════════════════════════════════════"
echo "  NoETL Snowflake Plugin - Installation Verification"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

success=0
fail=0

check_item() {
    local name="$1"
    local command="$2"
    
    printf "Checking %-50s " "$name..."
    if eval "$command" > /dev/null 2>&1; then
        echo -e "${GREEN}✓${NC}"
        ((success++))
        return 0
    else
        echo -e "${RED}✗${NC}"
        ((fail++))
        return 1
    fi
}

echo "1. Checking Plugin Files"
echo "─────────────────────────────────────────────────────────────"
check_item "Snowflake plugin directory" "test -d noetl/plugin/snowflake"
check_item "Plugin __init__.py" "test -f noetl/plugin/snowflake/__init__.py"
check_item "Plugin auth.py" "test -f noetl/plugin/snowflake/auth.py"
check_item "Plugin command.py" "test -f noetl/plugin/snowflake/command.py"
check_item "Plugin execution.py" "test -f noetl/plugin/snowflake/execution.py"
check_item "Plugin response.py" "test -f noetl/plugin/snowflake/response.py"
check_item "Plugin executor.py" "test -f noetl/plugin/snowflake/executor.py"
echo ""

echo "2. Checking Integration"
echo "─────────────────────────────────────────────────────────────"
check_item "Plugin import in __init__.py" "grep -q 'from .snowflake import' noetl/plugin/__init__.py"
check_item "Plugin in REGISTRY" "grep -q 'snowflake' noetl/plugin/__init__.py"
check_item "Plugin in execution.py" "grep -q 'snowflake' noetl/plugin/tool/execution.py"
check_item "Plugin in broker.py" "grep -q 'snowflake' noetl/server/api/event/processing/broker.py"
check_item "Dependency in pyproject.toml" "grep -q 'snowflake-connector-python' pyproject.toml"
echo ""

echo "3. Checking Examples"
echo "─────────────────────────────────────────────────────────────"
check_item "Examples directory" "test -d examples/snowflake"
check_item "Simple test playbook" "test -f examples/snowflake/snowflake_simple.yaml"
check_item "Comprehensive test playbook" "test -f examples/snowflake/snowflake_test.yaml"
check_item "Credentials template" "test -f examples/snowflake/snowflake_credentials.yaml"
check_item "Setup guide" "test -f examples/snowflake/SETUP_GUIDE.md"
check_item "README" "test -f examples/snowflake/README.md"
echo ""

echo "4. Checking Python Environment"
echo "─────────────────────────────────────────────────────────────"
check_item "Virtual environment" "test -d .venv"
check_item "Python executable" "test -x .venv/bin/python"

# Check if snowflake connector can be imported
if .venv/bin/python -c "import snowflake.connector" 2>/dev/null; then
    echo -e "Snowflake connector installed                             ${GREEN}✓${NC}"
    ((success++))
else
    echo -e "Snowflake connector installed                             ${YELLOW}⚠${NC} (needs installation)"
    echo "  Run: task install-dev"
fi
echo ""

echo "═══════════════════════════════════════════════════════════════"
echo "  Verification Results"
echo "═══════════════════════════════════════════════════════════════"
echo -e "Passed: ${GREEN}${success}${NC}"
echo -e "Failed: ${RED}${fail}${NC}"
echo ""

if [ $fail -eq 0 ]; then
    echo -e "${GREEN}✓ All checks passed! Snowflake plugin is ready.${NC}"
    echo ""
    echo "Next Steps:"
    echo "  1. Install dependencies: task install-dev"
    echo "  2. Review setup guide: examples/snowflake/SETUP_GUIDE.md"
    echo "  3. Configure Snowflake credentials"
    echo "  4. Run test playbook"
    exit 0
else
    echo -e "${RED}✗ Some checks failed. Please review the output above.${NC}"
    exit 1
fi
