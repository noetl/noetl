"""GCS-specific tests for :class:`GCSPayloadStore`.

The compliance suite in ``test_compliance.py`` does not yet cover GCS
(there is no in-process equivalent of ``moto.mock_aws`` for GCS;
``fake-gcs-server`` is a process-based emulator). This file exercises
the adapter's call shape against the ``google.cloud.storage`` SDK
surface using ``unittest.mock``.

Cases:

- constructor honors an injected client (no real ``Client()`` call)
- ``store`` calls ``upload_from_string`` with the right ``content_type``
- ``store`` writes ``blob.metadata`` before uploading
- ``store`` dedups via ``blob.exists()`` (no second ``upload_from_string``)
- ``fetch`` translates ``google.api_core.exceptions.NotFound`` into
  :class:`PayloadNotFound`
- ``exists`` passes through to ``blob.exists()``
- ``delete`` returns ``False`` when the blob is missing
- ``delete`` returns ``True`` when the blob existed
- key layout matches the filesystem + S3 sharding
- prefix normalization strips leading / trailing slashes
- URI uses the ``gs://`` scheme
- non-ASCII metadata raises ``ValueError``
- a missing-bucket error from ``upload_from_string`` propagates
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from google.api_core import exceptions as gax_exceptions

from noetl.core.payload_store import (
    GCSPayloadStore,
    PayloadNotFound,
    PayloadReference,
    content_hash,
)

_BUCKET = "noetl-payload-gcs"


def _make_store(
    *,
    blob: MagicMock | None = None,
    bucket: MagicMock | None = None,
    client: MagicMock | None = None,
    prefix: str = "",
) -> tuple[GCSPayloadStore, MagicMock, MagicMock, MagicMock]:
    """Build a ``GCSPayloadStore`` wired to a mocked client chain.

    Returns ``(store, client, bucket, blob)``.
    """
    blob = blob or MagicMock(name="Blob")
    bucket = bucket or MagicMock(name="Bucket")
    bucket.blob.return_value = blob
    client = client or MagicMock(name="Client")
    client.bucket.return_value = bucket
    store = GCSPayloadStore(_BUCKET, prefix=prefix, client=client)
    return store, client, bucket, blob


def test_constructor_uses_injected_client():
    client = MagicMock(name="Client")
    bucket = MagicMock(name="Bucket")
    client.bucket.return_value = bucket

    store = GCSPayloadStore(_BUCKET, client=client)

    # bucket() was queried for our bucket name on the injected client
    client.bucket.assert_called_once_with(_BUCKET)
    assert store.bucket is bucket
    assert store.client is client


def test_constructor_rejects_empty_bucket():
    with pytest.raises(ValueError, match="bucket name"):
        GCSPayloadStore("")


@pytest.mark.asyncio
async def test_store_uploads_via_blob_with_metadata():
    store, _, bucket, blob = _make_store()
    blob.exists.return_value = False  # not deduped

    payload = b"upload-shape"
    metadata = {"origin": "test", "tenant": "default"}

    ref = await store.store(
        payload, content_type="application/json", metadata=metadata
    )

    # The bucket was asked for the right key
    sha = content_hash(payload)
    expected_key = f"{sha[:2]}/{sha[2:4]}/{sha}"
    bucket.blob.assert_called_with(expected_key)

    # Custom metadata was assigned before upload
    assert blob.metadata == metadata

    # upload_from_string carries the data + content type
    blob.upload_from_string.assert_called_once_with(
        payload, content_type="application/json"
    )

    # Returned reference carries the full shape
    assert ref.sha256 == sha
    assert ref.byte_length == len(payload)
    assert ref.content_type == "application/json"
    assert ref.uri == f"gs://{_BUCKET}/{expected_key}"
    assert ref.metadata == metadata


@pytest.mark.asyncio
async def test_store_dedups_when_blob_exists():
    store, _, _, blob = _make_store()
    blob.exists.return_value = True  # already there → dedup

    await store.store(b"dedup-target")

    blob.upload_from_string.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_raises_payload_not_found_on_gcs_404():
    store, _, _, blob = _make_store()
    blob.download_as_bytes.side_effect = gax_exceptions.NotFound("missing")

    payload = b"never-stored"
    ref = PayloadReference(
        sha256=content_hash(payload), byte_length=len(payload)
    )

    with pytest.raises(PayloadNotFound):
        await store.fetch(ref)


@pytest.mark.asyncio
async def test_fetch_returns_blob_bytes():
    store, _, _, blob = _make_store()
    payload = b"fetched-from-gcs"
    blob.download_as_bytes.return_value = payload

    ref = PayloadReference(
        sha256=content_hash(payload), byte_length=len(payload)
    )
    assert await store.fetch(ref) == payload


@pytest.mark.asyncio
@pytest.mark.parametrize("present", [True, False])
async def test_exists_passes_through_blob_exists(present: bool):
    store, _, _, blob = _make_store()
    blob.exists.return_value = present

    ref = PayloadReference(sha256="0" * 64, byte_length=0)
    assert await store.exists(ref) is present


@pytest.mark.asyncio
async def test_delete_returns_false_on_missing_blob():
    store, _, _, blob = _make_store()
    blob.exists.return_value = False

    ref = PayloadReference(sha256="0" * 64, byte_length=0)
    assert await store.delete(ref) is False
    blob.delete.assert_not_called()


@pytest.mark.asyncio
async def test_delete_returns_true_on_existing_blob():
    store, _, _, blob = _make_store()
    blob.exists.return_value = True

    ref = PayloadReference(sha256="0" * 64, byte_length=0)
    assert await store.delete(ref) is True
    blob.delete.assert_called_once()


@pytest.mark.asyncio
async def test_key_layout_matches_filesystem_sharding():
    store, _, bucket, blob = _make_store()
    blob.exists.return_value = False

    payload = b"key layout"
    ref = await store.store(payload)
    sha = content_hash(payload)

    assert ref.uri is not None
    assert ref.uri.endswith(f"{sha[0:2]}/{sha[2:4]}/{sha}")
    assert ref.uri == f"gs://{_BUCKET}/{sha[0:2]}/{sha[2:4]}/{sha}"
    bucket.blob.assert_any_call(f"{sha[0:2]}/{sha[2:4]}/{sha}")


@pytest.mark.asyncio
async def test_prefix_normalization():
    store, _, bucket, blob = _make_store(prefix="/payloads/")
    blob.exists.return_value = False

    payload = b"prefixed"
    ref = await store.store(payload)
    sha = content_hash(payload)

    expected_key = f"payloads/{sha[0:2]}/{sha[2:4]}/{sha}"
    assert ref.uri == f"gs://{_BUCKET}/{expected_key}"
    bucket.blob.assert_any_call(expected_key)


@pytest.mark.asyncio
async def test_uri_is_gs_scheme():
    store, _, _, blob = _make_store()
    blob.exists.return_value = False

    ref = await store.store(b"scheme-check")
    assert ref.uri is not None
    assert ref.uri.startswith(f"gs://{_BUCKET}/")


@pytest.mark.asyncio
async def test_metadata_validation_rejects_non_ascii():
    store, _, _, blob = _make_store()
    blob.exists.return_value = False

    with pytest.raises(ValueError, match="ASCII"):
        await store.store(b"data", metadata={"key": "vä lue"})


@pytest.mark.asyncio
async def test_missing_bucket_propagates_error():
    store, _, _, blob = _make_store()
    blob.exists.return_value = False
    blob.upload_from_string.side_effect = gax_exceptions.NotFound(
        "bucket does not exist"
    )

    with pytest.raises(gax_exceptions.NotFound):
        await store.store(b"oops")
