"""Adapter-agnostic compliance suite for :class:`PayloadStore`.

Each test is parametrized across every registered adapter. Adding a
new adapter (GCS, Azure Blob, SeaweedFS, ...) means appending one
fixture branch — the suite is the long-term contract gate.
"""

from __future__ import annotations

from pathlib import Path
from typing import AsyncIterator

import pytest
import pytest_asyncio

from noetl.core.payload_store import (
    FilesystemPayloadStore,
    PayloadNotFound,
    PayloadReference,
    PayloadStore,
    S3PayloadStore,
    content_hash,
)

# moto + boto3 are dev deps; skip the S3 leg cleanly if either is missing
try:
    from moto import mock_aws  # type: ignore[import-not-found]
    import boto3  # type: ignore[import-not-found]

    _S3_AVAILABLE = True
except ImportError:  # pragma: no cover
    _S3_AVAILABLE = False
    mock_aws = None  # type: ignore[assignment]
    boto3 = None  # type: ignore[assignment]


_S3_BUCKET = "noetl-payload-compliance"


@pytest_asyncio.fixture(
    params=(
        "filesystem",
        pytest.param(
            "s3",
            marks=pytest.mark.skipif(
                not _S3_AVAILABLE,
                reason="moto[s3] not installed; install via `uv pip install moto[s3]`",
            ),
        ),
    )
)
async def payload_store(request, tmp_path: Path) -> AsyncIterator[PayloadStore]:
    """Yield a configured PayloadStore for the current parameter."""
    flavor = request.param
    if flavor == "filesystem":
        yield FilesystemPayloadStore(tmp_path)
        return

    # S3 leg — start the moto mock for the test's lifetime
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=_S3_BUCKET)
        yield S3PayloadStore(_S3_BUCKET, region_name="us-east-1")


@pytest.mark.asyncio
async def test_store_and_fetch_round_trip(payload_store: PayloadStore):
    payload = b"compliance: store + fetch"

    ref = await payload_store.store(payload, content_type="text/plain")

    assert isinstance(ref, PayloadReference)
    assert ref.sha256 == content_hash(payload)
    assert ref.byte_length == len(payload)
    assert ref.content_type == "text/plain"
    assert ref.uri is not None

    fetched = await payload_store.fetch(ref)
    assert fetched == payload


@pytest.mark.asyncio
async def test_content_addressing_is_deterministic(payload_store: PayloadStore):
    payload = b"compliance: deterministic"
    ref_a = await payload_store.store(payload)
    ref_b = await payload_store.store(payload)
    assert ref_a.sha256 == ref_b.sha256


@pytest.mark.asyncio
async def test_fetch_missing_raises_payload_not_found(payload_store: PayloadStore):
    bogus = PayloadReference(sha256="0" * 64, byte_length=0)
    with pytest.raises(PayloadNotFound):
        await payload_store.fetch(bogus)


@pytest.mark.asyncio
async def test_exists_reflects_state(payload_store: PayloadStore):
    payload = b"compliance: exists toggle"

    pre = PayloadReference(sha256=content_hash(payload), byte_length=len(payload))
    assert await payload_store.exists(pre) is False

    ref = await payload_store.store(payload)
    assert await payload_store.exists(ref) is True

    removed = await payload_store.delete(ref)
    assert removed is True
    assert await payload_store.exists(ref) is False


@pytest.mark.asyncio
async def test_delete_returns_false_when_missing(payload_store: PayloadStore):
    bogus = PayloadReference(sha256="1" * 64, byte_length=0)
    assert await payload_store.delete(bogus) is False


@pytest.mark.asyncio
async def test_content_type_default(payload_store: PayloadStore):
    ref = await payload_store.store(b"compliance: default content type")
    assert ref.content_type == "application/octet-stream"


@pytest.mark.asyncio
async def test_metadata_round_trip(payload_store: PayloadStore):
    """PayloadReference.metadata returned by store(...) reflects input.

    Adapter-specific persistence shape (filesystem sidecar vs S3
    object metadata header) is tested in adapter-specific files;
    the compliance suite only asserts the returned reference.
    """
    payload = b"compliance: metadata round trip"
    metadata = {"origin": "compliance", "tool": "pytest"}

    ref = await payload_store.store(
        payload, content_type="application/json", metadata=metadata
    )
    assert ref.metadata == metadata
    assert ref.content_type == "application/json"
