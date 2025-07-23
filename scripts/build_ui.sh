#!/bin/bash
# Builds the React UI from ui-src and integrates the assets into the noetl Python package.
# Supports both development and production modes with configurable FastAPI connection.

set -e

# --- Default Configuration ---
FASTAPI_HOST="localhost"
FASTAPI_PORT="8000"
UI_DEV_PORT="3000"
MODE="build"
SKIP_FASTAPI_CHECK="false"

# --- Usage function ---
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Options:"
    echo "  -h, --help              Show this help message"
    echo "  -m, --mode MODE         Mode: 'build' (default), 'dev', 'dev-with-api', or 'dev-with-server'"
    echo "  -H, --host HOST         FastAPI host (default: localhost)"
    echo "  -p, --port PORT         FastAPI port (default: 8000)"
    echo "  -u, --ui-port PORT      UI development port (default: 3000)"
    echo "  -s, --skip-api-check    Skip FastAPI connection check"
    echo "  --with-server           Start NoETL server together with UI (same as -m dev-with-server)"
    echo ""
    echo "Examples:"
    echo "  $0                                    # Build for production"
    echo "  $0 -m dev                            # Start development server"
    echo "  $0 -m dev-with-api -p 8080           # Start dev server with FastAPI on port 8080"
    echo "  $0 --with-server -p 8080             # Start both UI and NoETL server"
    echo "  $0 -m build -H api.example.com -p 80 # Build for production with custom API endpoint"
}

# --- Parse command line arguments ---
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            exit 0
            ;;
        -m|--mode)
            MODE="$2"
            shift 2
            ;;
        -H|--host)
            FASTAPI_HOST="$2"
            shift 2
            ;;
        -p|--port)
            FASTAPI_PORT="$2"
            shift 2
            ;;
        -u|--ui-port)
            UI_DEV_PORT="$2"
            shift 2
            ;;
        -s|--skip-api-check)
            SKIP_FASTAPI_CHECK="true"
            shift
            ;;
        --with-server)
            MODE="dev-with-server"
            shift
            ;;
        *)
            echo "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

echo "🔨 Building and Integrating NoETL UI..."

# --- Color definitions ---
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

# --- Path setup ---
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" &> /dev/null && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
UI_SRC_DIR="$PROJECT_ROOT/ui-src"
UI_DEST_DIR="$PROJECT_ROOT/noetl/ui"

echo -e "${BLUE}UI source: $UI_SRC_DIR${NC}"
echo -e "${BLUE}UI destination: $UI_DEST_DIR${NC}"
echo -e "${BLUE}Mode: $MODE${NC}"
echo -e "${BLUE}FastAPI endpoint: http://$FASTAPI_HOST:$FASTAPI_PORT${NC}"

# --- FastAPI Connection Check ---
check_fastapi() {
    if [[ "$SKIP_FASTAPI_CHECK" == "true" ]]; then
        echo -e "${YELLOW}Skipping FastAPI connection check...${NC}"
        return 0
    fi

    echo -e "${BLUE}Checking FastAPI connection...${NC}"
    if curl -s -f "http://$FASTAPI_HOST:$FASTAPI_PORT/health" > /dev/null 2>&1; then
        echo -e "${GREEN}✓ FastAPI is running on http://$FASTAPI_HOST:$FASTAPI_PORT${NC}"
        return 0
    else
        echo -e "${RED}✗ FastAPI is not accessible on http://$FASTAPI_HOST:$FASTAPI_PORT${NC}"
        echo -e "${YELLOW}To start FastAPI locally, run:${NC}"
        echo -e "${YELLOW}  cd $PROJECT_ROOT && python -m noetl.main server --port $FASTAPI_PORT${NC}"
        echo -e "${YELLOW}Or use --skip-api-check to bypass this check${NC}"
        return 1
    fi
}

# --- Generate Vite Configuration ---
generate_vite_config() {
    local config_file="$UI_SRC_DIR/vite.config.js"
    local fastapi_url="http://$FASTAPI_HOST:$FASTAPI_PORT"

    cat > "$config_file" << EOF
import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vitejs.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist',
    sourcemap: true,
  },
  server: {
    port: $UI_DEV_PORT,
    proxy: {
      '/api': '$fastapi_url',
      '/health': '$fastapi_url',
    }
  },
  define: {
    __FASTAPI_URL__: JSON.stringify('$fastapi_url')
  }
})
EOF
    echo -e "${GREEN}✓ Generated Vite config with FastAPI endpoint: $fastapi_url${NC}"
}

# --- Update API Service Configuration ---
update_api_config() {
    local api_file="$UI_SRC_DIR/src/services/api.ts"
    local fastapi_url="http://$FASTAPI_HOST:$FASTAPI_PORT"

    # Create a backup if the file exists
    if [[ -f "$api_file" ]]; then
        cp "$api_file" "$api_file.backup"
    fi

    # Update the API base URL configuration
    sed -i.tmp "s|const API_BASE_URL = process.env.NODE_ENV === 'development' ? '/api' : '/api';|const API_BASE_URL = process.env.NODE_ENV === 'development' ? '$fastapi_url/api' : '/api';|g" "$api_file"
    rm -f "$api_file.tmp"

    echo -e "${GREEN}✓ Updated API configuration for FastAPI endpoint: $fastapi_url${NC}"
}

# --- Main execution based on mode ---
cd "$UI_SRC_DIR"

case $MODE in
    "build")
        echo -e "${BLUE}Building UI for production...${NC}"

        # Check FastAPI connection
        if ! check_fastapi; then
            echo -e "${YELLOW}Warning: FastAPI not accessible. Continuing with build...${NC}"
        fi

        # Generate configuration
        generate_vite_config
        update_api_config

        # Install dependencies and build
        echo -e "${BLUE}Installing UI dependencies...${NC}"
        npm install --silent

        echo -e "${BLUE}Building UI for production...${NC}"
        npm run build

        # Integrate assets into Python package
        cd "$PROJECT_ROOT"
        echo -e "${BLUE}Copying built assets to $UI_DEST_DIR...${NC}"

        # Remove old build and copy new build
        rm -rf "$UI_DEST_DIR/build"
        cp -r "$UI_SRC_DIR/dist" "$UI_DEST_DIR/build"

        # Ensure __init__.py exists for Python package discovery
        find "$UI_DEST_DIR" -type d -exec touch {}/__init__.py \;

        echo -e "${GREEN}✓ UI build completed and assets integrated successfully!${NC}"
        echo -e "${GREEN}✓ The 'noetl' package is now ready to be built with the UI included.${NC}"
        ;;

    "dev")
        echo -e "${BLUE}Starting UI development server...${NC}"

        # Generate configuration
        generate_vite_config
        update_api_config

        # Install dependencies
        echo -e "${BLUE}Installing UI dependencies...${NC}"
        npm install --silent

        echo -e "${GREEN}Starting development server on http://localhost:$UI_DEV_PORT${NC}"
        echo -e "${YELLOW}Note: Make sure FastAPI is running on http://$FASTAPI_HOST:$FASTAPI_PORT${NC}"

        # Start development server
        npm run dev
        ;;

    "dev-with-api")
        echo -e "${BLUE}Starting UI development server with FastAPI check...${NC}"

        # Check FastAPI connection
        if ! check_fastapi; then
            echo -e "${RED}Error: FastAPI must be running for dev-with-api mode${NC}"
            exit 1
        fi

        # Generate configuration
        generate_vite_config
        update_api_config

        # Install dependencies
        echo -e "${BLUE}Installing UI dependencies...${NC}"
        npm install --silent

        echo -e "${GREEN}Starting development server on http://localhost:$UI_DEV_PORT${NC}"
        echo -e "${GREEN}Connected to FastAPI on http://$FASTAPI_HOST:$FASTAPI_PORT${NC}"

        # Start development server
        npm run dev
        ;;

    "dev-with-server")
        echo -e "${BLUE}Starting UI development server with NoETL server...${NC}"

        # Generate configuration
        generate_vite_config
        update_api_config

        # Install dependencies
        echo -e "${BLUE}Installing UI dependencies...${NC}"
        npm install --silent

        # Start NoETL server in the background
        echo -e "${GREEN}Starting NoETL server on http://$FASTAPI_HOST:$FASTAPI_PORT...${NC}"
        cd "$PROJECT_ROOT"
        nohup python -m noetl.main server --host "$FASTAPI_HOST" --port "$FASTAPI_PORT" > noetl_server.log 2>&1 &
        NOETL_SERVER_PID=$!

        # Store the PID for cleanup
        echo $NOETL_SERVER_PID > noetl_server.pid

        # Give the server some time to start
        sleep 3

        # Check if server started successfully
        if ! check_fastapi; then
            echo -e "${RED}Error: NoETL server failed to start${NC}"
            kill $NOETL_SERVER_PID 2>/dev/null || true
            rm -f noetl_server.pid
            exit 1
        fi

        echo -e "${GREEN}✓ NoETL server started successfully!${NC}"
        echo -e "${GREEN}Starting UI development server on http://localhost:$UI_DEV_PORT${NC}"
        echo -e "${GREEN}Connected to NoETL server on http://$FASTAPI_HOST:$FASTAPI_PORT${NC}"
        echo -e "${YELLOW}NoETL server logs: tail -f noetl_server.log${NC}"
        echo -e "${YELLOW}To stop NoETL server: kill \$(cat noetl_server.pid)${NC}"

        # Cleanup function
        cleanup() {
            echo -e "${YELLOW}Stopping NoETL server...${NC}"
            if [ -f noetl_server.pid ]; then
                kill $(cat noetl_server.pid) 2>/dev/null || true
                rm -f noetl_server.pid
            fi
            exit 0
        }

        # Set trap to cleanup on script exit
        trap cleanup EXIT INT TERM

        # Start development server
        cd "$UI_SRC_DIR"
        npm run dev
        ;;

    *)
        echo -e "${RED}Error: Invalid mode '$MODE'. Use 'build', 'dev', 'dev-with-api', or 'dev-with-server'${NC}"
        usage
        exit 1
        ;;
esac
