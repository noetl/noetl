"""Tests for DuckDB Excel export integration."""

from pathlib import Path

import duckdb
import pytest

from noetl.tools.duckdb import excel as excel_module
from noetl.tools.duckdb.errors import SQLExecutionError
from noetl.tools.duckdb.excel import ExcelExportError, ExcelExportManager, parse_excel_copy_command
from noetl.tools.duckdb.sql.execution import execute_sql_commands


def test_parse_excel_copy_command_basic():
    command = """
    COPY (
        SELECT 1 AS id, 'Alice' AS name
    ) TO 'out.xlsx'
      (FORMAT 'xlsx', SHEET 'People', WRITE_MODE 'overwrite_sheet');
    """

    parsed = parse_excel_copy_command(command)
    assert parsed is not None
    assert parsed.destination == "out.xlsx"
    assert parsed.options["format"] == "xlsx"
    assert parsed.options["sheet"] == "People"
    assert "select 1" in parsed.query.lower()


def test_parse_excel_copy_command_ignores_parquet():
    command = "COPY weather_flat TO 'gs://bucket/file.parquet' (FORMAT PARQUET);"

    parsed = parse_excel_copy_command(command)
    assert parsed is None


def test_excel_export_manager_creates_file(tmp_path):
    conn = duckdb.connect()
    conn.execute("CREATE TABLE demo AS SELECT 1 AS id, 'Alice' AS name")

    export_path = tmp_path / "demo.xlsx"
    commands = [
        f"COPY (SELECT * FROM demo ORDER BY id) TO '{export_path}' (FORMAT 'xlsx', SHEET 'Demo');"
    ]

    manager = ExcelExportManager()
    result = execute_sql_commands(conn, commands, "task-1", excel_manager=manager)

    assert result["excel_commands"] == 1
    assert len(result["excel_exports"]) == 1
    assert Path(export_path).exists()


def test_excel_export_manager_uses_gcs_hmac_auth(monkeypatch):
    conn = duckdb.connect()
    conn.execute("CREATE TABLE demo AS SELECT 1 AS id, 'Alice' AS name")

    destination = "gs://demo-bucket/output.xlsx"
    commands = [
        f"COPY (SELECT * FROM demo ORDER BY id) TO '{destination}' (FORMAT 'xlsx', SHEET 'Demo');"
    ]

    auth_map = {
        "gcs_secret": {
            "service": "gcs",
            "payload": {
                "key_id": "TESTKEY",
                "secret_key": "secret",
                "scope": "gs://demo-bucket",
            },
        }
    }

    captured = {}

    def fake_upload(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(excel_module, "_upload_with_gcs_hmac_http", fake_upload)

    manager = ExcelExportManager(auth_map=auth_map)
    result = execute_sql_commands(conn, commands, "task-2", excel_manager=manager)

    assert result["excel_commands"] == 1
    assert captured["bucket"] == "demo-bucket"
    assert captured["object_path"] == "output.xlsx"
    assert captured["endpoint"] == "https://storage.googleapis.com"
    assert captured["data"].startswith(b"PK")  # XLSX files are ZIP archives
    assert captured["key_id"] == "TESTKEY"



def test_excel_export_manager_stops_after_auth_failure(monkeypatch):
    conn = duckdb.connect()
    conn.execute("CREATE TABLE demo AS SELECT 1 AS id, 'Alice' AS name")

    destination = "gs://demo-bucket/output.xlsx"
    commands = [
        f"COPY (SELECT * FROM demo ORDER BY id) TO '{destination}' (FORMAT 'xlsx', SHEET 'Demo');"
    ]

    auth_map = {
        "gcs_secret": {
            "service": "gcs",
            "payload": {
                "key_id": "TESTKEY",
                "secret_key": "secret",
                "scope": "gs://demo-bucket",
            },
        }
    }

    def fake_upload(**kwargs):
        raise ExcelExportError("boom")

    monkeypatch.setattr(excel_module, "_upload_with_gcs_hmac_http", fake_upload)

    fallback_called = {"value": False}

    def fake_fsspec(self, *args, **kwargs):  # noqa: ANN001 - signature mimics method
        fallback_called["value"] = True
        raise AssertionError("Fallback should not run when auth attempts fail")

    monkeypatch.setattr(ExcelExportManager, "_write_with_fsspec", fake_fsspec, raising=False)

    manager = ExcelExportManager(auth_map=auth_map)

    with pytest.raises(SQLExecutionError) as excinfo:
        execute_sql_commands(conn, commands, "task-3", excel_manager=manager)

    assert "Auth errors" in str(excinfo.value)
    assert fallback_called["value"] is False
