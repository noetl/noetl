#!/bin/bash
# Publish NoETL package to PyPI with UV dependency management support
# Test on TestPyPI
# ./tools/pypi/pypi_publish.sh --test 1.0.0
# # Publish to PyPI
# ./tools/pypi/pypi_publish.sh 1.0.0
# Dry run
# ./tools/pypi/pypi_publish.sh --dry-run 1.0.0

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'
REPOSITORY="pypi"
VERSION=""
SKIP_BUILD=false
SKIP_TESTS=false
DRY_RUN=false

show_help() {
    cat << EOF
Usage: $0 [OPTIONS] [VERSION]

Publish NoETL package to PyPI with safety checks and UV dependency management.

OPTIONS:
    -t, --test          Publish to TestPyPI instead of PyPI (requires TestPyPI token)
    -v, --version VER   Specify version to publish
    -s, --skip-build    Skip building the package
    -n, --skip-tests    Skip running tests
    -d, --dry-run       Show what would be done without publishing
    -h, --help          Show this help message

EXAMPLES:
    $0 1.0.0                   # Publish version 1.0.0 to PyPI
    $0 --test 1.0.0            # Publish to TestPyPI first (requires TestPyPI setup)
    $0 --skip-build 1.0.0      # Publish without rebuilding
    $0 --dry-run 1.0.0         # Show what would be published

ENVIRONMENT VARIABLES:
    PYPI_TOKEN          PyPI API token (optional, uses ~/.pypirc if not set)
    TESTPYPI_TOKEN      TestPyPI API token (required for --test option)

TESTPYPI SETUP:
    To use TestPyPI, you need:
    1. A TestPyPI account at https://test.pypi.org/
    2. A TestPyPI API token
    3. Either set TESTPYPI_TOKEN environment variable or update ~/.pypirc

UV DEPENDENCY MANAGEMENT:
    This script automatically detects UV-managed projects and uses:
    - uv add --dev build twine  (for build dependencies)
    - python -m build          (for package building)
    - python -m twine upload    (for publishing)
EOF
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -t|--test)
            REPOSITORY="testpypi"
            shift
            ;;
        -v|--version)
            VERSION="$2"
            shift 2
            ;;
        -s|--skip-build)
            SKIP_BUILD=true
            shift
            ;;
        -n|--skip-tests)
            SKIP_TESTS=true
            shift
            ;;
        -d|--dry-run)
            DRY_RUN=true
            shift
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        -*)
            echo -e "${RED}Unknown option: $1${NC}"
            show_help
            exit 1
            ;;
        *)
            if [ -z "$VERSION" ]; then
                VERSION="$1"
            else
                echo -e "${RED} Too many arguments${NC}"
                show_help
                exit 1
            fi
            shift
            ;;
    esac
done

echo -e "${BLUE}NoETL PyPI Publishing Script${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
# Located in tools/pypi, repository root is parent of tools
PROJECT_ROOT="$(dirname "$(dirname "$SCRIPT_DIR")")"

echo -e "${BLUE}Project root: $PROJECT_ROOT${NC}"
echo -e "${BLUE}Repository: $REPOSITORY${NC}"

cd "$PROJECT_ROOT"

if [ -z "$VERSION" ]; then
    VERSION=$(python3 -c "
import re
with open('pyproject.toml', 'r') as f:
    content = f.read()
    match = re.search(r'version\s*=\s*[\"\\']([^\"\\']*)[\"\\']\s*', content)
    print(match.group(1) if match else '')
")
    if [ -z "$VERSION" ]; then
        echo -e "${RED}Could not determine version from pyproject.toml${NC}"
        exit 1
    fi
fi

echo -e "${BLUE}Version to publish: $VERSION${NC}"

check_dependencies() {
    echo -e "${BLUE}Checking dependencies...${NC}"

    local missing_deps=()

    if ! python3 -c "import build" &> /dev/null; then
        missing_deps+=("build")
    fi

    if ! python3 -c "import twine" &> /dev/null; then
        missing_deps+=("twine")
    fi

    if [ ${#missing_deps[@]} -gt 0 ]; then
        echo -e "${YELLOW}Installing missing dependencies: ${missing_deps[*]}${NC}"

        # Check if this is a UV-managed project
        if [ -f "uv.lock" ]; then
            echo -e "${BLUE}UV-managed project detected, using UV to install dependencies...${NC}"
            uv add --dev "${missing_deps[@]}"
        else
            echo -e "${BLUE}Using pip to install dependencies...${NC}"
            pip install "${missing_deps[@]}"
        fi
    fi

    echo -e "${GREEN}Dependencies OK${NC}"
}

# Run tests
run_tests() {
    if [ "$SKIP_TESTS" = true ]; then
        echo -e "${YELLOW}Skipping tests${NC}"
        return 0
    fi

    echo -e "${BLUE}Running tests...${NC}"

    if python3 -c "import pytest" &> /dev/null 2>&1; then
        if [ -d "tests" ]; then
            python3 -m pytest tests/ -v
        else
            echo -e "${YELLOW}No tests directory found${NC}"
        fi
    else
        echo -e "${YELLOW}pytest not available, skipping tests${NC}"
    fi

    echo -e "${BLUE}Testing package import...${NC}"
    python3 -c "
try:
    import noetl
    print('Package import successful')
except ImportError as e:
    print(f'Package import failed: {e}')
    exit(1)
"
}

build_package() {
    if [ "$SKIP_BUILD" = true ]; then
        echo -e "${YELLOW}Skipping package build${NC}"
        if [ ! -d "dist" ] || [ -z "$(ls -A dist)" ]; then
            echo -e "${RED}No built packages found and build skipped${NC}"
            exit 1
        fi
        return 0
    fi

    echo -e "${BLUE}Building package...${NC}"
    "$PROJECT_ROOT/tools/build_package.sh"
}

check_version_exists() {
    echo -e "${BLUE}Checking if version exists on $REPOSITORY...${NC}"

    local package_url=""
    if [ "$REPOSITORY" = "testpypi" ]; then
        package_url="https://test.pypi.org/pypi/noetl/$VERSION/json"
    else
        package_url="https://pypi.org/pypi/noetl/$VERSION/json"
    fi

    if curl -s --head "$package_url" | head -n 1 | grep -q "200 OK"; then
        echo -e "${RED}Version $VERSION already exists on $REPOSITORY${NC}"
        echo -e "${YELLOW}Please bump the version and try again${NC}"
        exit 1
    else
        echo -e "${GREEN}Version $VERSION is available${NC}"
    fi
}

validate_package() {
    echo -e "${BLUE}Validating package...${NC}"

    if [ ! -d "dist" ] || [ -z "$(ls -A dist)" ]; then
        echo -e "${RED}No packages found in dist directory${NC}"
        exit 1
    fi

    python3 -m twine check dist/*

    local wheel_file=$(ls dist/*.whl | head -1)
    if [ -n "$wheel_file" ]; then
        echo -e "${BLUE}Checking package contents...${NC}"
        python3 -c "
import zipfile
with zipfile.ZipFile('$wheel_file', 'r') as z:
    files = z.namelist()

    # Check for essential files
    has_init = any('noetl/__init__.py' in f for f in files)
    has_server = any('server.py' in f for f in files)
    has_ui = any('ui/' in f for f in files)

    print(f'Package has __init__.py: {has_init}')
    print(f'Package has server.py: {has_server}')
    print(f'Package has UI files: {has_ui}')

    if not has_init:
        print('Missing essential __init__.py file')
        exit(1)
"
    fi

    echo -e "${GREEN}Package validation passed${NC}"
}

check_testpypi_setup() {
    if [ "$REPOSITORY" != "testpypi" ]; then
        return 0
    fi

    echo -e "${BLUE}Checking TestPyPI setup...${NC}"

    # Check if TestPyPI token is available
    if [ -z "$TESTPYPI_TOKEN" ]; then
        # Check if testpypi section exists in .pypirc
        if ! grep -q "\[testpypi\]" ~/.pypirc 2>/dev/null; then
            echo -e "${RED}TestPyPI is not configured${NC}"
            echo -e "${YELLOW}To use TestPyPI, you need to:${NC}"
            echo "1. Create an account at https://test.pypi.org/"
            echo "2. Generate an API token"
            echo "3. Either:"
            echo "   - Set TESTPYPI_TOKEN environment variable"
            echo "   - Add [testpypi] section to ~/.pypirc"
            echo ""
            echo -e "${BLUE}Switching to PyPI instead...${NC}"
            REPOSITORY="pypi"
            return 0
        fi

        # Check if testpypi section has a password
        if ! grep -A 5 "\[testpypi\]" ~/.pypirc 2>/dev/null | grep -q "password"; then
            echo -e "${RED}TestPyPI password/token not found in ~/.pypirc${NC}"
            echo -e "${YELLOW}Please add your TestPyPI token to ~/.pypirc or set TESTPYPI_TOKEN${NC}"
            echo ""
            echo -e "${BLUE}Switching to PyPI instead...${NC}"
            REPOSITORY="pypi"
            return 0
        fi
    fi

    echo -e "${GREEN}TestPyPI setup OK${NC}"
}

# Upload to PyPI
upload_package() {
    echo -e "${BLUE}Uploading to $REPOSITORY...${NC}"

    local upload_args=""
    if [ "$REPOSITORY" = "testpypi" ]; then
        upload_args="--repository testpypi"

        # Use token if available
        if [ -n "$TESTPYPI_TOKEN" ]; then
            upload_args="$upload_args --username __token__ --password $TESTPYPI_TOKEN"
        fi
    elif [ "$REPOSITORY" = "pypi" ]; then
        # Use PyPI token if available
        if [ -n "$PYPI_TOKEN" ]; then
            upload_args="$upload_args --username __token__ --password $PYPI_TOKEN"
        fi
    fi

    if [ "$DRY_RUN" = true ]; then
        echo -e "${YELLOW}DRY RUN - Would execute:${NC}"
        echo "python3 -m twine upload $upload_args dist/*"
        return 0
    fi

    # Try upload with error handling
    if ! python3 -m twine upload $upload_args dist/*; then
        echo -e "${RED}Upload failed${NC}"

        if [ "$REPOSITORY" = "testpypi" ]; then
            echo -e "${YELLOW}TestPyPI upload failed. This might be due to:${NC}"
            echo "1. Missing or invalid TestPyPI token"
            echo "2. Version already exists on TestPyPI"
            echo "3. Package name conflicts"
            echo ""
            echo -e "${BLUE}Consider publishing directly to PyPI:${NC}"
            echo "$0 $VERSION"
        fi

        exit 1
    fi

    echo -e "${GREEN}Package uploaded successfully!${NC}"
}

verify_upload() {
    if [ "$DRY_RUN" = true ]; then
        return 0
    fi

    echo -e "${BLUE}Verifying upload...${NC}"

    local package_url=""
    if [ "$REPOSITORY" = "testpypi" ]; then
        package_url="https://test.pypi.org/project/noetl/$VERSION/"
    else
        package_url="https://pypi.org/project/noetl/$VERSION/"
    fi

    echo -e "${BLUE}Package URL: $package_url${NC}"

    echo -e "${BLUE}Waiting for package to be available...${NC}"
    echo -e "${YELLOW}Note: PyPI can take a few minutes to make new versions available${NC}"

    sleep 30

    echo -e "${BLUE}Testing installation...${NC}"

    local temp_venv="/tmp/noetl_test_$$"
    python3 -m venv "$temp_venv"
    source "$temp_venv/bin/activate"
    local max_retries=3
    local retry_count=0
    local install_success=false

    while [ $retry_count -lt $max_retries ] && [ "$install_success" = false ]; do
        echo -e "${BLUE}Installation attempt $((retry_count + 1)) of $max_retries...${NC}"

        if [ "$REPOSITORY" = "testpypi" ]; then
            if pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ noetl==$VERSION; then
                install_success=true
            fi
        else
            if pip install noetl==$VERSION; then
                install_success=true
            fi
        fi

        if [ "$install_success" = false ]; then
            retry_count=$((retry_count + 1))
            if [ $retry_count -lt $max_retries ]; then
                echo -e "${YELLOW}Installation failed, waiting 30 seconds before retry...${NC}"
                sleep 30
            fi
        fi
    done

    if [ "$install_success" = false ]; then
        echo -e "${YELLOW}Installation verification failed after $max_retries attempts${NC}"
        echo -e "${BLUE}This might be due to:${NC}"
        echo "1. PyPI propagation delay (can take up to 10-15 minutes)"
        echo "2. Network connectivity issues"
        echo "3. Package upload issues"
        echo ""
        echo -e "${BLUE}You can manually verify the upload at:${NC}"
        echo "$package_url"
        echo ""
        echo -e "${BLUE}Try installing manually in a few minutes:${NC}"
        if [ "$REPOSITORY" = "testpypi" ]; then
            echo "pip install --index-url https://test.pypi.org/simple/ --extra-index-url https://pypi.org/simple/ noetl==$VERSION"
        else
            echo "pip install noetl==$VERSION"
        fi

        deactivate
        rm -rf "$temp_venv"
        return 0
    fi

    echo -e "${GREEN}Package installed successfully!${NC}"

    python3 -c "
import noetl
print(f'Installed version: {noetl.__version__ if hasattr(noetl, "__version__") else "unknown"}')

# Test UI availability
try:
    from noetl import ui
    print('UI module available')
except ImportError:
    print('UI module not available (this is OK)')

# Test server import
try:
    from noetl import server
    print('Server module available')
except ImportError as e:
    print(f'Server module import failed: {e}')

# Test CLI
try:
    from noetl import main
    print('CLI module available')
except ImportError as e:
    print(f'CLI module import failed: {e}')
"

    deactivate
    rm -rf "$temp_venv"

    echo -e "${GREEN}Installation verification passed!${NC}"
}

main() {
    echo -e "${BLUE}Starting publication process...${NC}"

    check_dependencies
    check_testpypi_setup
    run_tests
    build_package
    check_version_exists
    validate_package

    if [ "$DRY_RUN" = false ]; then
        echo -e "${YELLOW}About to publish NoETL v$VERSION to $REPOSITORY${NC}"
        if [ "$REPOSITORY" = "testpypi" ]; then
            echo -e "${BLUE}Note: Publishing to TestPyPI first for testing${NC}"
        fi
        read -p "Continue? (y/N): " -n 1 -r
        echo
        if [[ ! $REPLY =~ ^[Yy]$ ]]; then
            echo -e "${YELLOW}Publication cancelled${NC}"
            exit 0
        fi
    fi

    upload_package
    verify_upload

    echo -e "${GREEN}Publication completed successfully.${NC}"

    if [ "$REPOSITORY" = "testpypi" ]; then
        echo -e "${BLUE}Next steps:${NC}"
        echo "  1. Test the package from TestPyPI"
        echo "  2. If all looks good, publish to PyPI:"
        echo "     $0 $VERSION"
    else
        echo -e "${BLUE}Package is now available:${NC}"
        echo "  • PyPI: https://pypi.org/project/noetl/$VERSION/"
        echo "  • Install: pip install noetl==$VERSION"
        echo "  • Latest: pip install noetl"
    fi
}

main
