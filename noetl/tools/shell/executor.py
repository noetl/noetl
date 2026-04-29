"""``kind: shell`` distributed-worker executor.

Mirrors the contract every other plugin in ``noetl/tools/`` follows:

    execute_shell_task(task_config, context, jinja_env, args) -> dict

``task_config["cmds"]`` is a list of multi-line shell program strings.
Each is jinja-rendered against the merged context (workload + args)
and then executed with ``/bin/sh -c <program>`` via ``subprocess.run``.
Output is captured, returncode is propagated, and the structured result
matches the rest of the plugin family (``status: ok|error``, ``data``
with stdout/stderr/returncode/duration_ms, plus ``text`` for the
GUI's run dialog so it surfaces inline alongside python steps).

This is deliberately conservative:

  - **No environment leakage from the worker pod's parent process** —
    we only forward variables explicitly declared under
    ``task_config["env"]`` (Jinja-rendered).
  - **Per-command timeout** — ``task_config["timeout_seconds"]``,
    default 600s, applied to each ``cmds`` entry. Lifecycle deploys
    that block forever shouldn't pin a worker.
  - **Failure-aware aggregation** — if any command exits non-zero we
    stop running the remaining commands, mark the result as error,
    and surface the failing command's stdout/stderr in the response.
    Same shape ``kind: python`` produces on uncaught exceptions.
"""

from __future__ import annotations

import os
import shlex
import subprocess
import time
from typing import Any

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


_DEFAULT_TIMEOUT_SECONDS = 600
_SHELL_BIN = "/bin/sh"


def _render(jinja_env, value: Any, context: dict) -> Any:
    """Render a Jinja2 template iff the value is a string with templating.

    Mirrors how ``noetl.tools.python.executor`` walks a single argument:
    only strings are rendered; lists/dicts/scalars pass through. We rely
    on the worker having already merged config + args into ``context``
    by the time this executor runs (the dispatcher does that — see
    ``nats_worker.py:_execute_tool``).
    """
    if not isinstance(value, str):
        return value
    if "{{" not in value and "{%" not in value:
        return value
    try:
        return jinja_env.from_string(value).render(**(context or {}))
    except Exception as exc:
        # Don't fail the whole step on a single bad template — let the
        # shell see the original string and surface the error there.
        # That matches the behaviour python steps get when their
        # rendered args fail to coerce.
        logger.warning("SHELL.RENDER: failed for value (len=%d): %s", len(value), exc)
        return value


def _build_env(task_config: dict, jinja_env, context: dict) -> dict[str, str]:
    """Build the subprocess env from task_config["env"] (rendered).

    Skips inheriting the worker pod's parent env on purpose. Lifecycle
    agents that need PATH / KUBERNETES_SERVICE_HOST / etc. should pass
    them through explicitly via ``env:`` in their YAML — defaulting to
    inheriting would leak NATS credentials, postgres URLs, and other
    secrets from the worker's environment into every shell-out.
    """
    explicit_env = task_config.get("env") or {}
    if not isinstance(explicit_env, dict):
        explicit_env = {}

    # Always preserve PATH so kubectl / helm / awk / etc. resolve from
    # /usr/local/bin where the worker image installs them. Skipping
    # PATH entirely would force every agent to set it manually, and
    # the worker image's PATH is a known-safe value.
    env: dict[str, str] = {"PATH": os.environ.get("PATH", "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin")}

    # KUBERNETES_SERVICE_HOST / KUBERNETES_SERVICE_PORT are how
    # in-cluster kubectl auto-discovers the API server; lifecycle
    # agents check the former to detect in-cluster execution. Forward
    # them through unconditionally — they're not secret, they're the
    # cluster's internal service IP.
    for k in ("KUBERNETES_SERVICE_HOST", "KUBERNETES_SERVICE_PORT"):
        if k in os.environ:
            env[k] = os.environ[k]

    for key, value in explicit_env.items():
        rendered = _render(jinja_env, value, context)
        if rendered is None:
            continue
        env[str(key)] = str(rendered)

    return env


def _coerce_cmds(task_config: dict) -> list[str]:
    """Pull the cmds list out of task_config in a forgiving way.

    Accepts:
      - cmds: ["one-line", "two\\nlines"]    (canonical)
      - cmd:  "single command"               (legacy alias)
      - command: "single command"            (legacy alias)

    Anything else returns an empty list and the caller surfaces a
    structured error rather than crashing.
    """
    raw = task_config.get("cmds")
    if isinstance(raw, list):
        return [str(c) for c in raw]
    for alt in ("cmd", "command"):
        v = task_config.get(alt)
        if isinstance(v, str) and v.strip():
            return [v]
    if isinstance(raw, str) and raw.strip():
        return [raw]
    return []


def execute_shell_task(
    task_config: dict,
    context: dict,
    jinja_env,
    args: dict | None = None,
) -> dict[str, Any]:
    """Execute ``kind: shell`` steps from a distributed worker.

    Returns the same dict shape every other plugin returns:

        {
          "status": "ok" | "error",
          "data": {
            "returncode": int,             # last command's returncode
            "stdout": str,                 # concatenated stdout
            "stderr": str,                 # concatenated stderr
            "commands": [                  # per-command breakdown
              {"cmd_preview": "first line of cmd",
               "returncode": int,
               "stdout": str,
               "stderr": str,
               "duration_ms": int}
            ],
            "duration_ms": int,            # total elapsed
          },
          "text": str,                     # human-readable for GUI
          "error": str | None,             # only set when status=error
        }
    """
    args = args or {}

    cmds = _coerce_cmds(task_config)
    if not cmds:
        msg = (
            "shell tool requires task_config['cmds'] to be a non-empty list "
            "of program strings (or a 'cmd'/'command' string alias)"
        )
        logger.error("SHELL.CONFIG: %s", msg)
        return {
            "status": "error",
            "error": msg,
            "data": {
                "returncode": -1,
                "stdout": "",
                "stderr": msg,
                "commands": [],
                "duration_ms": 0,
            },
            "text": msg,
        }

    timeout_seconds = task_config.get("timeout_seconds")
    try:
        timeout_seconds = (
            float(timeout_seconds)
            if timeout_seconds is not None
            else _DEFAULT_TIMEOUT_SECONDS
        )
    except (TypeError, ValueError):
        timeout_seconds = _DEFAULT_TIMEOUT_SECONDS

    env = _build_env(task_config, jinja_env, context)
    cwd = task_config.get("cwd") or None

    aggregated_stdout: list[str] = []
    aggregated_stderr: list[str] = []
    per_cmd: list[dict[str, Any]] = []
    last_returncode = 0
    overall_start = time.monotonic()

    for raw_cmd in cmds:
        rendered = _render(jinja_env, raw_cmd, context)
        if not isinstance(rendered, str):
            rendered = str(rendered)

        cmd_preview = rendered.strip().splitlines()[0][:120] if rendered.strip() else ""
        logger.info(
            "SHELL.RUN: command=%r length=%d timeout=%ss",
            cmd_preview,
            len(rendered),
            timeout_seconds,
        )

        cmd_start = time.monotonic()
        try:
            completed = subprocess.run(  # noqa: S602 -- shell=False, exec via /bin/sh -c
                [_SHELL_BIN, "-c", rendered],
                env=env,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            stdout = (exc.stdout or "") if isinstance(exc.stdout, (str, bytes)) else ""
            stderr = (exc.stderr or "") if isinstance(exc.stderr, (str, bytes)) else ""
            if isinstance(stdout, bytes):
                stdout = stdout.decode("utf-8", errors="replace")
            if isinstance(stderr, bytes):
                stderr = stderr.decode("utf-8", errors="replace")
            duration_ms = int((time.monotonic() - cmd_start) * 1000)
            err_text = (
                f"shell command timed out after {timeout_seconds}s: "
                f"{cmd_preview or '<empty>'}"
            )
            logger.error("SHELL.TIMEOUT: %s", err_text)
            per_cmd.append({
                "cmd_preview": cmd_preview,
                "returncode": -1,
                "stdout": stdout,
                "stderr": (stderr + "\n" + err_text).strip(),
                "duration_ms": duration_ms,
            })
            aggregated_stdout.append(stdout)
            aggregated_stderr.append(stderr + "\n" + err_text)
            return {
                "status": "error",
                "error": err_text,
                "data": {
                    "returncode": -1,
                    "stdout": "\n".join(s for s in aggregated_stdout if s),
                    "stderr": "\n".join(s for s in aggregated_stderr if s),
                    "commands": per_cmd,
                    "duration_ms": int((time.monotonic() - overall_start) * 1000),
                },
                "text": err_text,
            }

        duration_ms = int((time.monotonic() - cmd_start) * 1000)
        per_cmd.append({
            "cmd_preview": cmd_preview,
            "returncode": completed.returncode,
            "stdout": completed.stdout or "",
            "stderr": completed.stderr or "",
            "duration_ms": duration_ms,
        })
        if completed.stdout:
            aggregated_stdout.append(completed.stdout)
        if completed.stderr:
            aggregated_stderr.append(completed.stderr)
        last_returncode = completed.returncode

        if completed.returncode != 0:
            err_text = (
                f"shell command exited with returncode={completed.returncode}: "
                f"{cmd_preview or '<empty>'}"
            )
            logger.warning(
                "SHELL.NONZERO: rc=%s preview=%r stderr=%r",
                completed.returncode,
                cmd_preview,
                (completed.stderr or "")[:400],
            )
            return {
                "status": "error",
                "error": err_text,
                "data": {
                    "returncode": completed.returncode,
                    "stdout": "\n".join(s for s in aggregated_stdout if s),
                    "stderr": "\n".join(s for s in aggregated_stderr if s),
                    "commands": per_cmd,
                    "duration_ms": int((time.monotonic() - overall_start) * 1000),
                },
                "text": (completed.stdout or "") + (completed.stderr or "") + "\n" + err_text,
            }

    full_stdout = "\n".join(s for s in aggregated_stdout if s)
    full_stderr = "\n".join(s for s in aggregated_stderr if s)

    return {
        "status": "ok",
        "data": {
            "returncode": last_returncode,
            "stdout": full_stdout,
            "stderr": full_stderr,
            "commands": per_cmd,
            "duration_ms": int((time.monotonic() - overall_start) * 1000),
        },
        # GUI run-dialog convention: surface a single human-readable
        # text blob alongside the structured payload. Same shape every
        # lifecycle agent's `kind: python` end step already returns.
        "text": full_stdout or full_stderr or "",
    }
