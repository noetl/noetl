#!/usr/bin/env python3
"""Direct test of V2 worker to see what's happening."""

import sys
import asyncio

print("=== Direct Worker Test ===", flush=True)
print(f"Python: {sys.version}", flush=True)

try:
    from noetl.worker.v2_worker_nats import V2Worker
    print("Successfully imported V2Worker", flush=True)
    
    async def test():
        print("Creating worker...", flush=True)
        worker = V2Worker(
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
