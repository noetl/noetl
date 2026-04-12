from typing import Optional
import asyncio

_batch_metrics: dict[str, float] = {
    "accepted_total": 0,
    "enqueue_error_total": 0,
    "ack_timeout_total": 0,
    "queue_unavailable_total": 0,
    "worker_unavailable_total": 0,
    "processing_timeout_total": 0,
    "processing_error_total": 0,
    "enqueue_latency_seconds_sum": 0.0,
    "enqueue_latency_seconds_count": 0,
    "first_worker_claim_latency_seconds_sum": 0.0,
    "first_worker_claim_latency_seconds_count": 0,
}

def _inc_batch_metric(name: str, amount: float = 1.0) -> None:
    _batch_metrics[name] = float(_batch_metrics.get(name, 0.0)) + amount

def _observe_batch_metric(prefix: str, value: float) -> None:
    safe_value = max(0.0, float(value))
    _inc_batch_metric(f"{prefix}_sum", safe_value)
    _inc_batch_metric(f"{prefix}_count", 1.0)

def get_batch_metrics_snapshot(queue: Optional[asyncio.Queue], workers_tasks: list[asyncio.Task]) -> dict[str, float]:
    """Export in-process batch acceptance metrics for /metrics endpoint."""
    snapshot = dict(_batch_metrics)
    snapshot["queue_depth"] = float(queue.qsize() if queue else 0)
    snapshot["worker_count"] = float(sum(1 for task in workers_tasks if not task.done()))
    return snapshot
