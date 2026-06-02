"""Unit tests for `noetl.core.runtime.pool_routing` — see noetl/ai-meta#42.

PR-1 ships the routing helper as a no-behaviour-change scaffold gated
behind the ``NOETL_COMMAND_ROUTING_ENABLED`` env flag.  These tests
exercise both the flag-off path (subject returned verbatim) and the
flag-on path (hierarchical subject with pool segment).
"""

from __future__ import annotations

import os
import pytest

from noetl.core.runtime.pool_routing import (
    DEFAULT_POOL_SEGMENT,
    POOL_FILTER_MAP,
    POOL_PATH_PREFIX_MAP,
    ROUTING_ENABLED_ENV,
    command_stream_subjects,
    is_routing_enabled,
    pool_segment_for_kind,
    pool_segment_for_path,
    route_subject,
)


@pytest.fixture
def routing_off(monkeypatch):
    """Force routing flag off regardless of host env."""
    monkeypatch.delenv(ROUTING_ENABLED_ENV, raising=False)
    return monkeypatch


@pytest.fixture
def routing_on(monkeypatch):
    """Force routing flag on regardless of host env."""
    monkeypatch.setenv(ROUTING_ENABLED_ENV, "true")
    return monkeypatch


def test_pool_filter_map_includes_agent():
    """The agent kind is Python-only by design (noetl/ai-meta#42)."""
    assert POOL_FILTER_MAP["agent"] == "python"


def test_pool_filter_map_includes_task_sequence():
    """task_sequence is engine-level (not a noetl-tools kind); only the
    Python worker's ``TaskSequenceExecutor`` implements it.  Routing to
    Python keeps the regression suite green on the Rust pool (see
    noetl/ai-meta#47).
    """
    assert POOL_FILTER_MAP["task_sequence"] == "python"


def test_default_segment_is_shared():
    """Anything not in POOL_FILTER_MAP defaults to the shared queue."""
    assert DEFAULT_POOL_SEGMENT == "shared"


@pytest.mark.parametrize(
    "env_value, expected",
    [
        (None, False),
        ("", False),
        ("0", False),
        ("false", False),
        ("no", False),
        ("True", True),
        ("true", True),
        ("1", True),
        ("YES", True),
    ],
)
def test_is_routing_enabled_parses_flag(monkeypatch, env_value, expected):
    if env_value is None:
        monkeypatch.delenv(ROUTING_ENABLED_ENV, raising=False)
    else:
        monkeypatch.setenv(ROUTING_ENABLED_ENV, env_value)
    assert is_routing_enabled() is expected


def test_pool_segment_for_known_python_kind():
    assert pool_segment_for_kind("agent") == "python"
    assert pool_segment_for_kind("task_sequence") == "python"


def test_pool_segment_for_known_shared_kind():
    """Shared kinds default to "shared" (they're not in the map)."""
    for kind in ("http", "postgres", "duckdb", "nats", "mcp"):
        assert pool_segment_for_kind(kind) == DEFAULT_POOL_SEGMENT


def test_pool_segment_for_unknown_kind():
    """Unknown kinds default to "shared" — safer than failing."""
    assert pool_segment_for_kind("some-future-kind") == DEFAULT_POOL_SEGMENT


def test_pool_segment_for_none_or_empty():
    """Missing tool_kind argument routes to the shared queue."""
    assert pool_segment_for_kind(None) == DEFAULT_POOL_SEGMENT
    assert pool_segment_for_kind("") == DEFAULT_POOL_SEGMENT


def test_route_subject_returns_base_when_flag_off(routing_off):
    """No-behaviour-change guarantee for PR-1."""
    assert route_subject("noetl.commands", "agent", 12345) == "noetl.commands"
    assert route_subject("noetl.commands", "http", 12345) == "noetl.commands"
    assert route_subject("noetl.commands", None, 12345) == "noetl.commands"


def test_route_subject_segments_when_flag_on_agent(routing_on):
    """When the flag flips, agent commands route to the python branch."""
    assert (
        route_subject("noetl.commands", "agent", 12345)
        == "noetl.commands.python.12345"
    )


def test_route_subject_segments_when_flag_on_task_sequence(routing_on):
    """task_sequence commands also route to the python branch — only
    the Python worker's TaskSequenceExecutor implements the pipeline
    semantics (noetl/ai-meta#47).
    """
    assert (
        route_subject("noetl.commands", "task_sequence", 7777)
        == "noetl.commands.python.7777"
    )


def test_route_subject_segments_when_flag_on_shared(routing_on):
    """All non-Python-only kinds land on the shared branch."""
    for kind in ("http", "postgres", "duckdb", "nats", "mcp"):
        assert (
            route_subject("noetl.commands", kind, 67890)
            == "noetl.commands.shared.67890"
        )


def test_route_subject_segments_when_flag_on_unknown(routing_on):
    """Unknown kinds default to shared even with the flag on."""
    assert (
        route_subject("noetl.commands", "some-future-kind", 999)
        == "noetl.commands.shared.999"
    )


def test_route_subject_handles_none_kind_when_flag_on(routing_on):
    """Missing tool_kind argument still routes to shared with the flag on."""
    assert (
        route_subject("noetl.commands", None, 42)
        == "noetl.commands.shared.42"
    )


def test_command_stream_subjects_includes_bare_and_wildcard():
    """The stream must accept both the legacy bare subject AND the
    hierarchical wildcard so publishes work during the rollout window
    when the routing flag is mid-flip.  See noetl/ai-meta#42 PR-2a.
    """
    subjects = command_stream_subjects("noetl.commands")
    assert "noetl.commands" in subjects
    assert "noetl.commands.>" in subjects


def test_command_stream_subjects_preserves_base_for_other_streams():
    """The helper is generic over base subject — works for any stream name."""
    subjects = command_stream_subjects("foo.bar")
    assert subjects == ["foo.bar", "foo.bar.>"]


def test_command_stream_subjects_no_duplicate_entries():
    """No duplicate entries even if called repeatedly with the same base."""
    subjects = command_stream_subjects("x.y")
    assert len(subjects) == len(set(subjects))


# ---------------------------------------------------------------------------
# Path-based routing (noetl/ai-meta#46 Phase 2.a.2)
# ---------------------------------------------------------------------------


def test_pool_path_prefix_map_includes_system():
    """The ``system/`` prefix routes to the privileged system pool."""
    assert POOL_PATH_PREFIX_MAP["system/"] == "system"


def test_pool_segment_for_path_none_or_empty():
    """Missing playbook path returns ``None`` so the caller falls back to kind."""
    assert pool_segment_for_path(None) is None
    assert pool_segment_for_path("") is None
    assert pool_segment_for_path("/") is None  # only a slash → empty after lstrip


def test_pool_segment_for_path_system_namespace():
    """Paths under the ``system/`` namespace route to the system pool."""
    assert pool_segment_for_path("system/outbox_publisher") == "system"
    assert pool_segment_for_path("system/projector") == "system"
    assert pool_segment_for_path("system/nested/deep/playbook") == "system"


def test_pool_segment_for_path_strips_leading_slash():
    """Catalog paths sometimes carry a leading slash — match identically."""
    assert pool_segment_for_path("/system/outbox_publisher") == "system"
    assert pool_segment_for_path("//system/foo") == "system"


def test_pool_segment_for_path_user_namespace_returns_none():
    """User playbooks return ``None`` so kind-based routing decides the pool."""
    for path in (
        "user/foo",
        "tenants/acme/etl",
        "tests/fixtures/rust_worker_r2_validation",
        "playbooks/duffel_search",
    ):
        assert pool_segment_for_path(path) is None


def test_pool_segment_for_path_requires_trailing_slash_boundary():
    """``system`` without a trailing slash is NOT a system playbook — guards against
    accidental matches like ``systems_dashboard`` or just ``system``.
    """
    assert pool_segment_for_path("system") is None
    assert pool_segment_for_path("systems_dashboard") is None
    assert pool_segment_for_path("systemd") is None


def test_route_subject_path_wins_over_kind_when_flag_on(routing_on):
    """A ``system/*`` playbook with a normally-shared tool kind still
    routes to the system pool — the whole point of Phase 2.a.2.
    """
    # ``http`` would normally route to shared, but the system/ path forces system.
    assert (
        route_subject(
            "noetl.commands",
            "http",
            12345,
            playbook_path="system/outbox_publisher",
        )
        == "noetl.commands.system.12345"
    )


def test_route_subject_path_wins_even_for_agent_kind(routing_on):
    """Even ``agent`` (which would otherwise force python) is overridden
    by the privileged path — system playbooks always claim the system
    pool, no exceptions.
    """
    assert (
        route_subject(
            "noetl.commands",
            "agent",
            99,
            playbook_path="system/some_agent_playbook",
        )
        == "noetl.commands.system.99"
    )


def test_route_subject_falls_back_to_kind_for_non_system_paths(routing_on):
    """Non-system paths route by tool kind, same as before."""
    assert (
        route_subject(
            "noetl.commands",
            "agent",
            42,
            playbook_path="user/my_agent",
        )
        == "noetl.commands.python.42"
    )
    assert (
        route_subject(
            "noetl.commands",
            "http",
            42,
            playbook_path="user/my_http",
        )
        == "noetl.commands.shared.42"
    )


def test_route_subject_no_path_falls_back_to_kind(routing_on):
    """Omitting ``playbook_path`` preserves the legacy kind-only behaviour."""
    assert (
        route_subject("noetl.commands", "http", 7)
        == "noetl.commands.shared.7"
    )
    assert (
        route_subject("noetl.commands", "agent", 7)
        == "noetl.commands.python.7"
    )


def test_route_subject_path_routing_disabled_when_flag_off(routing_off):
    """Even a ``system/*`` path returns the base subject when the
    routing flag is off — kept off in tests + before the cutover.
    """
    assert (
        route_subject(
            "noetl.commands",
            "http",
            12345,
            playbook_path="system/outbox_publisher",
        )
        == "noetl.commands"
    )
