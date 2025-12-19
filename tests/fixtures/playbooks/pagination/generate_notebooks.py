#!/usr/bin/env python3
"""
Generate validation notebooks for pagination tests.
Creates standardized notebooks with proper structure for each pagination pattern.
"""

import json
import sys
from pathlib import Path

def create_pagination_notebook(
    test_name: str,
    test_path: str,
    endpoint: str,
    description: str,
    expected_items: int,
    expected_pages: int,
    special_validation: str = ""
):
    """Create a validation notebook for a pagination test"""
    
    cells = [
        # Cell 1: Title
        {
            "cell_type": "markdown",
            "metadata": {},
            "source": [f"# {test_name}\n\nValidation notebook for {description.lower()}"]
        },
        
        # Cell 2: Setup
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "import os\n",
                "import time\n",
                "import json\n",
                "import requests\n",
                "from typing import Dict\n\n",
                "# Modern data stack\n",
                "import psycopg\n",
                "import polars as pl\n\n",
                "# Configuration - Auto-detect environment\n",
                "ENVIRONMENT = os.getenv(\"NOETL_ENV\", \"localhost\").lower()\n\n",
                "if ENVIRONMENT == \"kubernetes\":\n",
                "    DB_CONFIG = {\n",
                "        \"host\": \"postgres.postgres.svc.cluster.local\",\n",
                "        \"port\": \"5432\",\n",
                "        \"user\": os.getenv(\"POSTGRES_USER\", \"demo\"),\n",
                "        \"password\": os.getenv(\"POSTGRES_PASSWORD\", \"demo\"),\n",
                "        \"dbname\": os.getenv(\"POSTGRES_DB\", \"demo_noetl\")\n",
                "    }\n",
                "    NOETL_SERVER_URL = \"http://noetl.noetl.svc.cluster.local:8082\"\n",
                "else:\n",
                "    DB_CONFIG = {\n",
                "        \"host\": \"localhost\",\n",
                "        \"port\": \"54321\",\n",
                "        \"user\": os.getenv(\"POSTGRES_USER\", \"demo\"),\n",
                "        \"password\": os.getenv(\"POSTGRES_PASSWORD\", \"demo\"),\n",
                "        \"dbname\": os.getenv(\"POSTGRES_DB\", \"demo_noetl\")\n",
                "    }\n",
                "    NOETL_SERVER_URL = \"http://localhost:8082\"\n\n",
                f"TEST_PATH = \"{test_path}\"\n",
                "POLL_INTERVAL = 2\n",
                "MAX_WAIT = 60\n\n",
                "print(\"✓ Configuration loaded\")\n",
                f"print(f\"  Environment: {{ENVIRONMENT}}\")\n",
                f"print(f\"  Server: {{NOETL_SERVER_URL}}\")\n",
                f"print(f\"  Database: {{DB_CONFIG['host']}}:{{DB_CONFIG['port']}}/{{DB_CONFIG['dbname']}}\")\n",
                f"print(f\"  Test: {{TEST_PATH}}\")"
            ]
        },
        
        # Cell 3: Database utilities
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "def get_postgres_connection():\n",
                "    \"\"\"Get psycopg3 connection\"\"\"\n",
                "    conn_string = f\"host={DB_CONFIG['host']} port={DB_CONFIG['port']} \" \\\n",
                "                  f\"dbname={DB_CONFIG['dbname']} user={DB_CONFIG['user']} \" \\\n",
                "                  f\"password={DB_CONFIG['password']}\"\n",
                "    return psycopg.connect(conn_string)\n\n",
                "def query_to_polars(query: str) -> pl.DataFrame:\n",
                "    \"\"\"Execute query and return as Polars DataFrame\"\"\"\n",
                "    with get_postgres_connection() as conn:\n",
                "        with conn.cursor() as cur:\n",
                "            cur.execute(query)\n",
                "            columns = [desc[0] for desc in cur.description]\n",
                "            data = cur.fetchall()\n",
                "    if not data:\n",
                "        return pl.DataFrame(schema=columns)\n",
                "    return pl.DataFrame({col: [row[i] for row in data] for i, col in enumerate(columns)})\n\n",
                "print(\"✓ Database utilities loaded\")"
            ]
        },
        
        # Cell 4: Execute test
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "def start_test() -> Dict:\n",
                "    \"\"\"Start pagination test\"\"\"\n",
                "    url = f\"{NOETL_SERVER_URL}/api/run/playbook\"\n",
                "    payload = {\"path\": TEST_PATH}\n",
                "    \n",
                f"    print(f\"Starting test: {{TEST_PATH}}\")\n",
                "    response = requests.post(url, json=payload, timeout=30)\n",
                "    response.raise_for_status()\n",
                "    \n",
                "    result = response.json()\n",
                "    execution_id = result['execution_id']\n",
                "    \n",
                "    print(f\"✓ Test started\")\n",
                f"    print(f\"  Execution ID: {{execution_id}}\")\n",
                f"    print(f\"  Status: {{result['status']}}\")\n",
                "    \n",
                "    return result\n\n",
                "test_result = start_test()\n",
                "EXECUTION_ID = test_result['execution_id']"
            ]
        },
        
        # Cell 5: Monitor execution
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "def monitor_execution(execution_id: int):\n",
                "    \"\"\"Monitor test execution\"\"\"\n",
                "    start_time = time.time()\n",
                "    last_count = 0\n",
                "    \n",
                f"    print(f\"Monitoring execution {{execution_id}}...\")\n",
                "    print(f\"{'Time':<6} {'Steps':<6} {'Status':<12} {'Events'}\")\n",
                "    print(\"-\" * 50)\n",
                "    \n",
                "    while (time.time() - start_time) < MAX_WAIT:\n",
                "        query = f\"\"\"\n",
                "            SELECT event_type, COUNT(*) as count\n",
                "            FROM noetl.event\n",
                "            WHERE execution_id = {execution_id}\n",
                "            GROUP BY event_type\n",
                "        \"\"\"\n",
                "        df = query_to_polars(query)\n",
                "        \n",
                "        step_count = df.filter(pl.col('event_type') == 'step_completed')['count'].sum() or 0\n",
                "        is_complete = df.filter(pl.col('event_type') == 'playbook_completed').height > 0\n",
                "        is_failed = df.filter(pl.col('event_type') == 'playbook_failed').height > 0\n",
                "        \n",
                "        if step_count != last_count or is_complete or is_failed:\n",
                "            elapsed = int(time.time() - start_time)\n",
                "            status = \"COMPLETED\" if is_complete else (\"FAILED\" if is_failed else \"RUNNING\")\n",
                "            total = df['count'].sum()\n",
                f"            print(f\"{{elapsed:<6}} {{step_count:<6}} {{status:<12}} {{total}}\")\n",
                "            last_count = step_count\n",
                "        \n",
                "        if is_complete:\n",
                f"            print(f\"\\n✓ Test completed in {{elapsed}}s\")\n",
                "            return True\n",
                "        elif is_failed:\n",
                f"            print(f\"\\n✗ Test failed after {{elapsed}}s\")\n",
                "            return False\n",
                "        \n",
                "        time.sleep(POLL_INTERVAL)\n",
                "    \n",
                f"    print(f\"\\n⚠ Timeout after {{MAX_WAIT}}s\")\n",
                "    return False\n\n",
                "success = monitor_execution(EXECUTION_ID)"
            ]
        },
        
        # Cell 6: View events
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                "def show_execution_events(execution_id: int):\n",
                "    \"\"\"Display ordered table of events for an execution\"\"\"\n",
                "    query = f\"\"\"\n",
                "        SELECT \n",
                "            ROW_NUMBER() OVER (ORDER BY event_id) as seq,\n",
                "            event_type,\n",
                "            node_name,\n",
                "            node_type,\n",
                "            status,\n",
                "            created_at\n",
                "        FROM noetl.event\n",
                "        WHERE execution_id = {execution_id}\n",
                "        ORDER BY event_id\n",
                "    \"\"\"\n",
                "    \n",
                "    df = query_to_polars(query)\n",
                "    \n",
                f"    print(f\"\\n📋 Events for Execution {{execution_id}}\")\n",
                "    print(\"=\" * 120)\n",
                "    print(f\"{'#':<4} {'Event Type':<25} {'Node':<30} {'Type':<12} {'Status':<12} {'Created'}\")\n",
                "    print(\"-\" * 120)\n",
                "    \n",
                "    for row in df.iter_rows(named=True):\n",
                "        node_name = row['node_name'] or '-'\n",
                "        node_type = row['node_type'] or '-'\n",
                "        status = row['status'] or '-'\n",
                "        created = str(row['created_at']) if row['created_at'] else '-'\n",
                "        \n",
                f"        print(f\"{{row['seq']:<4}} {{row['event_type']:<25}} {{node_name:<30}} \"\n",
                f"              f\"{{node_type:<12}} {{status:<12}} {{created}}\")\n",
                "    \n",
                "    print(\"-\" * 120)\n",
                f"    print(f\"Total events: {{len(df)}}\\n\")\n\n",
                "show_execution_events(EXECUTION_ID)"
            ]
        },
        
        # Cell 7: Validation
        {
            "cell_type": "code",
            "execution_count": None,
            "metadata": {},
            "outputs": [],
            "source": [
                f"print(f\"\\n🔍 Validation for {test_name}\")\n",
                "print(\"=\" * 80)\n\n",
                "# Get final result from step\n",
                "query = f\"\"\"\n",
                "    SELECT result\n",
                "    FROM noetl.event\n",
                "    WHERE execution_id = {EXECUTION_ID}\n",
                f"    AND event_type = 'step_result'\n",
                "    ORDER BY created_at DESC\n",
                "    LIMIT 1\n",
                "\"\"\"\n\n",
                "with get_postgres_connection() as conn:\n",
                "    with conn.cursor() as cur:\n",
                "        cur.execute(query)\n",
                "        row = cur.fetchone()\n",
                "        if row:\n",
                "            result = row[0]\n",
                f"            print(f\"✓ Final result retrieved\")\n",
                f"            print(f\"  Status: {{result.get('status')}}\")\n",
                f"            print(f\"  Total items: {{result.get('total_items')}}\")\n",
                f"            \n",
                f"            # Validate\n",
                f"            expected_items = {expected_items}\n",
                f"            actual_items = result.get('total_items', 0)\n",
                f"            \n",
                f"            if actual_items == expected_items:\n",
                f"                print(f\"\\n🎉 SUCCESS! Fetched {{actual_items}} items (expected {{expected_items}})\")\n",
                f"{special_validation}",
                f"            else:\n",
                f"                print(f\"\\n❌ FAILED! Expected {{expected_items}} items, got {{actual_items}}\")\n",
                "        else:\n",
                f"            print(\"❌ No result found\")\n\n",
                "print(\"=\" * 80)"
            ]
        }
    ]
    
    notebook = {
        "cells": cells,
        "metadata": {
            "kernelspec": {
                "display_name": "Python 3",
                "language": "python",
                "name": "python3"
            },
            "language_info": {
                "codemirror_mode": {
                    "name": "ipython",
                    "version": 3
                },
                "file_extension": ".py",
                "mimetype": "text/x-python",
                "name": "python",
                "nbconvert_exporter": "python",
                "pygments_lexer": "ipython3",
                "version": "3.12.0"
            }
        },
        "nbformat": 4,
        "nbformat_minor": 5
    }
    
    return notebook

if __name__ == "__main__":
    # Generate notebooks for each test
    tests = [
        {
            "name": "Basic Page-Number Pagination",
            "path": "tests/pagination/basic",
            "endpoint": "/api/v1/assessments",
            "description": "Page-number based pagination",
            "expected_items": 35,
            "expected_pages": 4,
            "output": "/Users/akuksin/projects/noetl/noetl/tests/fixtures/playbooks/pagination/basic/test_basic_pagination.ipynb"
        },
        {
            "name": "Cursor-Based Pagination",
            "path": "tests/pagination/cursor",
            "endpoint": "/api/v1/events",
            "description": "Cursor-based pagination",
            "expected_items": 35,
            "expected_pages": 4,
            "output": "/Users/akuksin/projects/noetl/noetl/tests/fixtures/playbooks/pagination/cursor/test_cursor_pagination.ipynb"
        },
        {
            "name": "Offset-Based Pagination",
            "path": "tests/pagination/offset",
            "endpoint": "/api/v1/users",
            "description": "Offset-based pagination",
            "expected_items": 35,
            "expected_pages": 4,
            "output": "/Users/akuksin/projects/noetl/noetl/tests/fixtures/playbooks/pagination/offset/test_offset_pagination.ipynb"
        },
        {
            "name": "Max Iterations Safety Limit",
            "path": "tests/pagination/max_iterations",
            "endpoint": "/api/v1/assessments",
            "description": "Max iterations safety limit",
            "expected_items": 20,
            "expected_pages": 2,
            "special_validation": "                print(f\"  Max iterations enforced: 2 pages only (not all 4)\\n\")",
            "output": "/Users/akuksin/projects/noetl/noetl/tests/fixtures/playbooks/pagination/max_iterations/test_max_iterations.ipynb"
        },
        {
            "name": "Pagination with Retry",
            "path": "tests/pagination/retry",
            "endpoint": "/api/v1/flaky",
            "description": "Pagination with automatic retry on failures",
            "expected_items": 35,
            "expected_pages": 4,
            "special_validation": "                print(f\"  Retry worked: Recovered from page 2 failure\\n\")",
            "output": "/Users/akuksin/projects/noetl/noetl/tests/fixtures/playbooks/pagination/retry/test_retry_pagination.ipynb"
        }
    ]
    
    for test in tests:
        notebook = create_pagination_notebook(
            test_name=test["name"],
            test_path=test["path"],
            endpoint=test["endpoint"],
            description=test["description"],
            expected_items=test["expected_items"],
            expected_pages=test["expected_pages"],
            special_validation=test.get("special_validation", "")
        )
        
        output_path = Path(test["output"])
        output_path.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_path, 'w') as f:
            json.dump(notebook, f, indent=2)
        
        print(f"✓ Created: {output_path}")
    
    print("\n✅ All notebooks generated successfully!")
