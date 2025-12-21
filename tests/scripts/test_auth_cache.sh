#!/bin/bash
# Test script to verify auth_cache table functionality

set -e

echo "=== Testing Auth Cache ==="
echo ""

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Check if table exists
echo -e "${BLUE}1. Checking if auth_cache table exists...${NC}"
kubectl exec -n postgres postgres-77f75d5877-5g4cc -- psql -U demo -d demo_noetl -c "\d noetl.auth_cache" > /dev/null 2>&1
if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Table exists${NC}"
else
    echo -e "${RED}✗ Table does not exist${NC}"
    exit 1
fi

# Show table schema
echo -e "\n${BLUE}2. Table schema:${NC}"
kubectl exec -n postgres postgres-77f75d5877-5g4cc -- psql -U demo -d demo_noetl -c "
SELECT column_name, data_type 
FROM information_schema.columns 
WHERE table_schema = 'noetl' AND table_name = 'auth_cache' 
ORDER BY ordinal_position;"

# Execute workflow
echo -e "\n${BLUE}3. Executing workflow to trigger caching...${NC}"
EXEC_ID=$(curl -s -X POST "http://localhost:30083/api/execution/execute" \
  -H "Content-Type: application/json" \
  -d '{"playbook_path": "api_integration/amadeus_ai_api/amadeus_ai_api", "payload": {"query": "Find flights from SFO to JFK on March 15, 2026"}}' \
  | jq -r '.execution_id')

if [ -z "$EXEC_ID" ] || [ "$EXEC_ID" = "null" ]; then
    echo -e "${RED}✗ Failed to start execution${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Execution started: $EXEC_ID${NC}"

# Wait for execution
echo -e "\n${BLUE}4. Waiting 30 seconds for workflow to process...${NC}"
for i in {1..30}; do
    echo -n "."
    sleep 1
done
echo ""

# Check cache entries
echo -e "\n${BLUE}5. Checking auth_cache entries:${NC}"
kubectl exec -n postgres postgres-77f75d5877-5g4cc -- psql -U demo -d demo_noetl -c "
SELECT 
    credential_name,
    credential_type,
    cache_type,
    scope_type,
    execution_id,
    created_at,
    accessed_at,
    access_count,
    CASE 
        WHEN expires_at > NOW() THEN 'valid'
        ELSE 'expired'
    END as status
FROM noetl.auth_cache 
WHERE created_at > NOW() - INTERVAL '5 minutes'
ORDER BY created_at DESC;"

# Count entries
COUNT=$(kubectl exec -n postgres postgres-77f75d5877-5g4cc -- psql -U demo -d demo_noetl -t -c "
SELECT COUNT(*) FROM noetl.auth_cache WHERE created_at > NOW() - INTERVAL '5 minutes';")

echo -e "\n${BLUE}6. Cache statistics:${NC}"
if [ "$COUNT" -gt 0 ]; then
    echo -e "${GREEN}✓ Found $COUNT cached credential(s)${NC}"
    
    # Show cache hits
    HITS=$(kubectl exec -n postgres postgres-77f75d5877-5g4cc -- psql -U demo -d demo_noetl -t -c "
    SELECT COALESCE(SUM(access_count), 0) FROM noetl.auth_cache WHERE created_at > NOW() - INTERVAL '5 minutes';")
    echo -e "${GREEN}✓ Total cache hits: $HITS${NC}"
else
    echo -e "${RED}✗ No cache entries found${NC}"
    echo -e "${RED}  This could mean:${NC}"
    echo -e "${RED}  - Workflow didn't use Secret Manager auth${NC}"
    echo -e "${RED}  - Caching code has an issue${NC}"
    echo -e "${RED}  - Workflow failed before reaching auth${NC}"
fi

# Check worker logs for cache activity
echo -e "\n${BLUE}7. Checking worker logs for cache activity:${NC}"
kubectl logs -n noetl -l app=noetl-worker --tail=1000 | grep -E "(Cached secret|Retrieved.*cache|AUTH:)" | tail -10

echo -e "\n${BLUE}=== Test Complete ===${NC}"
