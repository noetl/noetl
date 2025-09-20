import types

import noetl.plugin.postgres as pgmod


class DummyJinja:
    pass


def test_missing_fields_error():
    task_config = {"type": "postgres", "command_b64": "U0VMRUNUIDE7"}  # SELECT 1;
    try:
        pgmod.execute_postgres_task(task_config, context={}, jinja_env=DummyJinja(), task_with={}, log_event_callback=lambda *a, **k: None)
        assert False, "should raise"
    except ValueError as e:
        msg = str(e)
        assert "Use `auth: <credential_key>`" in msg

