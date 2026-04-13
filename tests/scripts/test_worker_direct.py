#!/usr/bin/env python3
"""Direct worker smoke test."""

import sys
import asyncio

print("=== Direct Worker Test ===", flush=True)
print(f"Python: {sys.version}", flush=True)

try:
    from noetl.worker.nats_worker import Worker
    print("Successfully imported Worker", flush=True)
    
    async def test():
        print("Creating worker...", flush=True)
        worker = Worker(
            worker_id="test-worker",
            nats_url="nats://noetl:noetl@localhost:30422",
            server_url="http://localhost:30082"
        )
        print("Worker created", flush=True)
        
        print("Starting worker...", flush=True)
        await worker.start()
        print("Worker started (should not see this)", flush=True)
    
    print("Running async test...", flush=True)
    asyncio.run(test())
    print("Test complete (should not see this)", flush=True)
    
except Exception as e:
    print(f"ERROR: {e}", flush=True)
    import traceback
    traceback.print_exc()
    sys.exit(1)
