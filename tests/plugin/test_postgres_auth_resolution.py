import noetl.tools.postgres as pgmod
from noetl.tools.postgres.auth import validate_and_render_connection_params


class DummyJinja:
    pass


def test_missing_fields_error():
    task_config = {"type": "postgres", "command_b64": "U0VMRUNUIDE7"}  # SELECT 1;
    try:
        pgmod.execute_postgres_task(task_config, context={}, jinja_env=DummyJinja(), task_with={}, log_event_callback=lambda *a, **k: None)
        assert False, "should raise"
    except ValueError as e:
        msg = str(e)
        assert "requires `auth`" in msg


def test_validate_connection_enforces_pgbouncer_route(monkeypatch):
    monkeypatch.setenv("NOETL_POSTGRES_ENFORCE_PGBOUNCER", "true")
    monkeypatch.setenv("NOETL_POSTGRES_PGBOUNCER_HOST", "pgbouncer.noetl.svc.cluster.local")
    monkeypatch.setenv("NOETL_POSTGRES_PGBOUNCER_PORT", "5432")

    host, port, *_rest = validate_and_render_connection_params(
        task_with={
            "db_host": "direct.db.internal",
            "db_port": "5432",
            "db_user": "svc",
            "db_password": "secret",
            "db_name": "analytics",
            "db_conn_string": "dbname=analytics user=svc password=secret host=direct.db.internal port=5432",
        },
        jinja_env=DummyJinja(),
        context={},
    )

    assert host == "pgbouncer.noetl.svc.cluster.local"
    assert port == "5432"
