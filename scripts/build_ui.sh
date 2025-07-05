#!/bin/bash
# Build React UI for NoETL package

set -e

echo "🔨 Building NoETL React UI..."

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UI_SRC_DIR="$PROJECT_ROOT/ui-src"
UI_DIST_DIR="$PROJECT_ROOT/ui"

echo -e "${BLUE}Project root: $PROJECT_ROOT${NC}"
echo -e "${BLUE}UI source: $UI_SRC_DIR${NC}"
echo -e "${BLUE}UI destination: $UI_DIST_DIR${NC}"

if [ ! -d "$UI_SRC_DIR" ]; then
    echo -e "${YELLOW}Warning: UI source directory not found at $UI_SRC_DIR${NC}"
    echo -e "${YELLOW}Checking for existing built UI in $UI_DIST_DIR${NC}"

    if [ -d "$UI_DIST_DIR/static" ] && [ "$(ls -A $UI_DIST_DIR/static)" ]; then
        echo -e "${GREEN}Using existing UI build${NC}"
        exit 0
    else
        echo -e "${RED}No UI source or built UI found${NC}"
        echo -e "${YELLOW}Creating minimal UI structure...${NC}"
        mkdir -p "$UI_DIST_DIR/static/css"
        mkdir -p "$UI_DIST_DIR/static/js"
        mkdir -p "$UI_DIST_DIR/templates"
        cat > "$UI_DIST_DIR/templates/index.html" << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NoETL Dashboard</title>
    <link href="https://cdn.jsdelivr.net/npm/antd@5.12.8/dist/reset.css" rel="stylesheet">
    <link href="/static/css/main.css" rel="stylesheet">
</head>
<body>
    <div id="root">
        <div style="padding: 20px; text-align: center;">
            <h1>NoETL Dashboard</h1>
            <p>Welcome to NoETL - Not Only ETL Framework</p>
            <div id="app"></div>
        </div>
    </div>
    <script src="https://unpkg.com/react@18/umd/react.production.min.js"></script>
    <script src="https://unpkg.com/react-dom@18/umd/react-dom.production.min.js"></script>
    <script src="https://cdn.jsdelivr.net/npm/antd@5.12.8/dist/antd.min.js"></script>
    <script src="/static/js/main.js"></script>
</body>
</html>
EOF
        cat > "$UI_DIST_DIR/static/css/main.css" << 'EOF'
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
    margin: 0;
    padding: 0;
    background-color: #f5f5f5;
}

.container {
    max-width: 1200px;
    margin: 0 auto;
    padding: 20px;
}

.header {
    background: #001529;
    color: white;
    padding: 16px 24px;
    margin-bottom: 24px;
}

.content {
    background: white;
    padding: 24px;
    border-radius: 6px;
    box-shadow: 0 1px 3px rgba(0,0,0,0.1);
}
EOF
        cat > "$UI_DIST_DIR/static/js/main.js" << 'EOF'
// NoETL Dashboard Basic UI
(function() {
    'use strict';

    const { useState, useEffect } = React;
    const { Button, Card, Typography, Space, Layout } = antd;
    const { Title, Paragraph } = Typography;
    const { Header, Content } = Layout;

    function NoETLDashboard() {
        const [status, setStatus] = useState('Ready');

        useEffect(() => {
            // Check server status
            fetch('/api/health')
                .then(response => response.json())
                .then(data => setStatus('Connected'))
                .catch(() => setStatus('Disconnected'));
        }, []);

        return React.createElement(Layout, { style: { minHeight: '100vh' } },
            React.createElement(Header, { style: { background: '#001529' } },
                React.createElement(Title, {
                    level: 2,
                    style: { color: 'white', margin: '16px 0' }
                }, 'NoETL Dashboard')
            ),
            React.createElement(Content, { style: { padding: '24px' } },
                React.createElement(Space, { direction: 'vertical', size: 'large', style: { width: '100%' } },
                    React.createElement(Card, { title: 'Server Status' },
                        React.createElement(Paragraph, null, `Status: ${status}`)
                    ),
                    React.createElement(Card, { title: 'Quick Actions' },
                        React.createElement(Space, null,
                            React.createElement(Button, { type: 'primary' }, 'View Playbooks'),
                            React.createElement(Button, null, 'Run Workflow'),
                            React.createElement(Button, null, 'View Logs')
                        )
                    )
                )
            )
        );
    }

    // Render the app
    const container = document.getElementById('app');
    if (container) {
        const root = ReactDOM.createRoot(container);
        root.render(React.createElement(NoETLDashboard));
    }
})();
EOF

        echo -e "${GREEN}Created minimal UI structure${NC}"
        exit 0
    fi
fi

if ! command -v node &> /dev/null; then
    echo -e "${RED}Node.js is not installed. Please install Node.js 18+ to build the UI.${NC}"
    exit 1
fi

if ! command -v npm &> /dev/null; then
    echo -e "${RED}npm is not installed. Please install npm to build the UI.${NC}"
    exit 1
fi

cd "$UI_SRC_DIR"

echo -e "${BLUE}Installing UI dependencies...${NC}"
npm install

echo -e "${BLUE}Building UI for production...${NC}"
npm run build

if [ ! -d "build" ] && [ ! -d "dist" ]; then
    echo -e "${RED}UI build failed. No build/dist directory found.${NC}"
    exit 1
fi

BUILD_OUTPUT_DIR=""
if [ -d "build" ]; then
    BUILD_OUTPUT_DIR="build"
elif [ -d "dist" ]; then
    BUILD_OUTPUT_DIR="dist"
fi

echo -e "${BLUE}Copying UI assets to package directory...${NC}"
mkdir -p "$UI_DIST_DIR/static"
mkdir -p "$UI_DIST_DIR/templates"

if [ -d "$BUILD_OUTPUT_DIR/static" ]; then
    cp -r "$BUILD_OUTPUT_DIR/static/"* "$UI_DIST_DIR/static/"
else
    cp -r "$BUILD_OUTPUT_DIR/"* "$UI_DIST_DIR/static/"
fi

if [ -f "$BUILD_OUTPUT_DIR/index.html" ]; then
    cp "$BUILD_OUTPUT_DIR/index.html" "$UI_DIST_DIR/templates/"
else
    echo -e "${YELLOW}No index.html found, creating template...${NC}"
    cat > "$UI_DIST_DIR/templates/index.html" << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>NoETL Dashboard</title>
    <link href="/static/css/main.css" rel="stylesheet">
</head>
<body>
    <div id="root"></div>
    <script src="/static/js/main.js"></script>
</body>
</html>
EOF
fi

if [ -f "$UI_DIST_DIR/templates/index.html" ]; then
    sed -i.bak 's|href="./static/|href="/static/|g' "$UI_DIST_DIR/templates/index.html"
    sed -i.bak 's|src="./static/|src="/static/|g' "$UI_DIST_DIR/templates/index.html"
    sed -i.bak 's|href="static/|href="/static/|g' "$UI_DIST_DIR/templates/index.html"
    sed -i.bak 's|src="static/|src="/static/|g' "$UI_DIST_DIR/templates/index.html"
    rm -f "$UI_DIST_DIR/templates/index.html.bak"
fi

if [ ! -f "$UI_DIST_DIR/__init__.py" ]; then
    cat > "$UI_DIST_DIR/__init__.py" << 'EOF'
"""
NoETL React UI Package

This package contains the built React UI components for the NoETL dashboard.
The UI is served by the FastAPI server and provides a web interface for
managing playbooks, workflows, and monitoring execution.
"""

import os
from pathlib import Path

# Get the UI package directory
UI_DIR = Path(__file__).parent

# Paths to UI assets
STATIC_DIR = UI_DIR / "static"
TEMPLATES_DIR = UI_DIR / "templates"

def get_static_dir():
    """Get the path to static assets directory."""
    return str(STATIC_DIR)

def get_templates_dir():
    """Get the path to templates directory."""
    return str(TEMPLATES_DIR)

def is_ui_available():
    """Check if UI assets are available."""
    return STATIC_DIR.exists() and TEMPLATES_DIR.exists()

__all__ = ['get_static_dir', 'get_templates_dir', 'is_ui_available']
EOF
fi

echo -e "${GREEN}UI build completed successfully!${NC}"
echo -e "${BLUE}Build summary:${NC}"
echo -e "  Static files: $(find "$UI_DIST_DIR/static" -type f | wc -l) files"
echo -e "  Template files: $(find "$UI_DIST_DIR/templates" -type f | wc -l) files"
echo -e "  Total size: $(du -sh "$UI_DIST_DIR" | cut -f1)"

echo -e "${GREEN}UI is ready for packaging!${NC}"
