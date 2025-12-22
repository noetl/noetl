# Quick Regression Test Commands

# 1. Start the regression test
curl -X POST http://localhost:8082/api/run/playbook \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/fixtures/playbooks/regression_test/master_regression_test"}' \
  | jq '{execution_id: .execution_id, status: .status}'

# Save the execution_id from above, then check status with:
# curl -X POST http://localhost:8082/api/postgres/execute \
#   -H "Content-Type: application/json" \
#   -d '{"query": "SELECT COUNT(DISTINCT node_name), COUNT(*), COUNT(CASE WHEN event_type='\''playbook_failed'\'' THEN 1 END) FROM noetl.event WHERE execution_id = YOUR_ID", "schema": "noetl"}' | jq '.result[0]'
