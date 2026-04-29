"""Unit tests for the distributed-worker shell executor.

Pure subprocess-driven tests that run real /bin/sh commands. Each
test is fast (<1s) — the timeout case caps at 1 second by design.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import pytest

from noetl.tools.shell.executor import execute_shell_task


class _FakeJinja:
    """Minimal Jinja-like adapter exposing only ``from_string(s).render(**ctx)``.

    The real Jinja2 environment is built once per worker request and
    threaded through; we don't want to import the worker stack here.
    A naive ``{{ var }}`` substitution covers every template our
    lifecycle agents currently use.
    """

    def from_string(self, s: str):
        class _T:
            def __init__(self, src: str):
                self.src = src

            def render(self, **ctx) -> str:
                out = self.src
                for k, v in ctx.items():
                    out = out.replace("{{ " + k + " }}", str(v))
                return out

        return _T(s)


# ---------------------------------------------------------------------------
# Happy-path
# ---------------------------------------------------------------------------


def test_runs_single_command_and_returns_ok_shape():
    result = execute_shell_task(
        {"cmds": ["echo hello"]},
        context={},
        jinja_env=_FakeJinja(),
        args={},
    )
    assert result["status"] == "ok"
    assert result["data"]["returncode"] == 0
    assert "hello" in result["data"]["stdout"]
    assert result["data"]["stderr"] == ""
    assert result["text"].strip() == "hello"


def test_renders_jinja_against_context():
    result = execute_shell_task(
        {"cmds": ["echo greet-{{ name }}"]},
        context={"name": "world"},
        jinja_env=_FakeJinja(),
        args={},
    )
    assert result["status"] == "ok"
    assert "greet-world" in result["data"]["stdout"]


def test_runs_multiple_commands_in_order():
    result = execute_shell_task(
        {"cmds": ["echo first", "echo second", "echo third"]},
        context={},
        jinja_env=_FakeJinja(),
        args={},
    )
    assert result["status"] == "ok"
    out = result["data"]["stdout"]
    assert out.index("first") < out.index("second") < out.index("third")
    assert len(result["data"]["commands"]) == 3


# ---------------------------------------------------------------------------
# Failure short-circuiting
# ---------------------------------------------------------------------------


def test_nonzero_exit_marks_status_error_and_short_circuits():
    result = execute_shell_task(
        {"cmds": ["echo first", "exit 7", "echo unreached"]},
        context={},
        jinja_env=_FakeJinja(),
        args={},
    )
    assert result["status"] == "error"
    assert result["data"]["returncode"] == 7
    assert "first" in result["data"]["stdout"]
    assert "unreached" not in result["data"]["stdout"]
    # Only the first two commands actually ran.
    assert len(result["data"]["commands"]) == 2
    assert "exit 7" in result["error"] or "returncode=7" in result["error"]


def test_command_timeout_returns_structured_error():
    result = execute_shell_task(
        {"cmds": ["sleep 5"], "timeout_seconds": 1},
        context={},
        jinja_env=_FakeJinja(),
        args={},
    )
    assert result["status"] == "error"
    assert "timed out" in result["error"]
    assert result["data"]["returncode"] == -1


def test_invalid_timeout_value_falls_back_to_default():
    """A garbage timeout shouldn't raise — silently use the default."""
    result = execute_shell_task(
        {"cmds": ["echo ok"], "timeout_seconds": "not-a-number"},
        context={},
        jinja_env=_FakeJinja(),
        args={},
    )
    assert result["status"] == "ok"


# ---------------------------------------------------------------------------
# Config validation
# ---------------------------------------------------------------------------


def test_missing_cmds_returns_structured_error_not_crash():
    result = execute_shell_task({}, context={}, jinja_env=_FakeJinja(), args={})
    assert result["status"] == "error"
    assert "non-empty list" in result["error"]
    assert result["data"]["returncode"] == -1


@pytest.mark.parametrize(
    "config",
    [
        {"cmd": "echo legacy-cmd-alias"},
        {"command": "echo legacy-command-alias"},
        # cmds-as-string treated as a single command for legacy compat
        {"cmds": "echo legacy-string-cmds"},
    ],
)
def test_string_aliases_for_cmds_work(config):
    result = execute_shell_task(
        config, context={}, jinja_env=_FakeJinja(), args={}
    )
    assert result["status"] == "ok", result
    assert "legacy" in result["data"]["stdout"]


# ---------------------------------------------------------------------------
# Environment forwarding
# ---------------------------------------------------------------------------


def test_path_is_forwarded_so_kubectl_helm_resolve():
    """The worker image installs kubectl/helm into /usr/local/bin.

    PATH must propagate to the subprocess or every lifecycle deploy
    would have to set it explicitly. Use 'which' as a portable proxy.
    """
    result = execute_shell_task(
        {"cmds": ["which sh"]},
        context={},
        jinja_env=_FakeJinja(),
        args={},
    )
    assert result["status"] == "ok"
    assert "/sh" in result["data"]["stdout"]


def test_kubernetes_service_host_forwarded_when_set(monkeypatch):
    """KUBERNETES_SERVICE_HOST is how lifecycle agents detect in-cluster execution."""
    monkeypatch.setenv("KUBERNETES_SERVICE_HOST", "10.96.0.1")
    result = execute_shell_task(
        {"cmds": ["echo $KUBERNETES_SERVICE_HOST"]},
        context={},
        jinja_env=_FakeJinja(),
        args={},
    )
    assert result["status"] == "ok"
    assert "10.96.0.1" in result["data"]["stdout"]


def test_explicit_env_entry_rendered_and_forwarded():
    result = execute_shell_task(
        {
            "cmds": ["echo $FOO"],
            "env": {"FOO": "bar-{{ x }}"},
        },
        context={"x": "42"},
        jinja_env=_FakeJinja(),
        args={},
    )
    assert result["status"] == "ok"
    assert "bar-42" in result["data"]["stdout"]


def test_arbitrary_parent_env_does_not_leak(monkeypatch):
    """Worker pod env (NATS creds, postgres URLs, etc.) must NOT leak.

    The executor only forwards PATH + KUBERNETES_SERVICE_* + explicit
    task.env entries. Anything else in os.environ should be invisible
    to the child shell.
    """
    monkeypatch.setenv("NOETL_LEAKY_SECRET", "must-not-appear-in-stdout")
    result = execute_shell_task(
        {"cmds": ["echo ${NOETL_LEAKY_SECRET:-unset}"]},
        context={},
        jinja_env=_FakeJinja(),
        args={},
    )
    assert result["status"] == "ok"
    assert "must-not-appear" not in result["data"]["stdout"]
    assert "unset" in result["data"]["stdout"]
