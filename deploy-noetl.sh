#!/bin/bash

# NoETL Deployment Script

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

MODE="default"
CLEANUP=false
LOGS=false

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

usage() {
    echo "Usage: $0 [OPTIONS]"
    echo ""
    echo "Deploy NoETL with different server configurations:"
    echo ""
    echo "Options:"
    echo "  -m, --mode MODE       Deployment mode: default, uvicorn, gunicorn, dev (default: default)"
    echo "  -c, --cleanup         Clean up existing containers before deployment"
    echo "  -l, --logs            Show logs after deployment"
    echo "  -h, --help            Show this help message"
    echo ""
    echo "Examples:"
    echo "  $0                    # Deploy with default uvicorn server"
    echo "  $0 -m gunicorn        # Deploy with gunicorn server (production)"
    echo "  $0 -m dev -l          # Deploy development server with live reload and show logs"
    echo "  $0 -c -m uvicorn      # Clean up and deploy with explicit uvicorn"
    echo ""
    echo "Available endpoints after deployment:"
    echo "  - Default:  http://localhost:8080"
    echo "  - Uvicorn:  http://localhost:8081 (profile: uvicorn)"
    echo "  - Gunicorn: http://localhost:8082 (profile: gunicorn)"
    echo "  - Dev:      http://localhost:8083 (profile: dev)"
}

log() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

cleanup() {
    log "Cleaning up existing NoETL containers..."
    docker-compose down --remove-orphans || true
    docker system prune -f --volumes || true
    success "Cleanup completed"
}

deploy() {
    local mode=$1

    log "Deploying NoETL in $mode mode..."

    case $mode in
        "default")
            docker-compose up -d postgres noetl
            ;;
        "uvicorn")
            docker-compose --profile uvicorn up -d postgres noetl-uvicorn
            ;;
        "gunicorn")
            docker-compose --profile gunicorn up -d postgres noetl-gunicorn
            ;;
        "dev")
            docker-compose --profile dev up -d postgres noetl-dev
            ;;
        *)
            error "Unknown mode: $mode"
            usage
            exit 1
            ;;
    esac

    log "Waiting for services to be ready..."
    sleep 10

    case $mode in
        "default")
            check_service "http://localhost:8080/health" "NoETL Default Server"
            ;;
        "uvicorn")
            check_service "http://localhost:8081/health" "NoETL Uvicorn Server"
            ;;
        "gunicorn")
            check_service "http://localhost:8082/health" "NoETL Gunicorn Server"
            ;;
        "dev")
            check_service "http://localhost:8083/health" "NoETL Development Server"
            ;;
    esac
}

check_service() {
    local url=$1
    local name=$2
    local retries=12
    local count=0

    log "Checking $name at $url..."

    while [ $count -lt $retries ]; do
        if curl -s -f "$url" > /dev/null 2>&1; then
            success "$name is running and healthy!"
            return 0
        fi

        count=$((count + 1))
        log "Attempt $count/$retries failed, retrying in 5 seconds..."
        sleep 5
    done

    error "$name health check failed after $retries attempts"
    error "Check the logs with: docker-compose logs"
    return 1
}

show_logs() {
    local mode=$1

    case $mode in
        "default")
            docker-compose logs -f noetl
            ;;
        "uvicorn")
            docker-compose logs -f noetl-uvicorn
            ;;
        "gunicorn")
            docker-compose logs -f noetl-gunicorn
            ;;
        "dev")
            docker-compose logs -f noetl-dev
            ;;
    esac
}

while [[ $# -gt 0 ]]; do
    case $1 in
        -m|--mode)
            MODE="$2"
            shift 2
            ;;
        -c|--cleanup)
            CLEANUP=true
            shift
            ;;
        -l|--logs)
            LOGS=true
            shift
            ;;
        -h|--help)
            usage
            exit 0
            ;;
        *)
            error "Unknown option: $1"
            usage
            exit 1
            ;;
    esac
done

# Validate mode
case $MODE in
    "default"|"uvicorn"|"gunicorn"|"dev")
        ;;
    *)
        error "Invalid mode: $MODE"
        usage
        exit 1
        ;;
esac

log "Starting NoETL deployment with mode: $MODE"

if [ "$CLEANUP" = true ]; then
    cleanup
fi

deploy "$MODE"

if [ "$LOGS" = true ]; then
    log "Showing logs for $MODE deployment (Press Ctrl+C to exit)..."
    show_logs "$MODE"
fi

success "Deployment completed successfully!"
log "NoETL is running in $MODE mode"

case $MODE in
    "default")
        log "Access the server at: http://localhost:8080"
        ;;
    "uvicorn")
        log "Access the server at: http://localhost:8081"
        ;;
    "gunicorn")
        log "Access the server at: http://localhost:8082"
        ;;
    "dev")
        log "Access the development server at: http://localhost:8083"
        log "Development mode includes live reload for code changes"
        ;;
esac

log "Use 'docker-compose logs <service-name>' to view logs"
log "Use 'docker-compose down' to stop all services"
