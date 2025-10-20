#!/bin/bash
#
# Quick Retry Testing Script
# Demonstrates retry issue and provides temporary fix
#

set -e

SERVER_URL="http://localhost:8083"

echo "======================================"
echo "NoETL Retry Testing - Quick Fix"
echo "======================================"
echo

# Step 1: Check current queue status
echo "1. Checking queue status..."
DEAD_JOBS=$(curl -s "$SERVER_URL/api/queue?status=dead" | jq -r '.items | length')
echo "   Dead jobs in queue: $DEAD_JOBS"
echo

# Step 2: Explain the problem
echo "2. THE PROBLEM:"
echo "   Worker hard-codes retry=false when jobs fail"
echo "   Location: noetl/worker/worker.py:374"
echo "   Result: All failures become 'dead' status, never retry"
echo

# Step 3: Show the fix
echo "3. THE FIX:"
echo "   Edit noetl/worker/worker.py line 374"
echo "   "
echo "   CHANGE FROM:"
echo '   await client.post(f"{self.server_url}/queue/{queue_id}/fail", json={"retry": False})'
echo "   "
echo "   CHANGE TO:"
echo '   await client.post(f"{self.server_url}/queue/{queue_id}/fail", json={"retry": True, "retry_delay_seconds": 5})'
echo

# Step 4: Provide test command
echo "4. TO TEST RETRY (after applying fix):"
echo "   "
echo "   # Stop worker"
echo "   pkill -f 'python -m noetl.main worker'"
echo "   "
echo "   # Apply the fix above"
echo "   "
echo "   # Start worker"
echo "   cd /Users/kadyapam/projects/noetl/noetl"
echo "   .venv/bin/python -m noetl.main worker start > logs/worker.log 2>&1 &"
echo "   "
echo "   # Execute a failing playbook"
echo "   curl -X POST $SERVER_URL/api/executions/run \\"
echo "     -H 'Content-Type: application/json' \\"
echo "     -d '{\"path\": \"tests/retry/python_exception\"}'"
echo "   "
echo "   # Watch the queue (should see attempts increment)"
echo "   watch -n 1 'curl -s $SERVER_URL/api/queue | jq .items'"
echo

# Step 5: Database check
echo "5. TO CHECK RETRY IN DATABASE:"
echo "   "
echo "   psql -h localhost -p 54321 -U demo_user -d demo_noetl -c \\"
echo "     'SELECT queue_id, execution_id, status, attempts, max_attempts, available_at FROM noetl.queue ORDER BY queue_id DESC LIMIT 5'"
echo

echo "======================================"
echo "Documentation: docs/RETRY_TESTING_GUIDE.md"
echo "======================================"
