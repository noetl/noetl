"""Unit tests for `_projection_sort_key` — closes noetl/noetl#638.

The replay service sorts projection rows (frames, stages, commands) by
identifier.  Production identifiers are snowflake-style numeric strings
(e.g. ``"639947948205277573"``); test fixtures and synthetic data use
semantic strings (e.g. ``"stage-1"``).  The previous
``int(row["X"])`` lambdas raised ``ValueError`` on non-numeric ids,
breaking the whole normaliser.  The helper tuple-sorts so both shapes
coexist: numeric first by int value, then non-numeric lexicographically.
"""

from __future__ import annotations

from noetl.server.api.replay.service import _projection_sort_key


def test_numeric_strings_get_numeric_sort_bucket():
    assert _projection_sort_key("100") == (0, 100)
    assert _projection_sort_key("9") == (0, 9)


def test_numeric_strings_sort_numerically_not_lexically():
    """Without numeric coercion, "10" would sort before "9" lex.

    Snowflake IDs (long numeric strings) must keep numeric ordering so
    event-log replay produces a deterministic event sequence.
    """
    keys = [_projection_sort_key(value) for value in ("10", "2", "100", "9")]
    sorted_keys = sorted(keys)
    assert sorted_keys == [(0, 2), (0, 9), (0, 10), (0, 100)]


def test_non_numeric_strings_get_string_sort_bucket():
    assert _projection_sort_key("stage-1") == (1, "stage-1")
    assert _projection_sort_key("frame-A") == (1, "frame-A")


def test_numeric_sort_before_non_numeric_when_mixed():
    """Defined ordering when a single projection mixes shapes.

    Realistically callers don't mix shapes inside a single normaliser
    run (production = all snowflakes, tests = all semantic strings),
    but the tuple sort gives a well-defined order if they ever do.
    """
    mixed = ["stage-2", "100", "stage-1", "9"]
    sorted_mixed = sorted(mixed, key=_projection_sort_key)
    assert sorted_mixed == ["9", "100", "stage-1", "stage-2"]


def test_int_input_works_too():
    """Some callers pass int directly (not via dict.get on a JSON column)."""
    assert _projection_sort_key(42) == (0, 42)


def test_none_input_sorts_as_empty_string():
    """Defensive: a missing identifier shouldn't blow up; falls back to ''."""
    assert _projection_sort_key(None) == (1, "")
