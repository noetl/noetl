# Timezone Configuration Guide

## Overview

NoETL uses **UTC** as the default timezone for all components to avoid issues with:
- Daylight saving time transitions
- Distributed system timestamp coordination
- Cross-timezone data processing

## Components Affected

### 1. PostgreSQL Database
- **Location**: `docker/postgres/Dockerfile`, `ci/manifests/postgres/configmap.yaml`
- **Setting**: `TZ=UTC` environment variable
- **Config Files**: 
  - `scripts/database/postgres/postgresql.conf` - `timezone = 'UTC'` and `log_timezone = 'UTC'`
  - `ci/manifests/postgres/config-files.yaml` - inline postgresql.conf with `timezone = 'UTC'`

### 2. NoETL Server
- **Location**: `ci/manifests/noetl/configmap.yaml`
- **Setting**: `TZ: "UTC"`
- **Impact**: All server-side timestamp generation uses UTC

### 3. NoETL Worker
- **Location**: `ci/manifests/noetl/configmap.yaml` (shared with server)
- **Setting**: `TZ: "UTC"`
- **Impact**: Worker processes use UTC for all time operations

## Changing Timezone

If you need to use a different timezone (e.g., `America/Chicago`), update these files:

### Step 1: Update Postgres Configuration

1. **Docker Build**:
   ```dockerfile
   # docker/postgres/Dockerfile
   ARG TZ=America/Chicago  # Change default
   ENV TZ=${TZ}
   ```

2. **Kubernetes ConfigMap**:
   ```yaml
   # ci/manifests/postgres/configmap.yaml
   data:
     TZ: America/Chicago
   ```

3. **PostgreSQL Config**:
   ```conf
   # scripts/database/postgres/postgresql.conf
   timezone = 'America/Chicago'
   log_timezone = 'America/Chicago'
   ```

### Step 2: Update NoETL Configuration

```yaml
# ci/manifests/noetl/configmap.yaml
data:
  TZ: "America/Chicago"
```

### Step 3: Rebuild and Redeploy

```bash
# Rebuild Postgres image with new timezone
task docker-build-postgres

# Redeploy Postgres with new configuration
task deploy-postgres

# Restart NoETL components to pick up new TZ
task deploy-noetl
```

## Timezone-Aware Development

### Python Code Best Practices

**DO** - Use timezone-aware datetimes:
```python
from datetime import datetime, timezone

# Correct - timezone-aware UTC datetime
now = datetime.now(timezone.utc)
available_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
```

**DON'T** - Use naive datetimes:
```python
# WRONG - creates naive datetime that Postgres interprets as local time
now = datetime.utcnow()  # Deprecated, creates naive datetime
available_at = datetime.now()  # Uses system timezone, not UTC
```

### Database Timestamp Handling

PostgreSQL `timestamptz` columns:
- **Store**: Always in UTC internally
- **Display**: Converted to session timezone for display
- **Input**: Naive timestamps interpreted as session timezone

Example query behavior:
```sql
-- Session timezone affects how timestamps are interpreted
SET timezone = 'America/Chicago';
SELECT '2025-10-26 10:00:00'::timestamptz;  -- Interpreted as Chicago time
-- Result: 2025-10-26 15:00:00+00 (converted to UTC)

SET timezone = 'UTC';
SELECT '2025-10-26 10:00:00'::timestamptz;  -- Interpreted as UTC
-- Result: 2025-10-26 10:00:00+00 (already UTC)
```

### Common Pitfalls

1. **Naive datetime insertion**: 
   ```python
   # Wrong - creates 5-hour offset with America/Chicago
   available_at = datetime.utcnow()  # Naive UTC datetime
   # Postgres sees "10:00:00" and thinks "10:00 Chicago" = "15:00 UTC"
   ```

2. **Timezone mismatch**:
   - App configured for UTC
   - Database configured for America/Chicago
   - Result: All timestamps off by 5-6 hours

3. **DST transitions**:
   - Non-UTC timezones have daylight saving time
   - Timestamps during "fall back" hour are ambiguous
   - Timestamps during "spring forward" hour don't exist

## Verification

### Check Current Timezone

**Database**:
```bash
psql -c "SHOW timezone;"
# Expected: UTC
```

**Container Environment**:
```bash
kubectl exec -n postgres deployment/postgres -- date
kubectl exec -n noetl deployment/noetl-server -- date
# Expected: UTC timestamps
```

**Python Code**:
```python
from datetime import datetime, timezone
print(datetime.now(timezone.utc))
# Should show UTC time with +00:00 offset
```

### Test Timestamp Consistency

```bash
# Insert timestamp from Python
python -c "from datetime import datetime, timezone; print(datetime.now(timezone.utc))"

# Compare with database NOW()
psql -c "SELECT NOW();"

# Should be within seconds of each other
```

## Migration Notes

If changing from `America/Chicago` to `UTC` on existing deployment:

1. **Existing Data**: Timestamps already stored correctly (timestamptz is always UTC internally)
2. **Running Jobs**: May have incorrect `available_at` if enqueued before restart
3. **Solution**: Clear queue or wait for old jobs to expire
   ```sql
   -- Clear queue if safe to restart
   TRUNCATE noetl.queue;
   ```

## Related Files

- `docker/postgres/Dockerfile` - Postgres container timezone
- `ci/manifests/postgres/configmap.yaml` - Postgres K8s environment
- `ci/manifests/noetl/configmap.yaml` - NoETL server/worker environment  
- `scripts/database/postgres/postgresql.conf` - Postgres server config
- `noetl/server/api/run/publisher.py` - Job queue timestamp generation
- `noetl/server/api/queue/service.py` - Job lease timestamp comparison

## References

- [PostgreSQL: Date/Time Types](https://www.postgresql.org/docs/current/datatype-datetime.html)
- [Python datetime documentation](https://docs.python.org/3/library/datetime.html)
- [IANA Time Zone Database](https://www.iana.org/time-zones)
