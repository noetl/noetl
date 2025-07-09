#!/bin/bash
# Builds the React UI from ui-src and integrates the assets into the noetl Python package.

set -e

echo "🔨 Building and Integrating NoETL UI..."

# --- Color definitions ---
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

# --- Path setup ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UI_SRC_DIR="$PROJECT_ROOT/ui-src"
# The final destination for packaged assets
UI_DEST_DIR="$PROJECT_ROOT/noetl/ui"

echo -e "${BLUE}UI source: $UI_SRC_DIR${NC}"
echo -e "${BLUE}UI destination: $UI_DEST_DIR${NC}"

# --- 1. Build Frontend Assets with Vite ---
cd "$UI_SRC_DIR"

echo -e "${BLUE}Installing UI dependencies...${NC}"
npm install --silent

echo -e "${BLUE}Building UI for production...${NC}"
npm run build

# --- 2. Integrate Assets into Python Package ---
cd "$PROJECT_ROOT"
echo -e "${BLUE}Copying built assets to $UI_DEST_DIR...${NC}"

# Clean destination and recreate structure
rm -rf "$UI_DEST_DIR"
mkdir -p "$UI_DEST_DIR/static/assets"
mkdir -p "$UI_DEST_DIR/templates"

# Copy the generated HTML files to the templates directory
cp "$UI_SRC_DIR/dist/"*.html "$UI_DEST_DIR/templates/"

# Copy the generated JS and CSS assets
cp -r "$UI_SRC_DIR/dist/assets/"* "$UI_DEST_DIR/static/assets/"

# Ensure all UI directories are valid Python packages
find "$UI_DEST_DIR" -type d -exec touch {}/__init__.py \;

echo -e "${GREEN}UI build completed and assets integrated successfully!${NC}"
echo -e "${GREEN}The 'noetl' package is now ready to be built with the UI included.${NC}"
