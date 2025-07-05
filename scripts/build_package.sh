#!/bin/bash
# Build NoETL package for PyPI distribution with UV support

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

if [ ! -f "uv.lock" ]; then
    echo -e "${YELLOW}WARNING: No uv.lock found. This script is optimized for UV-managed projects.${NC}"
fi

CURRENT_VERSION=$(python3 -c "
import re
with open('pyproject.toml', 'r') as f:
    content = f.read()
    match = re.search(r'version\s*=\s*[\"\\']([^\"\\']*)[\"\\']\s*', content)
    print(match.group(1) if match else 'unknown')
")

echo -e "${BLUE}Current version: $CURRENT_VERSION${NC}"

echo -e "${BLUE}Checking build dependencies...${NC}"
if ! python3 -c "import build" &> /dev/null; then
    echo -e "${YELLOW}Installing build tools using UV...${NC}"
    uv add --dev build twine
else
    echo -e "${GREEN}Build tools already available${NC}"
fi

echo -e "${BLUE}Cleaning previous builds...${NC}"
rm -rf dist/ build/ *.egg-info/
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo -e "${BLUE}Building UI components...${NC}"
if [ -f "$SCRIPT_DIR/build_ui.sh" ]; then
    "$SCRIPT_DIR/build_ui.sh"
else
    echo -e "${YELLOW}UI build script not found, skipping UI build${NC}"
fi

if [ -d "ui/static" ] && [ "$(ls -A ui/static)" ]; then
    echo -e "${GREEN}UI assets found${NC}"
    UI_FILES=$(find ui/static -type f | wc -l | tr -d ' ')
    echo -e "${BLUE}   UI files: $UI_FILES${NC}"
else
    echo -e "${YELLOW}No UI assets found${NC}"
fi

echo -e "${BLUE}Updating MANIFEST.in...${NC}"
cat > MANIFEST.in << 'EOF'
include README.md
include LICENSE
include CHANGELOG.md
include pyproject.toml
recursive-include noetl *.py
recursive-include ui/static *
recursive-include ui/templates *
include ui/__init__.py
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

echo -e "${BLUE}Validating package configuration...${NC}"

python3 -c "
import re
with open('pyproject.toml', 'r') as f:
    content = f.read()
    if 'dependencies' in content:
        print('Dependencies found')
    else:
        print('WARNING: No dependencies section found')

    if 'fastapi' in content:
        print('FastAPI dependency found')
    else:
        print('WARNING: FastAPI dependency not found')
"

echo -e "${BLUE}Building package using UV environment...${NC}"
python3 -m build

if [ ! -d "dist" ]; then
    echo -e "${RED}ERROR: Build failed - no dist directory created${NC}"
    exit 1
fi

echo -e "${GREEN}Build completed successfully!${NC}"
echo -e "${BLUE}Built packages:${NC}"
ls -la dist/

echo -e "${BLUE}Validating built packages...${NC}"

if ! python3 -c "import twine" &> /dev/null; then
    echo -e "${YELLOW}Installing twine using UV...${NC}"
    uv add --dev twine
fi

python3 -m twine check dist/*

echo -e "${BLUE}Package contents summary:${NC}"

WHEEL_FILE=$(ls dist/*.whl | head -1)
if [ -n "$WHEEL_FILE" ]; then
    echo -e "${BLUE}Wheel contents:${NC}"
    python3 -c "
import zipfile
import sys
with zipfile.ZipFile('$WHEEL_FILE', 'r') as z:
    files = z.namelist()
    total_files = len(files)
    ui_files = [f for f in files if 'ui/' in f]
    python_files = [f for f in files if f.endswith('.py')]

    print(f'  Total files: {total_files}')
    print(f'  Python files: {len(python_files)}')
    print(f'  UI files: {len(ui_files)}')

    if ui_files:
        print('  Sample UI files:')
        for f in ui_files[:5]:
            print(f'    {f}')
        if len(ui_files) > 5:
            print(f'    ... and {len(ui_files) - 5} more')
"
fi

echo -e "${BLUE}Package sizes:${NC}"
du -h dist/*

echo -e "${GREEN}Package build completed successfully!${NC}"
echo -e "${BLUE}Next steps:${NC}"
echo "  1. Test the package: pip install dist/*.whl"
echo "  2. Test on TestPyPI: python -m twine upload --repository testpypi dist/*"
echo "  3. Publish to PyPI: python -m twine upload --verbose dist/*"

echo -e "${BLUE}Pre-publish checklist:${NC}"

if [[ "$CURRENT_VERSION" == *"dev"* ]] || [[ "$CURRENT_VERSION" == *"rc"* ]]; then
    echo -e "${YELLOW}Development version detected: $CURRENT_VERSION${NC}"
fi

if [ -f "README.md" ]; then
    echo -e "${GREEN}README.md found${NC}"
else
    echo -e "${YELLOW}README.md not found${NC}"
fi

if [ -f "LICENSE" ]; then
    echo -e "${GREEN}LICENSE found${NC}"
else
    echo -e "${YELLOW}LICENSE not found${NC}"
fi

echo -e "${BLUE}UV Environment Status:${NC}"
if command -v uv &> /dev/null; then
    echo -e "${GREEN}UV available${NC}"
    if [ -f "uv.lock" ]; then
        echo -e "${GREEN}UV lock file found${NC}"
    fi
else
    echo -e "${YELLOW}UV not available (but build succeeded)${NC}"
fi

if command -v git &> /dev/null && [ -d ".git" ]; then
    if [ -z "$(git status --porcelain)" ]; then
        echo -e "${GREEN}Git repository is clean${NC}"
    else
        echo -e "${YELLOW}Git repository has uncommitted changes${NC}"
        echo "    Consider committing changes before publishing"
    fi
fi

echo -e "${GREEN}Ready for publishing with UV environment!${NC}"
