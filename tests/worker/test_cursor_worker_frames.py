from __future__ import annotations

import pytest
from jinja2 import Environment


class _FakeCursorDriver:
    kind = "frame_test"

    def __init__(self, rows):
        self.rows = list(rows)
        self.claim_contexts = []

    async def open(self, auth, spec):
        return self

    async def claim(self, handle, context):
        self.claim_contexts.append(dict(context))
        if not self.rows:
            return None
        return self.rows.pop(0)

    async def close(self, handle):
        return None


class _FakeStore:
    def __init__(self):
        self.puts = []

    async def put_ipc_bytes(self, **kwargs):
        from noetl.core.storage import Scope, StoreTier, TempRef, TempRefMeta

        self.puts.append(kwargs)
        return TempRef.create(
            execution_id=kwargs["execution_id"],
            name=kwargs["name"],
            store=kwargs.get("store") or StoreTier.KV,
            scope=kwargs.get("scope") or Scope.EXECUTION,
            meta=TempRefMeta(
                content_type=kwargs["media_type"],
                media_type=kwargs["media_type"],
                bytes=len(kwargs["data_bytes"]),
                schema_digest=kwargs["schema_digest"],
                row_count=kwargs["row_count"],
                encoding="binary",
            ),
        )


@pytest.mark.asyncio
async def test_cursor_worker_claims_and_serializes_bounded_frames(monkeypatch):
    from noetl.core.cursor_drivers import register_driver
    from noetl.core.storage import arrow_ipc_to_rows
    from noetl.worker import cursor_worker

    driver = _FakeCursorDriver(
        [
            {"id": 1, "status": "pending"},
            {"id": 2, "status": "pending"},
            {"id": 3, "status": "pending"},
        ]
    )
    register_driver(driver.kind, driver)
    fake_store = _FakeStore()
    monkeypatch.setattr(cursor_worker, "default_store", fake_store)
    monkeypatch.setattr(cursor_worker, "_frame_ipc_cache", lambda: None)
    async def fetch_credential(auth_key):
        return {"dsn": "memory"}

    monkeypatch.setattr(cursor_worker, "fetch_credential_by_key_async", fetch_credential)

    seen_iter = []

    async def tool_executor(kind, cfg, ctx):
        seen_iter.append(dict(ctx["iter"]["item"]))
        return {"status": "ok"}

    result = await cursor_worker.execute_cursor_worker(
        config={
            "cursor": {
                "kind": driver.kind,
                "auth": "pg",
                "claim": "select next",
                "options": {"max_iterations": 10},
            },
            "iterator": "item",
            "tasks": [{"name": "process_item", "kind": "noop"}],
            "frame_policy": {"max_rows": 2, "max_seconds": 30, "max_bytes": 4096},
        },
        context={"execution_id": 42},
        jinja_env=Environment(),
        tool_executor=tool_executor,
        render_template=lambda template, ctx: template,
        render_dict=lambda data, ctx: data,
        worker_slot_id="slot-1",
    )

    assert result["status"] == "ok"
    assert result["processed"] == 3
    assert result["frame_count"] == 2
    assert [frame["row_count"] for frame in result["frames"]] == [2, 1]
    assert seen_iter == [
        {"id": 1, "status": "pending"},
        {"id": 2, "status": "pending"},
        {"id": 3, "status": "pending"},
    ]

    first_frame_rows = arrow_ipc_to_rows(fake_store.puts[0]["data_bytes"])
    assert first_frame_rows == [
        {"id": 1, "status": "pending"},
        {"id": 2, "status": "pending"},
    ]
    assert fake_store.puts[0]["row_count"] == 2
    assert fake_store.puts[0]["media_type"] == "application/vnd.apache.arrow.stream"
    assert driver.claim_contexts[0]["frame_index"] == 0
    assert driver.claim_contexts[1]["frame_row_index"] == 1
