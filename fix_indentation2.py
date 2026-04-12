import re

with open("noetl/server/api/v2.py", "r") as f:
    content = f.read()

fixed = """        async with get_pool_connection() as engine_conn:
            async with engine_conn.transaction():
                async with engine_conn.cursor() as cur:
                    # Batch orchestration runs off the request path and can legitimately
                    # exceed the default API statement timeout under fan-out load.
                    timeout_ms = int(_BATCH_PROCESSING_STATEMENT_TIMEOUT_MS)
                    await cur.execute(
                        f"SET LOCAL statement_timeout = {timeout_ms}"
                    )
                    await cur.execute("SELECT pg_advisory_xact_lock(%s)", (int(job.last_actionable_event.execution_id),))
                    commands = await engine.handle_event(job.last_actionable_event, conn=engine_conn, already_persisted=True)"""

content = re.sub(
    r'        async with get_pool_connection\(\) as engine_conn:\n            async with engine_conn.transaction\(\):\n                async with engine_conn.cursor\(\) as cur:\n                    # Batch orchestration runs off the request path and can legitimately\n                    # exceed the default API statement timeout under fan-out load.\n                    timeout_ms = int\(_BATCH_PROCESSING_STATEMENT_TIMEOUT_MS\)\n                    await cur.execute\(\n                        f"SET LOCAL statement_timeout = \{timeout_ms\}"\n                    \)\n                    await cur.execute\("SELECT pg_advisory_xact_lock\(%s\)", \(int\(job.last_actionable_event.execution_id\),\)\)\n                commands = await engine.handle_event\(job.last_actionable_event, conn=engine_conn, already_persisted=True\)',
    fixed,
    content
)

with open("noetl/server/api/v2.py", "w") as f:
    f.write(content)

