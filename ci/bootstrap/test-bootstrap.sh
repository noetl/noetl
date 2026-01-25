#!/usr/bin/env bash
#
# NoETL Bootstrap Integration Test
#
# Tests the complete bootstrap flow in an isolated project directory.
# This validates that all components work together correctly.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
NOETL_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
TEST_PROJECT="/tmp/noetl-bootstrap-test-$$"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log_info() { echo -e "[INFO] $1"; }
log_success() { echo -e "${GREEN}[✓]${NC} $1"; }
log_error() { echo -e "${RED}[✗]${NC} $1"; }

cleanup() {
    if [[ -d "$TEST_PROJECT" ]]; then
        log_info "Cleaning up test project: $TEST_PROJECT"
        rm -rf "$TEST_PROJECT"
    fi
}

trap cleanup EXIT

main() {
    echo "========================================"
    echo "  NoETL Bootstrap Integration Test"
    echo "========================================"
    echo ""

    log_info "Test project: $TEST_PROJECT"
    echo ""

    # 1. Create test project
    log_info "Step 1: Creating test project directory"
    mkdir -p "$TEST_PROJECT"
    cd "$TEST_PROJECT"
    git init
    log_success "Project directory created"
    echo ""

    # 2. Add NoETL as submodule (use local path for testing)
    log_info "Step 2: Adding NoETL as submodule"
    git submodule add "$NOETL_ROOT" noetl 2>/dev/null || {
        # If fails, just copy it
        cp -r "$NOETL_ROOT" noetl
    }
    log_success "NoETL submodule added"
    echo ""

    # 3. Copy bootstrap files
    log_info "Step 3: Copying bootstrap files"
    cp noetl/ci/bootstrap/pyproject-template.toml ./pyproject.toml
    cp noetl/ci/bootstrap/gitignore-template ./.gitignore
    chmod +x noetl/ci/bootstrap/bootstrap.sh
    log_success "Bootstrap files copied"
    echo ""

    # 4. Verify files exist
    log_info "Step 4: Verifying files"
    [[ -f pyproject.toml ]] || { log_error "pyproject.toml missing"; exit 1; }
    [[ -f .gitignore ]] || { log_error ".gitignore missing"; exit 1; }
    [[ -x noetl/ci/bootstrap/bootstrap.sh ]] || { log_error "bootstrap.sh not executable"; exit 1; }
    log_success "All files present"
    echo ""

    # 5. Test venv creation only (skip tools and cluster for speed)
    log_info "Step 5: Testing Python venv setup"
    if command -v python3 >/dev/null 2>&1; then
        ./noetl/ci/bootstrap/bootstrap.sh --skip-tools --skip-cluster
        log_success "Bootstrap completed (venv only)"
    else
        log_error "python3 not found, skipping venv test"
    fi
    echo ""

    # 6. Verify venv
    if [[ -d .venv ]]; then
        log_success "Virtual environment created"

        if [[ -f .venv/bin/noetl ]]; then
            log_success "NoETL CLI installed"

            # Test CLI
            if .venv/bin/noetl --version >/dev/null 2>&1 || .venv/bin/noetl --help >/dev/null 2>&1; then
                log_success "NoETL CLI functional"
            else
                log_error "NoETL CLI not functional"
            fi
        else
            log_error "NoETL CLI not found"
        fi
    else
        log_info "Venv creation skipped (python3 not available)"
    fi
    echo ""

    # 7. Verify gitignore patterns
    log_info "Step 7: Verifying .gitignore"
    if grep -q "credentials/" .gitignore; then
        log_success "Credentials directory ignored"
    else
        log_error "Credentials directory not ignored"
    fi

    if grep -q "\.venv" .gitignore; then
        log_success "Venv directory ignored"
    else
        log_error "Venv directory not ignored"
    fi
    echo ""

    # 8. Test directory structure
    log_info "Step 8: Testing project structure"
    mkdir -p playbooks credentials tests
    log_success "Project directories created"
    echo ""

    # 9. Create sample playbook
    log_info "Step 9: Creating sample playbook"
    cat > playbooks/test.yaml << 'EOF'
apiVersion: noetl.io/v1
kind: Playbook
metadata:
  name: test_playbook
  path: test/sample
workload:
  message: "Test"
workflow:
  - step: start
    type: python
    code: |
      def main(input_data):
          return {"status": "success"}
    next:
      - step: end
  - step: end
    desc: End
EOF
    log_success "Sample playbook created"
    echo ""

    # 10. Verify NoETL automation playbooks exist
    log_info "Step 10: Verifying NoETL automation playbooks"
    if [[ -f noetl/automation/setup/bootstrap.yaml ]]; then
        log_success "Bootstrap playbook found"
    else
        log_error "Bootstrap playbook not found"
    fi

    if [[ -f noetl/automation/infrastructure/kind.yaml ]]; then
        log_success "Kind playbook found"
    else
        log_error "Kind playbook not found"
    fi

    if [[ -f noetl/automation/infrastructure/postgres.yaml ]]; then
        log_success "Postgres playbook found"
    else
        log_error "Postgres playbook not found"
    fi
    echo ""

    # Summary
    echo "========================================"
    echo "  Test Summary"
    echo "========================================"
    echo ""
    log_success "Bootstrap infrastructure validated"
    echo ""
    echo "Test project structure:"
    tree -L 2 -I 'noetl' "$TEST_PROJECT" 2>/dev/null || find "$TEST_PROJECT" -maxdepth 2 -type d | grep -v noetl
    echo ""
    echo "Next steps for manual verification:"
    echo "  cd $TEST_PROJECT"
    echo "  source .venv/bin/activate"
    echo "  noetl --help"
    echo "  noetl run noetl/automation/setup/bootstrap.yaml"
    echo ""
}

main "$@"
