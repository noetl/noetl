import re

with open("tests/unit/dsl/engine/test_engine.py", "r") as f:
    content = f.read()

# Fix mock for state_replay test positional arguments
content = content.replace("async def _load_playbook_by_id(_catalog_id):", "async def _load_playbook_by_id(_catalog_id, _conn=None):")

# Fix _ReplayCursor to handle all queries and return consistent mocks
replacement = """    class _ReplayCursor:
        def __init__(self):
            self.query = ""

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def execute(self, query, params=None):
            self.query = query

        async def fetchone(self):
            if "noetl.execution" in self.query:
                return None
            if "playbook.initialized" in self.query:
                return {
                    "catalog_id": 101,
                    "context": {"workload": {}},
                    "result": None,
                }
            if "noetl.event" in self.query:
                 return {
                    "catalog_id": 101,
                    "context": {"workload": {}},
                    "result": None,
                }
            return None

        async def fetchall(self):
            if "event_type = ANY" in self.query:
                return [
                    {
                        "event_id": 1,
                        "parent_event_id": None,
                        "node_name": "claim_rows",
                        "event_type": "call.done",
                        "result": {
                            "rows": [{"patient_id": 7}],
                            "row_count": 1,
                        },
                        "meta": None,
                    }
                ]
            return []"""

content = re.sub(r'    class _ReplayCursor:.*?return \[\]', replacement, content, flags=re.DOTALL)

# Fix engine_setup fixture to use a more robust mock store that doesn't actually try to hit DB
# but stores state in memory for the tests
content = content.replace("await state_store.save_state(state)", "monkeypatch.setattr(state_store, \"load_state\", AsyncMock(return_value=state))\n    monkeypatch.setattr(state_store, \"load_state_for_update\", AsyncMock(return_value=state))\n    await state_store.save_state(state)")

with open("tests/unit/dsl/engine/test_engine.py", "w") as f:
    f.write(content)
