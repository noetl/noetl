# Recovery: Readiness-Gated Auto-Resume

NoETL startup recovery can automatically restart interrupted **parent** playbook executions,
but only after critical dependencies are healthy.

## Dependency gate

Recovery waits for:

- PostgreSQL queryability
- NATS connectivity
- at least one ready worker heartbeat in `noetl.runtime`

If dependencies are not healthy yet, startup recovery retries with polling until timeout.

## Recovery modes

- `restart` (default): start a new execution from the interrupted parent workload, then mark the old execution as `execution.cancelled`.
- `cancel`: only mark interrupted execution as cancelled.

## Environment variables

- `NOETL_AUTO_RESUME_ENABLED` (default `true`)
- `NOETL_AUTO_RESUME_MODE` (`restart|cancel`, default `restart`)
- `NOETL_AUTO_RESUME_LOOKBACK_MINUTES` (default `15`)
- `NOETL_AUTO_RESUME_MAX_CANDIDATES` (default `1`, latest parent execution)
- `NOETL_AUTO_RESUME_READINESS_TIMEOUT_SECONDS` (default `300`)
- `NOETL_AUTO_RESUME_READINESS_POLL_SECONDS` (default `5`)
- `NOETL_AUTO_RESUME_STARTUP_DELAY_SECONDS` (default `3`)
- `NOETL_AUTO_RESUME_WORKER_HEARTBEAT_MAX_AGE_SECONDS` (default `60`)
- `NOETL_AUTO_RESUME_MIN_READY_WORKERS` (default `1`)

## Metrics

Exposed on `/metrics`:

- `noetl_auto_resume_attempts_total`
- `noetl_auto_resume_dependency_not_ready_total`
- `noetl_auto_resume_recoveries_started_total`
- `noetl_auto_resume_recoveries_completed_total`
- `noetl_auto_resume_recoveries_failed_total`
- `noetl_auto_resume_recoveries_restarted_total`
