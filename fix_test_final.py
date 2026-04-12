import re

with open("tests/unit/dsl/engine/test_engine.py", "r") as f:
    content = f.read()

# Fix mock for state_replay test
replacement = """        async def fetchone(self):
            if "noetl.execution" in self.query:
                return None
            if "playbook.initialized" in self.query:
                return {
                    "catalog_id": 101,
                    "context": {"workload": {}},
                    "result": None,
                }
            raise AssertionError(f"Unexpected fetchone query: {self.query}")"""

content = re.sub(
    r'        async def fetchone\(self\):\n            if "playbook\.initialized" in self\.query:\n                return \{\n                    "catalog_id": 101,\n                    "context": \{"workload": \{\}\},\n                    "result": None,\n                \}\n            raise AssertionError\(f"Unexpected fetchone query: \{self\.query\}"\)',
    replacement,
    content
)

with open("tests/unit/dsl/engine/test_engine.py", "w") as f:
    f.write(content)
