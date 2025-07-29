#!/bin/bash

# NoETL Amadeus API Playbook Execution Script
# This script registers and executes the Amadeus API integration playbook
#
# Usage: ./examples/amadeus/run_amadeus_api.sh [port] [query]
#
# Examples:
#   ./examples/amadeus/run_amadeus_api.sh
#   ./examples/amadeus/run_amadeus_api.sh 8080
#   ./examples/amadeus/run_amadeus_api.sh 8080 "I want a flight from LAX to NYC on December 25, 2025"

set -e  # Exit on any error

# Default values
DEFAULT_PORT=8080
DEFAULT_QUERY="I want a one-way flight from SFO to JFK on September 15, 2025 for 1 adult"

# Parse command line arguments
PORT=${1:-$DEFAULT_PORT}
QUERY=${2:-"$DEFAULT_QUERY"}

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}======================================${NC}"
echo -e "${BLUE}  NoETL Amadeus API Playbook Runner  ${NC}"
echo -e "${BLUE}======================================${NC}"
echo ""
echo -e "${YELLOW}Configuration:${NC}"
echo -e "  Port: ${PORT}"
echo -e "  Query: ${QUERY}"
echo ""

# Get the directory where the script is located
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PLAYBOOK_FILE="$SCRIPT_DIR/amadeus_api_playbook.yaml"

# Check if playbook file exists
if [ ! -f "$PLAYBOOK_FILE" ]; then
    echo -e "${RED}Error: Playbook file not found: $PLAYBOOK_FILE${NC}"
    exit 1
fi

echo -e "${YELLOW}Step 1: Registering Amadeus API playbook...${NC}"
echo "Command: noetl playbooks --register $PLAYBOOK_FILE --port $PORT"
echo ""

if noetl playbooks --register "$PLAYBOOK_FILE" --port "$PORT"; then
    echo -e "${GREEN}[SUCCESS] Playbook registered successfully.${NC}"
    echo ""
else
    echo -e "${RED}[FAILED] Failed to register playbook${NC}"
    exit 1
fi

echo -e "${YELLOW}Step 2: Executing Amadeus API playbook...${NC}"
echo "Command: noetl playbooks --execute --path \"amadeus/amadeus_api\" --payload '{\"query\": \"$QUERY\"}' --port $PORT"
echo ""

if noetl playbooks --execute --path "amadeus/amadeus_api" --payload "{\"query\": \"$QUERY\"}" --port "$PORT"; then
    echo -e "${GREEN}[SUCCESS] Playbook executed successfully.${NC}"
    echo ""
    echo -e "${BLUE}Check your PostgreSQL database for results:${NC}"
    echo -e "  - ${YELLOW}amadeus_ai_events${NC} table: API call events and logs"
    echo -e "  - ${YELLOW}api_results${NC} table: Final natural language results"
    echo ""
else
    echo -e "${RED}[FAILED] Failed to execute playbook${NC}"
    exit 1
fi

echo -e "${GREEN}[COMPLETE] Amadeus API workflow completed successfully.${NC}"
echo ""
echo -e "${BLUE}Next steps:${NC}"
echo -e "  1. Query the database tables to see the results"
echo -e "  2. Check the NoETL logs for detailed execution information"
echo -e "  3. Try different travel queries by running:"
echo -e "     ${YELLOW}./examples/amadeus/run_amadeus_api.sh $PORT \"Your travel query here\"${NC}"
