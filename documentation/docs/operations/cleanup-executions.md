---
sidebar_position: 1
---

# Cleanup Stuck Executions

NoETL provides a mechanism to clean up stuck executions that may occur due to server crashes, network failures, or other interruptions. This guide explains how to identify and cancel stuck executions using both the CLI and REST API.

## What Are Stuck Executions?

An execution is considered "stuck" when it lacks a terminal event in the event table. Terminal events include:
- `playbook.completed` - Successful completion
- `playbook.failed` - Failed execution
- `execution.cancelled` - Manually cancelled

Executions without these terminal events remain in a `RUNNING` state indefinitely and can clutter the system.

## Common Causes

- Server crashes during execution
- Network interruptions between server and workers
- Worker pod restarts in Kubernetes
- Database connection failures during event reporting
- Manual container/pod deletion

## Cleanup Methods

### CLI Command

The NoETL CLI provides a `cleanup` command to identify and cancel stuck executions:

```bash
# Preview stuck executions (dry-run mode)
noetl cleanup --dry-run

# Cancel stuck executions older than 5 minutes (default)
noetl cleanup

# Cancel executions older than 10 minutes
noetl cleanup --older-than-minutes 10

# Dry-run with custom age threshold
noetl cleanup --older-than-minutes 15 --dry-run

# JSON output for automation
noetl cleanup --json
```

#### Parameters

- `--older-than-minutes`: Minimum age in minutes for executions to be cancelled (default: 5, minimum: 1)
- `--dry-run`: Preview mode - shows what would be cancelled without actually cancelling
- `--json`: Output results in JSON format for scripting/automation

#### Example Output

```
============================================================
[DRY RUN] Cleanup Stuck Executions
============================================================
Older than:    5 minutes
Found:         3 stuck execution(s)

[DRY RUN] Would cancel 3 stuck executions older than 5 minutes

Execution IDs:
  - 123
  - 124
  - 125

Note: Run without --dry-run to actually cancel these executions
============================================================
```

### REST API

The cleanup functionality is also available via the REST API:

#### Endpoint

```http
POST /api/executions/cleanup
Content-Type: application/json
```

#### Request Body

```json
{
  "older_than_minutes": 5,
  "dry_run": false
}
```

#### Response

```json
{
  "cancelled_count": 3,
  "execution_ids": [123, 124, 125],
  "message": "Cancelled 3 stuck executions older than 5 minutes"
}
```

#### Example with curl

```bash
# Dry-run
curl -X POST http://localhost:8082/api/executions/cleanup \
  -H "Content-Type: application/json" \
  -d '{"older_than_minutes": 5, "dry_run": true}'

# Actual cleanup
curl -X POST http://localhost:8082/api/executions/cleanup \
  -H "Content-Type: application/json" \
  -d '{"older_than_minutes": 5, "dry_run": false}'
```

## Best Practices

### Regular Monitoring

Check for stuck executions periodically:

```bash
# Check daily for stuck executions
noetl cleanup --older-than-minutes 60 --dry-run
```

### Conservative Age Threshold

Use appropriate age thresholds to avoid cancelling legitimately long-running executions:

- **Default (5 minutes)**: Suitable for most playbooks
- **10-15 minutes**: For playbooks with long-running tasks
- **60+ minutes**: For ETL pipelines or batch processing jobs

### Automation

Integrate cleanup into monitoring workflows:

```bash
#!/bin/bash
# cleanup-stuck-executions.sh

# Check for stuck executions older than 10 minutes
RESULT=$(noetl cleanup --older-than-minutes 10 --json)
COUNT=$(echo $RESULT | jq -r '.cancelled_count')

if [ "$COUNT" -gt 0 ]; then
    echo "Cancelled $COUNT stuck executions"
    # Send notification
    echo $RESULT | jq -r '.execution_ids[]' | while read id; do
        echo "  - Execution ID: $id"
    done
fi
```

### Dry-Run First

Always use `--dry-run` to preview changes before executing:

```bash
# Step 1: Preview
noetl cleanup --older-than-minutes 5 --dry-run

# Step 2: Review output

# Step 3: Execute
noetl cleanup --older-than-minutes 5
```

## Preventing Stuck Executions

### Auto-Resume Configuration

NoETL includes an auto-resume mechanism that marks interrupted executions as cancelled on server restart. This is configured in the server settings:

```python
# noetl/server/auto_resume.py
RESUME_WINDOW_MINUTES = 5  # Only check last 5 minutes
```

### Monitoring

Monitor execution health using the events API:

```bash
# Query running executions
noetl query "SELECT execution_id, created_at FROM noetl.event WHERE event_type = 'execution.started' AND execution_id NOT IN (SELECT execution_id FROM noetl.event WHERE event_type IN ('playbook.completed', 'playbook.failed', 'execution.cancelled'))" --schema noetl
```

### Database Backup

Regularly backup the NoETL event table to recover from data corruption:

```bash
pg_dump -h localhost -p 54321 -U noetl -d noetl -t event > event_backup.sql
```

## Troubleshooting

### No Stuck Executions Found

If cleanup reports 0 executions but the UI shows stuck jobs:

1. Check the actual database state:
```bash
noetl query "SELECT execution_id, MAX(event_id) as max_event, MAX(event_type) as last_event FROM noetl.event GROUP BY execution_id HAVING MAX(event_type) NOT IN ('playbook.completed', 'playbook.failed', 'execution.cancelled')"
```

2. Verify server connectivity:
```bash
curl http://localhost:8082/api/health
```

3. Check server logs:
```bash
kubectl logs -n noetl -l app=noetl-server
```

### Cleanup Fails

If cleanup command fails:

1. Verify API endpoint is accessible:
```bash
curl -X POST http://localhost:8082/api/executions/cleanup \
  -H "Content-Type: application/json" \
  -d '{"older_than_minutes": 5, "dry_run": true}'
```

2. Check server logs for errors
3. Verify database connectivity
4. Ensure sufficient permissions for event table writes

### Manual Cleanup

If automated cleanup fails, manually insert cancellation events:

```sql
-- Find stuck executions
SELECT execution_id, MAX(event_id) as last_event_id
FROM noetl.event
GROUP BY execution_id
HAVING MAX(event_type) NOT IN ('playbook.completed', 'playbook.failed', 'execution.cancelled');

-- Insert cancellation event
INSERT INTO noetl.event (execution_id, catalog_id, event_id, event_type, status, context, created_at)
SELECT 
    execution_id,
    catalog_id,
    (SELECT COALESCE(MAX(event_id), 0) + 1 FROM noetl.event WHERE execution_id = 123) as event_id,
    'execution.cancelled'::noetl.event_type,
    'cancelled'::noetl.execution_status,
    '{"reason": "Manual cleanup", "cancelled_at": "'||NOW()||'"}'::jsonb,
    NOW()
FROM noetl.event
WHERE execution_id = 123
LIMIT 1;
```

## API Reference

### Request Schema

```typescript
interface CleanupStuckExecutionsRequest {
  older_than_minutes: number;  // Min: 1, Default: 5
  dry_run: boolean;             // Default: false
}
```

### Response Schema

```typescript
interface CleanupStuckExecutionsResponse {
  cancelled_count: number;      // Number of executions cancelled
  execution_ids: number[];      // List of cancelled execution IDs
  message: string;              // Human-readable status message
}
```
