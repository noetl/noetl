#!/bin/bash

set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

echo -e "${BLUE}Building NoETL Package...${NC}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

if [ ! -f "pyproject.toml" ]; then
    echo -e "${RED}ERROR: pyproject.toml not found${NC}"
    exit 1
fi

echo -e "${BLUE}Cleaning previous builds...${NC}"
rm -rf dist/ build/ *.egg-info/
find . -name "*.pyc" -delete
find . -name "__pycache__" -type d -exec rm -rf {} + 2>/dev/null || true

echo -e "${BLUE}Building sdist and wheel...${NC}"
python3 -m build

echo -e "${GREEN}Build completed successfully!${NC}"
echo -e "${BLUE}Built packages:${NC}"
ls -la dist/

echo -e "${BLUE}Validating built packages...${NC}"
python3 -m twine check dist/*

echo -e "${GREEN}Ready for publishing!${NC}"
