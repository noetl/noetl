#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Building NoETL Package for PyPI (UV Environment)...${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

echo -e "${BLUE}Project root: $PROJECT_ROOT${NC}"

cd "$PROJECT_ROOT"

if [ ! -f "pyproject.toml" ]; then
    echo -e "${RED}ERROR: pyproject.toml not found${NC}"
    exit 1
fi

CURRENT_VERSION=$(python3 -c "
import re
with open('pyproject.toml', 'r') as f:
    content = f.read()
    match = re.search(r'version\s*=\s*[\"\\']([^\"\\']*)[\"\\']\s*', content)
    print(match.group(1) if match else 'unknown')
")

echo -e "${BLUE}Current version: $CURRENT_VERSION${NC}"

echo -e "${BLUE}Cleaning previous builds...${NC}"
rm -rf dist/ build/ *.egg-info/
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo -e "${BLUE}Checking for UI files in noetl/ui...${NC}"
if [ -d "noetl/ui" ]; then
    echo -e "${GREEN}noetl/ui directory found${NC}"

    if [ -f "noetl/ui/__init__.py" ]; then
        echo -e "${GREEN}noetl/ui/__init__.py found${NC}"
    else
        echo -e "${YELLOW}noetl/ui/__init__.py not found, creating it${NC}"
        mkdir -p noetl/ui
        echo '"""
NoETL UI Package

This package contains the web user interface components for NoETL,
including static CSS, JS, and HTML template files.
"""

__version__ = "'$CURRENT_VERSION'"' > noetl/ui/__init__.py
    fi

    if [ -d "noetl/ui/static" ]; then
        echo -e "${GREEN}noetl/ui/static directory found${NC}"
        if [ -f "noetl/ui/static/__init__.py" ]; then
            echo -e "${GREEN}noetl/ui/static/__init__.py found${NC}"
        else
            echo -e "${YELLOW}noetl/ui/static/__init__.py not found, creating it${NC}"
            mkdir -p noetl/ui/static
            echo '"""NoETL UI Static Files"""' > noetl/ui/static/__init__.py
        fi
    else
        echo -e "${YELLOW}noetl/ui/static directory not found, creating it${NC}"
        mkdir -p noetl/ui/static
        echo '"""NoETL UI Static Files"""' > noetl/ui/static/__init__.py
    fi

    if [ -d "noetl/ui/templates" ]; then
        echo -e "${GREEN}noetl/ui/templates directory found${NC}"
        if [ -f "noetl/ui/templates/__init__.py" ]; then
            echo -e "${GREEN}noetl/ui/templates/__init__.py found${NC}"
        else
            echo -e "${YELLOW}noetl/ui/templates/__init__.py not found, creating it${NC}"
            mkdir -p noetl/ui/templates
            echo '"""NoETL UI Templates"""' > noetl/ui/templates/__init__.py
        fi
    else
        echo -e "${YELLOW}noetl/ui/templates directory not found, creating it${NC}"
        mkdir -p noetl/ui/templates
        echo '"""NoETL UI Templates"""' > noetl/ui/templates/__init__.py
    fi

    UI_FILES=$(find noetl/ui -type f -not -path "*/\.*" -not -name "__init__.py" | wc -l | tr -d ' ')
    echo -e "${BLUE}   Total UI files: $UI_FILES${NC}"

    if [ -d "noetl/ui/static" ]; then
        STATIC_FILES=$(find noetl/ui/static -type f -not -path "*/\.*" -not -name "__init__.py" | wc -l | tr -d ' ')
        echo -e "${BLUE}   Static files: $STATIC_FILES${NC}"
    fi

    if [ -d "noetl/ui/templates" ]; then
        TEMPLATE_FILES=$(find noetl/ui/templates -type f -not -path "*/\.*" -not -name "__init__.py" | wc -l | tr -d ' ')
        echo -e "${BLUE}   Template files: $TEMPLATE_FILES${NC}"
    fi
else
    echo -e "${YELLOW}noetl/ui directory not found, creating it${NC}"
    mkdir -p noetl/ui
    echo '"""NoETL UI Package"""' > noetl/ui/__init__.py
    mkdir -p noetl/ui/static
    echo '"""NoETL UI Static Files"""' > noetl/ui/static/__init__.py
    mkdir -p noetl/ui/templates
    echo '"""NoETL UI Templates"""' > noetl/ui/templates/__init__.py
fi

echo -e "${BLUE}Updating MANIFEST.in...${NC}"
cat > MANIFEST.in << 'EOF'
include README.md
include LICENSE
include pyproject.toml
recursive-include noetl *.py
recursive-include noetl/ui *
recursive-include noetl/ui/static *
recursive-include noetl/ui/templates *
include noetl/ui/__init__.py
include noetl/ui/static/__init__.py
include noetl/ui/templates/__init__.py
graft noetl/ui
global-exclude __pycache__
global-exclude *.py[co]
global-exclude .DS_Store
global-exclude *.so
exclude .gitignore
exclude .env*
exclude docker-compose*.yml
exclude Dockerfile*
exclude uv.lock
EOF

echo -e "${BLUE}Building sdist...${NC}"
python3 -m build --sdist
echo -e "${BLUE}Building wheel...${NC}"
python3 -m build --wheel

echo -e "${GREEN}Build completed successfully!${NC}"
echo -e "${BLUE}Built packages:${NC}"
ls -la dist/

echo -e "${BLUE}Validating built packages...${NC}"
python3 -m twine check dist/*

echo -e "${BLUE}Verifying UI files are included in the wheel package...${NC}"
WHEEL_FILE=$(ls dist/*.whl | head -1)
if [ -n "$WHEEL_FILE" ]; then
    echo -e "${BLUE}Extracting wheel package to verify UI files...${NC}"
    TEMP_DIR=$(mktemp -d)
    unzip -q "$WHEEL_FILE" -d "$TEMP_DIR"

    if [ -d "$TEMP_DIR/noetl/ui" ]; then
        echo -e "${GREEN}noetl/ui directory found in wheel package${NC}"
        UI_FILES=$(find "$TEMP_DIR/noetl/ui" -type f | wc -l | tr -d ' ')
        echo -e "${GREEN}UI files found in wheel package: $UI_FILES${NC}"
    else
        echo -e "${RED}noetl/ui directory not found in wheel package${NC}"
    fi

    rm -rf "$TEMP_DIR"
fi

echo -e "${GREEN}Ready for publishing!${NC}"