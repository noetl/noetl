"""
NoETL Worker v2

Pure background worker with:
- NO HTTP endpoints (unlike v1 worker)
- Only command execution from queue
- Event emission to server
- Signal handling for graceful shutdown
"""

import logging
import asyncio
import signal
import sys
from typing import Optional
import uuid

from noetl.worker.executor_v2 import run_worker_v2

logger = logging.getLogger(__name__)


class WorkerV2:
    """
    Pure background worker for v2 architecture.
    
    Key differences from v1:
    - NO HTTP server
    - NO queue update APIs
    - Only polls queue and executes commands
    - All state changes via events to server
    """
    
    def __init__(self, worker_id: Optional[str] = None, server_url: str = "http://localhost:8000"):
        self.worker_id = worker_id or f"worker-{uuid.uuid4().hex[:8]}"
        self.server_url = server_url
        self._task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
    
    async def start(self):
        """Start worker."""
        logger.info(f"Starting NoETL Worker v2: {self.worker_id}")
        logger.info(f"Server URL: {self.server_url}")
        
        # Register signal handlers
        self._register_signal_handlers()
        
        # Start worker task
        self._task = asyncio.create_task(self._run())
        
        try:
            await self._task
        except asyncio.CancelledError:
            logger.info("Worker task cancelled")
    
    async def stop(self):
        """Stop worker gracefully."""
        logger.info("Stopping worker...")
        
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("Worker stopped")
    
    async def _run(self):
        """Main worker loop."""
        try:
            await run_worker_v2(
                worker_id=self.worker_id,
                server_url=self.server_url
            )
        except Exception as e:
            logger.error(f"Worker error: {e}", exc_info=True)
            raise
    
    def _register_signal_handlers(self):
        """Register signal handlers for graceful shutdown."""
        def handle_signal(sig, frame):
            logger.info(f"Received signal {sig}, initiating shutdown...")
            asyncio.create_task(self.stop())
        
        signal.signal(signal.SIGINT, handle_signal)
        signal.signal(signal.SIGTERM, handle_signal)


# ============================================================================
# Convenience Functions
# ============================================================================

async def start_worker_v2(worker_id: Optional[str] = None, server_url: str = "http://localhost:8000"):
    """
    Start worker v2 (convenience function).
    
    Usage:
        import asyncio
        from noetl.worker.worker_v2 import start_worker_v2
        
        asyncio.run(start_worker_v2(server_url="http://localhost:8000"))
    """
    worker = WorkerV2(worker_id=worker_id, server_url=server_url)
    await worker.start()


def run_worker_v2_sync(worker_id: Optional[str] = None, server_url: str = "http://localhost:8000"):
    """
    Run worker v2 synchronously (blocks until stopped).
    
    Usage:
        from noetl.worker.worker_v2 import run_worker_v2_sync
        
        run_worker_v2_sync(server_url="http://localhost:8000")
    """
    try:
        asyncio.run(start_worker_v2(worker_id=worker_id, server_url=server_url))
    except KeyboardInterrupt:
        logger.info("Worker interrupted by user")
    except Exception as e:
        logger.error(f"Worker failed: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    # Simple CLI for running worker
    import argparse
    
    parser = argparse.ArgumentParser(description="NoETL Worker v2")
    parser.add_argument("--worker-id", type=str, help="Worker ID")
    parser.add_argument("--server-url", type=str, default="http://localhost:8000", help="Server URL")
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    
    run_worker_v2_sync(worker_id=args.worker_id, server_url=args.server_url)
