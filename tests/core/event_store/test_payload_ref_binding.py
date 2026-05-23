"""Tests for the :class:`EventRecord` ↔ :class:`PayloadReference`
typed binding introduced in v2 spec Phase 5 round 5.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from noetl.core.event_store import (
    PAYLOAD_REF_KIND_PAYLOAD_STORE,
    EventRecord,
    payload_ref_to_dict,
)
from noetl.core.payload_store import PayloadReference


_PAYLOAD = b"hello typed binding"
_REF = PayloadReference(
    sha256="a" * 64,
    byte_length=len(_PAYLOAD),
    content_type="text/plain",
    uri="gs://noetl-payload/aa/bb/abc",
    metadata={"origin": "test", "tenant": "default"},
)


def _record(**overrides):
    base = dict(
        event_type="frame.committed",
        stream_id="execution/1/stage/2",
        execution_id=1,
        aggregate_id="frame/3",
        aggregate_type="frame",
        result={"status": "COMPLETED"},
        meta={"row_count": 2},
        event_time=datetime(2026, 5, 22, tzinfo=timezone.utc),
    )
    base.update(overrides)
    return EventRecord(**base)


def test_envelope_serializes_payload_reference_to_canonical_dict():
    record = _record(payload_ref=_REF)
    envelope = record.envelope(stream_version=7)

    payload_ref = envelope["payload_ref"]
    assert payload_ref == {
        "kind": PAYLOAD_REF_KIND_PAYLOAD_STORE,
        "sha256": _REF.sha256,
        "byte_length": _REF.byte_length,
        "content_type": _REF.content_type,
        "uri": _REF.uri,
        "metadata": dict(_REF.metadata),
    }


def test_envelope_passes_through_legacy_dict_unchanged():
    legacy = {
        "kind": "result_ref",
        "ref": "noetl://result_ref/some-id",
        "scope": "execution",
    }
    record = _record(payload_ref=legacy)
    envelope = record.envelope(stream_version=1)

    assert envelope["payload_ref"] == legacy
    # And the dict identity is preserved (no defensive copy)
    assert envelope["payload_ref"] is legacy


def test_envelope_handles_none_payload_ref():
    record = _record(payload_ref=None)
    envelope = record.envelope(stream_version=1)

    assert "payload_ref" in envelope
    assert envelope["payload_ref"] is None


@pytest.mark.parametrize("bad_value", ["just a string", 42, ["list"], 3.14])
def test_payload_ref_to_dict_rejects_invalid_input(bad_value):
    with pytest.raises(TypeError, match="PayloadReference"):
        payload_ref_to_dict(bad_value)


def test_checksum_matches_between_payload_reference_and_dict_form():
    """A PayloadReference and its serialized dict must yield identical envelopes."""
    record_ref = _record(payload_ref=_REF)
    record_dict = _record(payload_ref=payload_ref_to_dict(_REF))

    envelope_ref = record_ref.envelope(stream_version=7)
    envelope_dict = record_dict.envelope(stream_version=7)

    assert envelope_ref["envelope_checksum"] == envelope_dict["envelope_checksum"]
    assert envelope_ref["payload_ref"] == envelope_dict["payload_ref"]


def test_payload_ref_metadata_preserved_in_envelope():
    ref = PayloadReference(
        sha256="b" * 64,
        byte_length=10,
        content_type="application/json",
        uri="s3://bucket/key",
        metadata={"origin": "frame", "tool": "python", "schema": "v1"},
    )
    record = _record(payload_ref=ref)
    envelope = record.envelope(stream_version=1)

    assert envelope["payload_ref"]["metadata"] == {
        "origin": "frame",
        "tool": "python",
        "schema": "v1",
    }


def test_payload_ref_to_dict_none_returns_none():
    assert payload_ref_to_dict(None) is None


def test_payload_ref_to_dict_passes_through_dict():
    legacy = {"kind": "temp_ref", "ref": "noetl://temp/x"}
    assert payload_ref_to_dict(legacy) is legacy


def test_payload_ref_kind_constant_value():
    """The discriminator string is part of the wire contract — guard it."""
    assert PAYLOAD_REF_KIND_PAYLOAD_STORE == "payload_store"
