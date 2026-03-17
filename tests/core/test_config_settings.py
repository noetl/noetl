from noetl.core import config as config_module


def test_get_settings_uses_nats_subject_env(monkeypatch):
    monkeypatch.setenv("NOETL_RUN_MODE", "worker")
    monkeypatch.setenv("NOETL_SERVER_URL", "http://localhost:8082")
    monkeypatch.setenv("POSTGRES_PORT", "5432")
    monkeypatch.setenv("NOETL_PORT", "8082")
    monkeypatch.setenv("NOETL_SERVER_WORKERS", "1")
    monkeypatch.setenv("NOETL_SERVER", "uvicorn")
    monkeypatch.setenv("NATS_SUBJECT", "noetl.commands.custom")
    config_module._settings = None

    try:
        settings = config_module.get_settings(reload=True)
        assert settings.nats_subject == "noetl.commands.custom"
    finally:
        config_module._settings = None
