import re

with open("tests/unit/dsl/v2/test_engine.py", "r") as f:
    content = f.read()

# Replace string execution_ids with ints (represented as strings, but digits only)
content = content.replace('"exec-trans"', '"1000"')
content = content.replace('"exec-recovery"', '"1001"')
content = content.replace('"exec-no-dup"', '"1002"')

# Fix state replay mock
new_fetchone = """            async def fetchone(self):
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
    r'            async def fetchone\(self\):\n                if "playbook\.initialized" in self\.query:\n                    return \{\n                        "catalog_id": 101,\n                        "context": \{"workload": \{\}\},\n                        "result": None,\n                    \}\n                raise AssertionError\(f"Unexpected fetchone query: \{self\.query\}"\)',
    new_fetchone,
    content
)

with open("tests/unit/dsl/v2/test_engine.py", "w") as f:
    f.write(content)
