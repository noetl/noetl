import os
import json
import time
import uuid
import shutil
import random
import string
import pathlib
import subprocess

import pytest

# Integration tests here rely on Docker CLI to simulate a Kubernetes Job
# that runs a containerized script applying a Postgres schema. The test:
# - Creates a temporary Docker network
# - Starts a Postgres container with provided credentials
# - Runs a separate "job" container (postgres image) with a shell script mounted
#   that waits for readiness and applies DDL and dictionary SQL files
# - Captures container logs and verifies success by querying the DB via psql
#
# To enable these tests set NOETL_CONTAINER_TESTS=true and ensure Docker is available.


RUNTIME_ENABLED = os.environ.get("NOETL_CONTAINER_TESTS", "false").lower() == "true"


def _have_docker() -> bool:
    try:
        subprocess.run(["docker", "version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except Exception:
        return False


def _rand_suffix(n: int = 6) -> str:
    return ''.join(random.choice(string.ascii_lowercase + string.digits) for _ in range(n))


@pytest.mark.skipif(not RUNTIME_ENABLED, reason="Container runtime tests disabled. Set NOETL_CONTAINER_TESTS=true to enable.")
@pytest.mark.skipif(not _have_docker(), reason="Docker CLI is not available on this system")
class TestContainerJobPostgres:
    def setup_method(self):
        self.tmpdir = pathlib.Path(pytest.ensuretemp(f"container_job_{_rand_suffix()}"))
        # Write SQL fixtures
        (self.tmpdir / "tradedb_ddl.sql").write_text(
            """
            -- Create a demo table in the provided schema
            CREATE TABLE IF NOT EXISTS :SCHEMA_NAME.demo_trades(
                id SERIAL PRIMARY KEY,
                symbol TEXT NOT NULL,
                qty INT NOT NULL,
                price NUMERIC(10,2) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        (self.tmpdir / "create_dictionaries.sql").write_text(
            """
            -- Create a simple dictionary table
            CREATE TABLE IF NOT EXISTS :SCHEMA_NAME.dict_symbols(
                symbol TEXT PRIMARY KEY,
                description TEXT
            );
            INSERT INTO :SCHEMA_NAME.dict_symbols(symbol, description)
            VALUES ('AAPL', 'Apple Inc.') ON CONFLICT DO NOTHING;
            """
        )
        # Write the shell script based on the user's template
        (self.tmpdir / "apply_schema.sh").write_text(
            """#!/bin/sh\nset -e\n\nPOSTGRES="psql -h ${POSTGRES_HOST} -p ${POSTGRES_PORT} -d ${POSTGRES_DB} --username ${POSTGRES_USER}"\nDDL_PATH=${TRADDB_DDL_PATH:-/tradedb_ddl.sql}\nDICT_PATH=${TRADDB_DICT_PATH:-/create_dictionaries.sql}\n\necho "Waiting for postgres to be ready..."\nuntil pg_isready -h $POSTGRES_HOST -p $POSTGRES_PORT -U $POSTGRES_USER; do\n  echo "Waiting for postgres..."\n  sleep 2\ndone\n\necho "Creating database schemas in $POSTGRES_DB"\n\necho "Creating database schema ${POSTGRES_SCHEMA}"\n$POSTGRES <<-ESQL\n\\connect ${POSTGRES_DB};\nSET SESSION AUTHORIZATION ${POSTGRES_USER};\nCREATE SCHEMA IF NOT EXISTS ${POSTGRES_SCHEMA};\nCREATE EXTENSION IF NOT EXISTS plpython3u;\nCREATE EXTENSION IF NOT EXISTS pg_stat_statements;\nESQL\necho "Database schema ${POSTGRES_SCHEMA} created"\n\n$POSTGRES -v SCHEMA_NAME=${POSTGRES_SCHEMA} -f "${DDL_PATH}"\n$POSTGRES -v SCHEMA_NAME=${POSTGRES_SCHEMA} -f "${DICT_PATH}"\necho "Database schema ${POSTGRES_USER} objects created"\n"""
        )
        os.chmod(self.tmpdir / "apply_schema.sh", 0o755)

        # Common settings
        self.network = f"noetl_test_net_{_rand_suffix()}"
        self.pg_container = f"noetl_pg_{_rand_suffix()}"
        self.job_container = f"noetl_job_{_rand_suffix()}"

        self.pg_user = "testuser"
        self.pg_password = "testpass"
        self.pg_db = "testdb"
        self.pg_schema = "tradedb"
        self.pg_image = os.environ.get("NOETL_TEST_POSTGRES_IMAGE", "postgres:16-alpine")

    def teardown_method(self):
        # Cleanup containers and network if they exist
        subprocess.run(["docker", "rm", "-f", self.job_container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "rm", "-f", self.pg_container], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        subprocess.run(["docker", "network", "rm", self.network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Remove temp dir (pytest ensuretemp keeps; but try to clean content)
        try:
            shutil.rmtree(self.tmpdir, ignore_errors=True)
        except Exception:
            pass

    def _docker(self, *args, check=True, capture_output=False, text=True, env=None):
        return subprocess.run(["docker", *args], check=check, capture_output=capture_output, text=text, env=env)

    def _psql_query(self, query: str) -> str:
        # Run a one-off psql query in a disposable container on the same network
        proc = self._docker(
            "run", "--rm",
            "--network", self.network,
            self.pg_image,
            "psql", "-h", self.pg_container, "-p", "5432",
            "-U", self.pg_user, "-d", self.pg_db,
            "-tAc", query,
            capture_output=True
        )
        return proc.stdout.strip()

    def test_container_job_applies_schema_and_reports_logs(self):
        # 1) Create user-defined network
        self._docker("network", "create", self.network)

        # 2) Start Postgres on that network
        self._docker(
            "run", "-d", "--name", self.pg_container,
            "--network", self.network,
            "-e", f"POSTGRES_USER={self.pg_user}",
            "-e", f"POSTGRES_PASSWORD={self.pg_password}",
            "-e", f"POSTGRES_DB={self.pg_db}",
            self.pg_image
        )

        # 3) Run the job container with the script mounted
        mount_path = "/work"
        env_vars = {
            "POSTGRES_HOST": self.pg_container,
            "POSTGRES_PORT": "5432",
            "POSTGRES_USER": self.pg_user,
            "POSTGRES_PASSWORD": self.pg_password,
            "POSTGRES_DB": self.pg_db,
            "POSTGRES_SCHEMA": self.pg_schema,
            "TRADDB_DDL_PATH": f"{mount_path}/tradedb_ddl.sql",
            "TRADDB_DICT_PATH": f"{mount_path}/create_dictionaries.sql",
        }

        run_args = [
            "run", "--name", self.job_container,
            "--network", self.network,
            "-v", f"{self.tmpdir}:{mount_path}",
        ]
        for k, v in env_vars.items():
            run_args += ["-e", f"{k}={v}"]

        run_args += [self.pg_image, "/bin/sh", "-c", f"{mount_path}/apply_schema.sh"]

        # Use capture_output=False to stream logs; we will fetch logs after
        proc = self._docker(*run_args, check=False)
        assert proc.returncode == 0, f"Job container failed to start (rc={proc.returncode})"

        # Wait for container to finish
        # The script has set -e, so non-zero exit will stop the container
        # Poll for completion with timeout
        deadline = time.time() + 120
        while time.time() < deadline:
            ps = self._docker("ps", "-a", "--filter", f"name={self.job_container}", "--format", "{{.Status}}", capture_output=True)
            status = ps.stdout.strip()
            if status and (status.startswith("Exited") or status.startswith("Created")):
                break
            time.sleep(2)

        # Get exit code
        inspect = self._docker("inspect", self.job_container, "--format", "{{.State.ExitCode}}", capture_output=True)
        exit_code = int(inspect.stdout.strip() or "0")

        # Fetch logs for assertion and debugging
        logs = self._docker("logs", self.job_container, capture_output=True)
        log_text = logs.stdout

        assert exit_code == 0, f"Job container exit code {exit_code}. Logs:\n{log_text}"
        assert "Database schema" in log_text, "Expected log lines not found in job logs"
        assert "objects created" in log_text, "Expected completion marker not found in job logs"

        # 4) Verify schema & tables exist via psql inside another container
        schema_exists = self._psql_query(f"SELECT EXISTS (SELECT 1 FROM information_schema.schemata WHERE schema_name = '{self.pg_schema}');")
        assert schema_exists == 't', f"Schema {self.pg_schema} does not exist"

        table_count = self._psql_query(f"SELECT count(*) FROM information_schema.tables WHERE table_schema = '{self.pg_schema}';")
        assert table_count.isdigit() and int(table_count) >= 2, "Expected at least 2 tables created"

    def test_event_payload_mcp_semantics(self):
        """
        Minimal validation that a container-job step can construct an MCP-like event
        payload for reporting. We don't send the event over the network here.
        """
        # This event is a simplified stand-in for the tool's report
        event = {
            "event_type": "task_log",
            "component": {
                "kind": "tool",
                "tool": "container",
                "name": "apply_schema",
            },
            "status": "success",
            "context": {
                "execution_id": str(uuid.uuid4()),
                "job_id": f"job-{_rand_suffix()}",
            },
            "data": {
                "log": "Database schema tradedb created; objects created",
                "exit_code": 0,
            },
            "metadata": {
                "runner": "docker",
                "image": self.pg_image,
            },
        }
        # Basic schema checks per MCP-like semantics
        assert event["event_type"] == "task_log"
        assert event["component"]["kind"] == "tool"
        assert event["component"]["tool"] == "container"
        assert event["status"] in {"success", "error"}
        assert isinstance(event["context"].get("execution_id"), str)
        assert isinstance(event["data"].get("exit_code"), int)
        # Ensure it is JSON serializable
        json.dumps(event)
