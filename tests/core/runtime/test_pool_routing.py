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
    ROUTING_ENABLED_ENV,
    is_routing_enabled,
    pool_segment_for_kind,
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
