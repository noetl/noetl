# HTTP Pagination - Testing and Deployment Checklist

## Pre-Deployment Checklist

### Code Review
- [x] Config extraction in `noetl/tools/controller/iterator/config.py`
- [x] Pagination executor in `noetl/tools/controller/iterator/pagination.py`
- [x] Iterator executor delegation in `noetl/tools/controller/iterator/executor.py`
- [x] Async HTTP executor integration
- [x] Error handling for all edge cases
- [x] Logging at appropriate levels

### Testing Infrastructure
- [x] Mock server created (`tests/fixtures/servers/paginated_api.py`)
- [x] 5 test playbooks covering all scenarios
- [x] Test script with health checks
- [x] README documentation for tests

### Documentation
- [x] Design document (`documentation/docs/features/pagination_design.md`)
- [x] User guide (`documentation/docs/features/pagination.md`)
- [x] Quick reference (`documentation/docs/reference/http_pagination_quick_reference.md`)
- [x] Implementation summary (`documentation/docs/features/pagination_implementation_summary.md`)
- [x] Copilot instructions updated

## Deployment Steps

### 1. Build Docker Image
```bash
cd /Users/akuksin/projects/noetl/noetl
noetl build
```

Expected output:
- Image built successfully
- Tagged as `local/noetl:latest` or `local/noetl:YYYY-MM-DD-HH-MM`

### 2. Load Image to kind Cluster

The image is automatically loaded to the kind cluster during the build process.

Expected output:
- Image loaded into kind cluster
- Available for deployment

### 3. Update Deployment Manifests
```bash
# Update image tag in deployment
kubectl set image deployment/noetl-server noetl-server=local/noetl:latest -n noetl
kubectl set image deployment/noetl-worker noetl-worker=local/noetl:latest -n noetl
```

Or use noetl CLI:
```bash
noetl run automation/deployment/noetl-stack.yaml --set action=deploy
```

Expected output:
- Deployments updated
- Pods restarted with new image

### 4. Verify Deployment
```bash
# Check pod status
kubectl get pods -n noetl

# Check logs for errors
kubectl logs -l app=noetl-server -n noetl --tail=50
kubectl logs -l app=noetl-worker -n noetl --tail=50
```

Expected:
- All pods in `Running` state
- No error messages in logs
- Server responds to health checks

## Testing Steps

### 1. Start Mock Server
```bash
# In separate terminal
python tests/fixtures/servers/paginated_api.py 5555
```

Expected output:
```
Starting mock pagination API on port 5555
Total items: 35, Items per page: 10

Available endpoints:
  GET /api/v1/assessments?page=N&pageSize=M  - Page number pagination
  GET /api/v1/users?offset=N&limit=M         - Offset pagination
  GET /api/v1/events?cursor=TOKEN&limit=M    - Cursor pagination
  GET /api/v1/flaky?page=N&fail_on=2,3       - Retry testing
  GET /health                                - Health check
```

### 2. Verify Mock Server
```bash
curl http://localhost:5555/health
```

Expected: `{"status": "ok"}`

### 3. Run Test Suite
```bash
./tests/scripts/test_pagination.sh
```

Expected output:
```
Pagination Feature Test Suite
========================================

Checking mock server at localhost:5555...
Mock server is running

Checking NoETL API at http://localhost:8082/api...
NoETL API is accessible

Test 1: test_pagination_basic
Description: Page-number pagination with hasMore flag
Registering playbook...
Executing playbook...
Execution ID: 12345
Status: completed
✓ PASSED: test_pagination_basic

[... 4 more tests ...]

========================================
Test Summary
========================================
Tests run: 5
Tests passed: 5
Tests failed: 0

All pagination tests passed!
```

### 4. Manual Validation

Test individual endpoint:
```bash
# Register test playbook
curl -X POST http://localhost:8082/api/catalog/register \
  -H "Content-Type: application/json" \
  -d "{\"content\": $(cat tests/fixtures/playbooks/pagination/test_pagination_basic.yaml | jq -Rs .)}"

# Execute
curl -X POST http://localhost:8082/api/run/playbook \
  -H "Content-Type: application/json" \
  -d '{"path": "tests/pagination/basic"}'

# Check status (use execution_id from above)
curl http://localhost:8082/api/execution/{execution_id}/status
```

### 5. Check Logs
```bash
# Server logs
kubectl logs -l app=noetl-server -n noetl --tail=100 | grep PAGINATION

# Worker logs
kubectl logs -l app=noetl-worker -n noetl --tail=100 | grep PAGINATION
```

Expected log entries:
- `PAGINATION: Starting paginated execution with strategy=append`
- `PAGINATION: Iteration 0, attempt 1 succeeded`
- `PAGINATION: Iteration 0 complete, merged results`
- `PAGINATION: Stopping - continue_while evaluated to False at iteration 3`
- `PAGINATION: Completed 4 iterations, returning accumulated results`

## Validation Checklist

### Functional Tests
- [ ] Page number pagination works
- [ ] Offset pagination works
- [ ] Cursor pagination works
- [ ] Max iterations limit enforced
- [ ] Retry mechanism works with exponential backoff
- [ ] All 4 merge strategies work (append, extend, replace, collect)
- [ ] Variables accessible in expressions (response, iteration, accumulated)

### Error Handling
- [ ] Invalid `continue_while` expression fails gracefully
- [ ] Missing `merge_path` fails with clear error
- [ ] HTTP errors trigger retry
- [ ] Max retry reached fails with last error
- [ ] Infinite loop prevented by max_iterations

### Integration
- [ ] Works with existing iterator features
- [ ] Compatible with vars block
- [ ] Works with save blocks
- [ ] Integrates with retry directives
- [ ] Logs events properly

### Performance
- [ ] 35 items fetched in ~4 seconds (4 pages)
- [ ] Memory usage reasonable (< 100MB for 35 items)
- [ ] No memory leaks over multiple executions
- [ ] Retry backoff timing accurate

## Post-Deployment Tasks

### 1. Update Documentation Site
```bash
cd documentation
npm run build
# Deploy to docs site
```

### 2. Create Release Notes
- Add pagination feature to CHANGELOG.md
- Document breaking changes (none expected)
- Add migration guide for manual pagination users

### 3. Notify Users
- Announce feature in team channels
- Update examples repository
- Add to feature showcase

### 4. Monitor Production
- Watch for errors in production logs
- Monitor API response times
- Track pagination usage metrics

## Rollback Plan

If issues discovered:

### 1. Quick Rollback
```bash
# Revert to previous image
kubectl set image deployment/noetl-server noetl-server=local/noetl:previous-tag -n noetl
kubectl set image deployment/noetl-worker noetl-worker=local/noetl:previous-tag -n noetl
```

### 2. Disable Feature
Pagination only activates when `loop.pagination` block present. Users can:
- Remove pagination block from playbooks
- Revert to manual pagination loops
- No data loss (existing playbooks unaffected)

## Known Issues

None currently. Report issues to GitHub.

## Support

- Documentation: `documentation/docs/features/pagination.md`
- Examples: `tests/fixtures/playbooks/pagination/`
- Design: `documentation/docs/features/pagination_design.md`
- Slack: #noetl-support

## Success Criteria

Deployment successful if:
- [x] All 5 automated tests pass
- [ ] Manual validation passes
- [ ] No errors in production logs (24h)
- [ ] Users successfully adopt feature
- [ ] No performance degradation

## Sign-Off

- [ ] Developer: Code review complete
- [ ] Tester: All tests passing
- [ ] Technical Writer: Documentation reviewed
- [ ] Product Owner: Feature acceptance
- [ ] DevOps: Deployment verified
