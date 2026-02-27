"""
Adaptive concurrency controller for distributed worker-server communication.

Problem: Multiple workers issue claim and event-emission requests concurrently.
The server's DB pool has a finite number of connections. When all workers hit
the server simultaneously, pool slots are exhausted and the server returns 503.
Each worker then retries independently, creating retry storms that keep the
server saturated.

Solution: Per-process AIMD (Additive Increase / Multiplicative Decrease)
concurrency controller.

  - A shared async gate limits how many claim/event requests fly concurrently
    within one worker process.
  - On 503: multiplicative decrease of concurrency limit + global backoff.
  - On success: additive increase back toward the configured maximum.
  - Proactive probe: a background task polls /api/pool/status so the worker
    pre-throttles before hitting 503, rather than discovering saturation
    reactively.

This does NOT replace the per-command retry logic; it sits above it and prevents
the thundering-herd condition that makes retries ineffective.
"""

import asyncio
import logging
import time
from typing import Optional

logger = logging.getLogger(__name__)


class AdaptiveConcurrencyController:
    """
    AIMD concurrency gate shared across all NATS message handlers in one
    worker process.

    Usage:
        # In worker __init__:
        self._concurrency = AdaptiveConcurrencyController(initial_limit=2, max_limit=4)

        # In claim / event-emit path:
        await self._concurrency.acquire()
        try:
            resp = await http_call(...)
            if resp.status_code == 503:
                await self._concurrency.release_overload(retry_after)
            else:
                await self._concurrency.release_success()
        except Exception:
            await self._concurrency.release_error()
            raise
    """

    def __init__(
        self,
        initial_limit: float = 2.0,
        min_limit: float = 1.0,
        max_limit: float = 8.0,
        probe_interval: float = 8.0,
    ) -> None:
        # Concurrency limit (float for smooth AIMD transitions; effective = int(limit))
        self._limit: float = max(min_limit, min(initial_limit, max_limit))
        self._min: float = min_limit
        self._max: float = max_limit

        # Number of requests currently in flight (waiting for server response)
        self._active: int = 0

        # asyncio.Condition: used for wait/notify when a slot becomes available
        # or the backoff period ends.
        self._condition: asyncio.Condition = asyncio.Condition()

        # Monotonic timestamp after which new requests may proceed.
        # Set on 503; all waiters sleep until this passes.
        self._backoff_until: float = 0.0

        # Running count of consecutive 503 responses (reset on any success)
        self._consecutive_503: int = 0

        # Background probe state
        self._probe_interval: float = probe_interval
        self._probe_task: Optional[asyncio.Task] = None
        self._running: bool = False

        # Injected by the worker after async init
        self._http_client = None   # httpx.AsyncClient
        self._server_url: str = ""

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self, http_client, server_url: str) -> None:
        """Start the background probe task. Call once after the HTTP client is ready."""
        self._http_client = http_client
        self._server_url = server_url
        self._running = True
        self._probe_task = asyncio.create_task(
            self._probe_loop(), name="concurrency-probe"
        )

    async def stop(self) -> None:
        """Cancel the background probe task."""
        self._running = False
        if self._probe_task and not self._probe_task.done():
            self._probe_task.cancel()
            try:
                await self._probe_task
            except asyncio.CancelledError:
                pass
        self._probe_task = None

    async def acquire(self) -> None:
        """
        Wait for a concurrency slot.

        Blocks until:
          1. Any active global backoff period has elapsed, AND
          2. The number of active requests is below int(self._limit).
        """
        async with self._condition:
            while True:
                # --- Phase 1: respect global backoff ---
                delay = self._backoff_until - time.monotonic()
                if delay > 0:
                    # Release the condition lock while sleeping, wake early if
                    # notified (e.g. backoff cancelled after server recovers).
                    try:
                        await asyncio.wait_for(
                            self._condition.wait(), timeout=min(delay, 1.0)
                        )
                    except asyncio.TimeoutError:
                        pass
                    continue  # re-check everything

                # --- Phase 2: check concurrency limit ---
                if self._active < int(self._limit):
                    self._active += 1
                    return

                # --- Phase 3: wait for a slot to free up ---
                # 30s timeout is a safety net against leaked _active counts;
                # under normal operation notify_all() wakes us much sooner.
                try:
                    await asyncio.wait_for(
                        self._condition.wait(), timeout=30.0
                    )
                except asyncio.TimeoutError:
                    pass

    async def release_success(self) -> None:
        """Called after a successful (non-503) server response."""
        async with self._condition:
            self._active = max(0, self._active - 1)
            self._consecutive_503 = 0
            # Additive increase: +0.1 per success, bounded by max
            old_limit = self._limit
            self._limit = min(self._max, self._limit + 0.1)
            if int(self._limit) > int(old_limit):
                logger.debug(
                    "[CONCURRENCY] Limit increased %.1f → %.1f (success streak)",
                    old_limit, self._limit,
                )
            self._condition.notify_all()

    async def release_overload(self, retry_after: float = 1.0) -> None:
        """
        Called when the server returned 503.

        Applies AIMD multiplicative decrease to the concurrency limit and
        sets a global backoff window. All pending acquire() calls will wait
        out the backoff before trying again.
        """
        async with self._condition:
            self._active = max(0, self._active - 1)
            self._consecutive_503 += 1
            streak = self._consecutive_503

            # Multiplicative decrease
            old_limit = self._limit
            self._limit = max(self._min, self._limit * 0.5)

            # Exponential backoff: scales with streak, capped at 30 s
            base = max(float(retry_after), 0.5)
            backoff = min(base * (1.5 ** min(streak - 1, 7)), 30.0)
            self._backoff_until = time.monotonic() + backoff

            logger.info(
                "[CONCURRENCY] 503 streak=%d: limit %.1f→%.1f, backoff=%.2fs",
                streak, old_limit, self._limit, backoff,
            )
            self._condition.notify_all()

    async def release_error(self) -> None:
        """Called on a non-HTTP error (network timeout, exception). Just releases the slot."""
        async with self._condition:
            self._active = max(0, self._active - 1)
            self._condition.notify_all()

    def get_status(self) -> dict:
        """Return a snapshot of the controller state (for logging/metrics)."""
        return {
            "limit": round(self._limit, 2),
            "active": self._active,
            "consecutive_503": self._consecutive_503,
            "backoff_remaining": round(max(0.0, self._backoff_until - time.monotonic()), 2),
        }

    # ------------------------------------------------------------------
    # Background probe
    # ------------------------------------------------------------------

    async def _probe_loop(self) -> None:
        """
        Periodically query /api/pool/status and proactively adjust the limit
        before the server starts returning 503.

          - utilization > 80% or no free slots → reduce limit
          - utilization < 40% and slots available → allow recovery
        """
        # Small initial delay so the worker has time to fully start up
        await asyncio.sleep(5.0)

        while self._running:
            try:
                await asyncio.sleep(self._probe_interval)
                if not self._http_client or not self._server_url:
                    continue

                resp = await self._http_client.get(
                    f"{self._server_url.rstrip('/')}/api/pool/status",
                    timeout=5.0,
                )
                if resp.status_code != 200:
                    continue

                stats = resp.json()
                utilization = float(stats.get("utilization") or 0.0)
                available = int(stats.get("slots_available") or 0)
                pool_max = int(stats.get("pool_max") or 1)
                waiting = int(stats.get("requests_waiting") or 0)

                async with self._condition:
                    if utilization > 0.80 or available == 0 or waiting > 0:
                        # Server pool under pressure — reduce limit proactively
                        new_limit = max(self._min, self._limit * 0.75)
                        if new_limit < self._limit:
                            logger.info(
                                "[CONCURRENCY] Probe: server pool util=%.0f%% "
                                "avail=%d waiting=%d → limit %.1f→%.1f",
                                utilization * 100, available, waiting,
                                self._limit, new_limit,
                            )
                            self._limit = new_limit
                            # Apply a short proactive backoff so in-flight
                            # requests land before we issue more
                            self._backoff_until = max(
                                self._backoff_until,
                                time.monotonic() + 0.5 + 0.2 * waiting,
                            )
                            self._condition.notify_all()

                    elif utilization < 0.40 and available >= pool_max // 2:
                        # Server pool healthy — allow gradual recovery
                        new_limit = min(self._max, self._limit + 0.2)
                        if new_limit > self._limit + 0.05:
                            logger.debug(
                                "[CONCURRENCY] Probe: server pool healthy "
                                "util=%.0f%% → limit %.1f→%.1f",
                                utilization * 100, self._limit, new_limit,
                            )
                            self._limit = new_limit
                            self._condition.notify_all()

            except asyncio.CancelledError:
                break
            except Exception as exc:
                # Probe failures are non-fatal; log and continue
                logger.debug("[CONCURRENCY] Probe error: %s", exc)
