import asyncio
from typing import List

from noetl import worker


class DummyQueueWorker:
    def __init__(self, server_url=None, worker_id=None, thread_pool=None, process_pool=None):
        pass

    async def run_forever(self, interval: float = 0.01, stop_event: asyncio.Event | None = None):
        while stop_event and not stop_event.is_set():
            await asyncio.sleep(0.01)


def test_pool_scales_workers(monkeypatch):
    monkeypatch.setattr(worker, "QueueWorker", DummyQueueWorker)
    pool = worker.ScalableQueueWorkerPool(server_url="http://test", max_workers=5)

    sizes: List[int] = [3, 1]

    async def fake_size() -> int:
        return sizes.pop(0)

    monkeypatch.setattr(pool, "_queue_size", fake_size)

    async def run_test():
        await pool._scale_workers()
        assert len(pool._tasks) == 3
        await pool._scale_workers()
        assert len(pool._tasks) == 1
        await pool.stop()

    asyncio.run(run_test())

