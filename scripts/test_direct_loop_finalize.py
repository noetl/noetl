import asyncio
import sys

from noetl.api.routers.event.processing.loop_completion import _process_direct_loop_completion
from noetl.core.common import get_async_db_connection
from noetl.api.routers.event.service import get_event_service


async def main(execution_id: str, step_name: str) -> None:
    es = get_event_service()
    async with get_async_db_connection() as conn:
        async with conn.cursor() as cur:
            await _process_direct_loop_completion(conn, cur, es, execution_id, step_name)


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/test_direct_loop_finalize.py <execution_id> <step_name>")
        sys.exit(1)
    eid = sys.argv[1]
    step = sys.argv[2]
    asyncio.run(main(eid, step))

