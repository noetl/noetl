"""Tests for ``replay_payload_ref_locator`` with the new
``kind: "payload_store"`` discriminator introduced in v2 spec Phase
5 round 5.

Existing legacy locator behavior (``ref`` / ``uri`` / ``locator``
keys, bare strings, nested ``rows_ref`` mappings) is regression-
guarded here.
"""

from __future__ import annotations

import pytest

from noetl.server.api.replay import replay_payload_ref_locator


def test_locator_extracts_uri_for_payload_store_kind():
    ref = {
        "kind": "payload_store",
        "sha256": "a" * 64,
        "byte_length": 7,
        "content_type": "text/plain",
        "uri": "gs://bucket/aa/bb/abc",
        "metadata": {},
    }
    assert replay_payload_ref_locator(ref) == "gs://bucket/aa/bb/abc"


def test_locator_falls_back_to_sha256_for_payload_store_kind_without_uri():
    ref = {
        "kind": "payload_store",
        "sha256": "c" * 64,
        "byte_length": 0,
        "uri": None,
        "metadata": {},
    }
    assert replay_payload_ref_locator(ref) == "c" * 64


def test_locator_returns_uri_when_kind_unset_legacy():
    ref = {"uri": "/tmp/foo"}
    assert replay_payload_ref_locator(ref) == "/tmp/foo"


def test_locator_returns_ref_for_legacy_temp_store_dict():
    ref = {"kind": "temp_ref", "ref": "noetl://temp/x"}
    assert replay_payload_ref_locator(ref) == "noetl://temp/x"


def test_locator_returns_none_for_empty_dict():
    assert replay_payload_ref_locator({}) is None


def test_locator_returns_string_for_bare_string_locator():
    assert replay_payload_ref_locator("some-ref") == "some-ref"


def test_locator_returns_none_for_unknown_payload_store_shape():
    """A payload_store-kind dict with no URI and no sha256 falls through
    to the legacy lookup and returns None (legacy keys are absent)."""
    ref = {"kind": "payload_store", "byte_length": 0, "metadata": {}}
    assert replay_payload_ref_locator(ref) is None


def test_locator_legacy_rows_ref_nested_mapping():
    """Regression guard: nested ``rows_ref`` extraction still works."""
    ref = {"rows_ref": {"ref": "noetl://rows/y"}}
    assert replay_payload_ref_locator(ref) == "noetl://rows/y"


@pytest.mark.parametrize("non_mapping", [None, 42, 3.14, ["a", "b"]])
def test_locator_returns_none_for_non_mapping_non_string(non_mapping):
    assert replay_payload_ref_locator(non_mapping) is None
