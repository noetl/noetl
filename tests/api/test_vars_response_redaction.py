from __future__ import annotations

from datetime import datetime, timezone

import pytest

from noetl.server.api.vars import endpoint as vars_endpoint


def _now():
    return datetime(2026, 5, 24, 20, 0, 0, tzinfo=timezone.utc)


def _jwt() -> str:
    return ".".join(["eyJhbGciOiJIUzI1NiJ9", "eyJzdWIiOiIxMjMifQ", "signature"])


@pytest.mark.asyncio
async def test_list_variables_redacts_secret_values(monkeypatch):
    async def fake_get_all_vars_with_metadata(_execution_id):
        return {
            "auth0_token": {
                "value": _jwt(),
                "type": "user_defined",
                "source_step": "login",
                "created_at": _now(),
                "accessed_at": _now(),
                "access_count": 0,
            },
            "safe_region": {
                "value": "us-central1",
                "type": "user_defined",
                "source_step": None,
                "created_at": _now(),
                "accessed_at": _now(),
                "access_count": 0,
            },
        }

    monkeypatch.setattr(
        vars_endpoint.TransientVars,
        "get_all_vars_with_metadata",
        fake_get_all_vars_with_metadata,
    )

    response = await vars_endpoint.list_variables(123)

    assert response.variables["auth0_token"].value == "[REDACTED]"
    assert response.variables["safe_region"].value == "us-central1"


@pytest.mark.asyncio
async def test_get_variable_redacts_secret_value(monkeypatch):
    async def fake_get_cached(_var_name, _execution_id):
        return {
            "value": {"api_key": "sk-" + "test_" + ("A" * 32)},
            "type": "computed",
            "source_step": "resolve",
            "created_at": _now(),
            "accessed_at": _now(),
            "access_count": 1,
        }

    monkeypatch.setattr(vars_endpoint.TransientVars, "get_cached", fake_get_cached)

    response = await vars_endpoint.get_variable(123, "provider_config")

    assert response.value == {"api_key": "[REDACTED]"}
