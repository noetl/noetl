#!/bin/bash
# verify_fixture.sh - Verify all required files exist for container_postgres_init fixture

set -e

FIXTURE_DIR="tests/fixtures/playbooks/container_postgres_init"

echo "========================================"
echo "Container PostgreSQL Init Fixture Verification"
echo "========================================"
echo ""

# Check main files
echo "Checking main files..."
files=(
    "$FIXTURE_DIR/container_postgres_init.yaml"
    "$FIXTURE_DIR/Dockerfile"
    "$FIXTURE_DIR/README.md"
    "$FIXTURE_DIR/QUICKSTART.md"
    "$FIXTURE_DIR/build.sh"
    "$FIXTURE_DIR/.dockerignore"
)

missing=0
for file in "${files[@]}"; do
    if [ -f "$file" ]; then
        echo "✓ $file"
    else
        echo "✗ $file (MISSING)"
        ((missing++))
    fi
done

# Check scripts
echo ""
echo "Checking scripts..."
scripts=(
    "$FIXTURE_DIR/scripts/init_schema.sh"
    "$FIXTURE_DIR/scripts/create_tables.sh"
    "$FIXTURE_DIR/scripts/seed_data.sh"
)

for script in "${scripts[@]}"; do
    if [ -f "$script" ]; then
        if [ -x "$script" ]; then
            echo "✓ $script (executable)"
        else
            echo "⚠ $script (not executable)"
            chmod +x "$script"
            echo "  → Made executable"
        fi
    else
        echo "✗ $script (MISSING)"
        ((missing++))
    fi
done

# Check SQL files
echo ""
echo "Checking SQL files..."
sql_files=(
    "$FIXTURE_DIR/sql/create_schema.sql"
    "$FIXTURE_DIR/sql/create_tables.sql"
    "$FIXTURE_DIR/sql/seed_data.sql"
)

for sql in "${sql_files[@]}"; do
    if [ -f "$sql" ]; then
        lines=$(wc -l < "$sql")
        echo "✓ $sql ($lines lines)"
    else
        echo "✗ $sql (MISSING)"
        ((missing++))
    fi
done

# Check tasks
echo ""
echo "Checking task definitions..."
task_names=(
    "test:container:build-image"
    "test:container:register"
    "test:container:execute"
    "test:container:verify"
    "test:container:cleanup"
    "test:container:full"
)

for task_name in "${task_names[@]}"; do
    if task --list 2>/dev/null | grep -q "$task_name"; then
        echo "✓ $task_name"
    else
        echo "✗ $task_name (NOT FOUND)"
        ((missing++))
    fi
done

# Summary
echo ""
echo "========================================"
if [ $missing -eq 0 ]; then
    echo "✅ All files verified successfully!"
    echo "========================================"
    echo ""
    echo "Quick Start:"
    echo "  1. task test:container:build-image"
    echo "  2. task test:container:full"
    echo "  3. task test:container:verify"
    echo ""
    echo "Documentation:"
    echo "  - README:     $FIXTURE_DIR/README.md"
    echo "  - Quickstart: $FIXTURE_DIR/QUICKSTART.md"
    exit 0
else
    echo "❌ $missing file(s) missing or issues found"
    echo "========================================"
    exit 1
fi
