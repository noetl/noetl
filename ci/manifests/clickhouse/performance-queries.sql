-- ============================================================================
-- NoETL Performance Analysis Queries for ClickHouse
-- ============================================================================
-- These queries help identify performance bottlenecks in playbook execution.
-- Run these against the observability.noetl_events table after syncing events.
--
-- Usage:
--   kubectl exec -n clickhouse <pod> -- clickhouse-client --query="<query>"
--   Or use port-forward and connect via HTTP: http://localhost:30123
-- ============================================================================

-- ============================================================================
-- Query 1: Execution Duration Distribution (Last 24 hours)
-- Shows P50/P95/P99 latencies by event type
-- ============================================================================
SELECT
    toStartOfHour(Timestamp) AS hour,
    EventType,
    count() AS event_count,
    round(avg(Duration), 2) AS avg_duration_ms,
    round(quantile(0.50)(Duration), 2) AS p50_ms,
    round(quantile(0.95)(Duration), 2) AS p95_ms,
    round(quantile(0.99)(Duration), 2) AS p99_ms,
    max(Duration) AS max_ms
FROM observability.noetl_events
WHERE Timestamp >= now() - INTERVAL 24 HOUR
GROUP BY hour, EventType
ORDER BY hour DESC, avg_duration_ms DESC;

-- ============================================================================
-- Query 2: Slowest Steps (>1 second)
-- Find individual steps taking longest
-- ============================================================================
SELECT
    ExecutionId,
    StepName,
    EventType,
    Duration AS duration_ms,
    Timestamp,
    Status,
    ErrorMessage
FROM observability.noetl_events
WHERE Timestamp >= now() - INTERVAL 1 HOUR
  AND Duration > 1000  -- Steps taking > 1 second
ORDER BY Duration DESC
LIMIT 50;

-- ============================================================================
-- Query 3: Event Throughput by Minute
-- Monitor event emission rate
-- ============================================================================
SELECT
    toStartOfMinute(Timestamp) AS minute,
    countIf(EventType = 'command.claimed') AS claims,
    countIf(EventType = 'command.started') AS starts,
    countIf(EventType = 'command.completed') AS completions,
    countIf(EventType = 'command.failed') AS failures,
    countIf(Status = 'FAILED') AS total_failures,
    round(avg(Duration), 2) AS avg_duration_ms
FROM observability.noetl_events
WHERE Timestamp >= now() - INTERVAL 1 HOUR
GROUP BY minute
ORDER BY minute DESC;

-- ============================================================================
-- Query 4: Execution Timeline Analysis
-- Detailed event sequence for a specific execution
-- Replace {execution_id} with actual execution ID
-- ============================================================================
-- SELECT
--     ExecutionId,
--     EventType,
--     StepName,
--     Timestamp,
--     Duration AS step_duration_ms,
--     Status,
--     row_number() OVER (ORDER BY Timestamp) AS event_order,
--     dateDiff('millisecond',
--         lagInFrame(Timestamp, 1, Timestamp) OVER (ORDER BY Timestamp),
--         Timestamp
--     ) AS time_since_prev_ms
-- FROM observability.noetl_events
-- WHERE ExecutionId = '{execution_id}'
-- ORDER BY Timestamp;

-- ============================================================================
-- Query 5: Event Count per Execution (State Reconstruction Cost)
-- High event counts may cause slow state reconstruction
-- ============================================================================
SELECT
    ExecutionId,
    count() AS total_events,
    min(Timestamp) AS start_time,
    max(Timestamp) AS end_time,
    dateDiff('second', min(Timestamp), max(Timestamp)) AS duration_seconds,
    countIf(Status = 'FAILED') AS failed_events,
    uniq(StepName) AS unique_steps
FROM observability.noetl_events
WHERE Timestamp >= now() - INTERVAL 24 HOUR
GROUP BY ExecutionId
HAVING total_events > 10  -- Executions with many events
ORDER BY total_events DESC
LIMIT 100;

-- ============================================================================
-- Query 6: Worker Performance Comparison
-- Compare throughput across workers
-- ============================================================================
SELECT
    Metadata['worker_id'] AS worker_id,
    count() AS command_count,
    round(avg(Duration), 2) AS avg_duration_ms,
    round(quantile(0.95)(Duration), 2) AS p95_duration_ms,
    max(Duration) AS max_duration_ms,
    countIf(Status = 'FAILED') AS failures
FROM observability.noetl_events
WHERE EventType IN ('command.completed', 'command.failed')
  AND Timestamp >= now() - INTERVAL 1 HOUR
  AND Metadata['worker_id'] != ''
GROUP BY worker_id
ORDER BY avg_duration_ms DESC;

-- ============================================================================
-- Query 7: Bottleneck Detection (Gap Analysis)
-- Find large gaps between consecutive events within executions
-- ============================================================================
SELECT
    ExecutionId,
    prev_event_type,
    EventType AS curr_event_type,
    prev_step,
    StepName AS curr_step,
    gap_ms,
    Timestamp
FROM (
    SELECT
        ExecutionId,
        EventType,
        StepName,
        Timestamp,
        lagInFrame(EventType, 1, '') OVER (
            PARTITION BY ExecutionId ORDER BY Timestamp
        ) AS prev_event_type,
        lagInFrame(StepName, 1, '') OVER (
            PARTITION BY ExecutionId ORDER BY Timestamp
        ) AS prev_step,
        dateDiff('millisecond',
            lagInFrame(Timestamp, 1, Timestamp) OVER (
                PARTITION BY ExecutionId ORDER BY Timestamp
            ),
            Timestamp
        ) AS gap_ms
    FROM observability.noetl_events
    WHERE Timestamp >= now() - INTERVAL 1 HOUR
)
WHERE gap_ms > 5000  -- Gaps > 5 seconds
ORDER BY gap_ms DESC
LIMIT 50;

-- ============================================================================
-- Query 8: Event Type Transition Analysis
-- Find which event transitions are slowest
-- ============================================================================
SELECT
    prev_event_type,
    EventType AS curr_event_type,
    count() AS transition_count,
    round(avg(gap_ms), 2) AS avg_gap_ms,
    round(quantile(0.95)(gap_ms), 2) AS p95_gap_ms,
    max(gap_ms) AS max_gap_ms
FROM (
    SELECT
        EventType,
        lagInFrame(EventType, 1, '') OVER (
            PARTITION BY ExecutionId ORDER BY Timestamp
        ) AS prev_event_type,
        dateDiff('millisecond',
            lagInFrame(Timestamp, 1, Timestamp) OVER (
                PARTITION BY ExecutionId ORDER BY Timestamp
            ),
            Timestamp
        ) AS gap_ms
    FROM observability.noetl_events
    WHERE Timestamp >= now() - INTERVAL 1 HOUR
)
WHERE prev_event_type != ''
GROUP BY prev_event_type, curr_event_type
HAVING avg_gap_ms > 100  -- Only show transitions averaging >100ms
ORDER BY avg_gap_ms DESC
LIMIT 20;

-- ============================================================================
-- Query 9: Hourly Error Rate
-- Track error trends over time
-- ============================================================================
SELECT
    toStartOfHour(Timestamp) AS hour,
    count() AS total_events,
    countIf(Status = 'FAILED') AS failed_events,
    round(countIf(Status = 'FAILED') * 100.0 / count(), 2) AS error_rate_pct,
    uniq(ExecutionId) AS unique_executions
FROM observability.noetl_events
WHERE Timestamp >= now() - INTERVAL 24 HOUR
GROUP BY hour
ORDER BY hour DESC;

-- ============================================================================
-- Query 10: Step Duration by Name
-- Find which steps are consistently slow
-- ============================================================================
SELECT
    StepName,
    EventType,
    count() AS occurrences,
    round(avg(Duration), 2) AS avg_duration_ms,
    round(quantile(0.50)(Duration), 2) AS p50_ms,
    round(quantile(0.95)(Duration), 2) AS p95_ms,
    max(Duration) AS max_ms,
    min(Duration) AS min_ms
FROM observability.noetl_events
WHERE Timestamp >= now() - INTERVAL 24 HOUR
  AND StepName != ''
  AND Duration > 0
GROUP BY StepName, EventType
ORDER BY avg_duration_ms DESC
LIMIT 30;

-- ============================================================================
-- Query 11: Playbook Performance Summary
-- Compare playbook execution times
-- ============================================================================
SELECT
    PlaybookPath,
    count() AS execution_count,
    round(avg(total_duration_ms), 2) AS avg_duration_ms,
    round(quantile(0.95)(total_duration_ms), 2) AS p95_duration_ms,
    round(avg(event_count), 2) AS avg_events
FROM (
    SELECT
        ExecutionId,
        any(PlaybookPath) AS PlaybookPath,
        dateDiff('millisecond', min(Timestamp), max(Timestamp)) AS total_duration_ms,
        count() AS event_count
    FROM observability.noetl_events
    WHERE Timestamp >= now() - INTERVAL 24 HOUR
      AND PlaybookPath != ''
    GROUP BY ExecutionId
)
WHERE PlaybookPath != ''
GROUP BY PlaybookPath
ORDER BY avg_duration_ms DESC
LIMIT 20;

-- ============================================================================
-- Query 12: Recent Failures with Context
-- Debug recent failures
-- ============================================================================
SELECT
    Timestamp,
    ExecutionId,
    EventType,
    StepName,
    Status,
    ErrorMessage,
    Duration AS duration_ms
FROM observability.noetl_events
WHERE Status = 'FAILED'
  AND Timestamp >= now() - INTERVAL 1 HOUR
ORDER BY Timestamp DESC
LIMIT 20;

-- ============================================================================
-- Query 13: Event Emission Latency Histogram
-- Distribution of event durations
-- ============================================================================
SELECT
    multiIf(
        Duration < 10, '0-10ms',
        Duration < 50, '10-50ms',
        Duration < 100, '50-100ms',
        Duration < 500, '100-500ms',
        Duration < 1000, '500ms-1s',
        Duration < 5000, '1-5s',
        Duration < 10000, '5-10s',
        '>10s'
    ) AS duration_bucket,
    count() AS event_count,
    round(count() * 100.0 / sum(count()) OVER (), 2) AS percentage
FROM observability.noetl_events
WHERE Timestamp >= now() - INTERVAL 1 HOUR
  AND Duration > 0
GROUP BY duration_bucket
ORDER BY
    CASE duration_bucket
        WHEN '0-10ms' THEN 1
        WHEN '10-50ms' THEN 2
        WHEN '50-100ms' THEN 3
        WHEN '100-500ms' THEN 4
        WHEN '500ms-1s' THEN 5
        WHEN '1-5s' THEN 6
        WHEN '5-10s' THEN 7
        ELSE 8
    END;

-- ============================================================================
-- Query 14: Command Lifecycle Analysis
-- Track command state transitions timing
-- ============================================================================
SELECT
    ExecutionId,
    StepName,
    minIf(Timestamp, EventType = 'command.issued') AS issued_at,
    minIf(Timestamp, EventType = 'command.claimed') AS claimed_at,
    minIf(Timestamp, EventType = 'command.started') AS started_at,
    minIf(Timestamp, EventType IN ('command.completed', 'command.failed')) AS finished_at,
    dateDiff('millisecond',
        minIf(Timestamp, EventType = 'command.issued'),
        minIf(Timestamp, EventType = 'command.claimed')
    ) AS issue_to_claim_ms,
    dateDiff('millisecond',
        minIf(Timestamp, EventType = 'command.claimed'),
        minIf(Timestamp, EventType = 'command.started')
    ) AS claim_to_start_ms,
    dateDiff('millisecond',
        minIf(Timestamp, EventType = 'command.started'),
        minIf(Timestamp, EventType IN ('command.completed', 'command.failed'))
    ) AS execution_ms,
    anyIf(Status, EventType IN ('command.completed', 'command.failed')) AS final_status
FROM observability.noetl_events
WHERE Timestamp >= now() - INTERVAL 1 HOUR
  AND StepName != ''
GROUP BY ExecutionId, StepName
HAVING issued_at IS NOT NULL
ORDER BY issue_to_claim_ms + claim_to_start_ms DESC
LIMIT 30;

-- ============================================================================
-- Query 15: Real-time Performance Monitor
-- Run continuously to monitor current state
-- ============================================================================
SELECT
    'Last 5 minutes' AS period,
    count() AS events,
    uniq(ExecutionId) AS executions,
    countIf(Status = 'FAILED') AS failures,
    round(avg(Duration), 2) AS avg_duration_ms,
    max(Duration) AS max_duration_ms
FROM observability.noetl_events
WHERE Timestamp >= now() - INTERVAL 5 MINUTE;
