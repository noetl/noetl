"""Azure Blob–specific tests for :class:`AzureBlobPayloadStore`.

The compliance suite in ``test_compliance.py`` does not yet cover
Azure (Azurite is a process-based emulator, not an in-process
mock library). This file exercises the adapter's call shape
against the ``azure-storage-blob`` SDK surface using
``unittest.mock``.

Cases:

- constructor honors an injected client (no real ``BlobServiceClient`` call)
- constructor rejects an empty container name
- constructor requires one of: client / connection_string / account_url
- ``store`` calls ``upload_blob`` with the right
  ``ContentSettings(content_type=...)`` and metadata
- ``store`` dedups via ``BlobClient.exists()``
- ``fetch`` translates ``ResourceNotFoundError`` into
  :class:`PayloadNotFound`
- ``fetch`` returns the underlying blob bytes on the happy path
- ``exists`` passes through to ``BlobClient.exists()``
- ``delete`` returns ``False`` when the blob is missing
- ``delete`` returns ``True`` when the blob existed
- key layout matches the filesystem + S3 + GCS sharding
- prefix normalization strips leading / trailing slashes
- URI uses the ``azure://`` scheme
- non-ASCII metadata values raise ``ValueError``
- non-identifier metadata keys raise ``ValueError``
- a missing-container error from ``upload_blob`` propagates
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from azure.core.exceptions import ResourceNotFoundError
from azure.storage.blob import ContentSettings

from noetl.core.payload_store import (
    AzureBlobPayloadStore,
    PayloadNotFound,
    PayloadReference,
    content_hash,
)

_CONTAINER = "noetl-payload-azure"
_ACCOUNT = "noetlacct"


def _make_store(
    *,
    blob: MagicMock | None = None,
    container_client: MagicMock | None = None,
    client: MagicMock | None = None,
    prefix: str = "",
) -> tuple[AzureBlobPayloadStore, MagicMock, MagicMock, MagicMock]:
    """Build an ``AzureBlobPayloadStore`` wired to a mocked client chain.

    Returns ``(store, client, container_client, blob)``.
    """
    blob = blob or MagicMock(name="BlobClient")
    container_client = container_client or MagicMock(name="ContainerClient")
    container_client.get_blob_client.return_value = blob
    client = client or MagicMock(name="BlobServiceClient")
    client.get_container_client.return_value = container_client
    client.account_name = _ACCOUNT
    store = AzureBlobPayloadStore(_CONTAINER, prefix=prefix, client=client)
    return store, client, container_client, blob


def test_constructor_uses_injected_client():
    client = MagicMock(name="BlobServiceClient")
    container_client = MagicMock(name="ContainerClient")
    client.get_container_client.return_value = container_client

    store = AzureBlobPayloadStore(_CONTAINER, client=client)

    client.get_container_client.assert_called_once_with(_CONTAINER)
    assert store.container_client is container_client
    assert store.client is client


def test_constructor_rejects_empty_container():
    with pytest.raises(ValueError, match="container name"):
        AzureBlobPayloadStore("")


def test_constructor_requires_auth_source():
    with pytest.raises(ValueError, match="connection_string"):
        AzureBlobPayloadStore(_CONTAINER)


@pytest.mark.asyncio
async def test_store_uploads_via_blob_with_metadata():
    store, _, container_client, blob = _make_store()
    blob.exists.return_value = False  # not deduped

    payload = b"upload-shape"
    metadata = {"origin": "test", "tenant": "default"}

    ref = await store.store(
        payload, content_type="application/json", metadata=metadata
    )

    sha = content_hash(payload)
    expected_key = f"{sha[:2]}/{sha[2:4]}/{sha}"
    container_client.get_blob_client.assert_called_with(expected_key)

    blob.upload_blob.assert_called_once()
    call = blob.upload_blob.call_args
    # First positional argument is the payload bytes
    assert call.args[0] == payload
    # ContentSettings carries the content type
    content_settings = call.kwargs["content_settings"]
    assert isinstance(content_settings, ContentSettings)
    assert content_settings.content_type == "application/json"
    # Metadata dict is passed through
    assert call.kwargs["metadata"] == metadata

    # Returned reference carries the full shape
    assert ref.sha256 == sha
    assert ref.byte_length == len(payload)
    assert ref.content_type == "application/json"
    assert ref.uri == f"azure://{_ACCOUNT}/{_CONTAINER}/{expected_key}"
    assert ref.metadata == metadata


@pytest.mark.asyncio
async def test_store_dedups_when_blob_exists():
    store, _, _, blob = _make_store()
    blob.exists.return_value = True  # already there → dedup

    await store.store(b"dedup-target")

    blob.upload_blob.assert_not_called()


@pytest.mark.asyncio
async def test_fetch_raises_payload_not_found_on_azure_404():
    store, _, _, blob = _make_store()
    blob.download_blob.side_effect = ResourceNotFoundError("missing")

    payload = b"never-stored"
    ref = PayloadReference(
        sha256=content_hash(payload), byte_length=len(payload)
    )

    with pytest.raises(PayloadNotFound):
        await store.fetch(ref)


@pytest.mark.asyncio
async def test_fetch_returns_blob_bytes():
    store, _, _, blob = _make_store()
    payload = b"fetched-from-azure"
    stream = MagicMock(name="StorageStreamDownloader")
    stream.readall.return_value = payload
    blob.download_blob.return_value = stream

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
    blob.delete_blob.assert_not_called()


@pytest.mark.asyncio
async def test_delete_returns_true_on_existing_blob():
    store, _, _, blob = _make_store()
    blob.exists.return_value = True

    ref = PayloadReference(sha256="0" * 64, byte_length=0)
    assert await store.delete(ref) is True
    blob.delete_blob.assert_called_once()


@pytest.mark.asyncio
async def test_key_layout_matches_filesystem_sharding():
    store, _, container_client, blob = _make_store()
    blob.exists.return_value = False

    payload = b"key layout"
    ref = await store.store(payload)
    sha = content_hash(payload)

    assert ref.uri is not None
    assert ref.uri.endswith(f"{sha[0:2]}/{sha[2:4]}/{sha}")
    assert ref.uri == f"azure://{_ACCOUNT}/{_CONTAINER}/{sha[0:2]}/{sha[2:4]}/{sha}"
    container_client.get_blob_client.assert_any_call(
        f"{sha[0:2]}/{sha[2:4]}/{sha}"
    )


@pytest.mark.asyncio
async def test_prefix_normalization():
    store, _, container_client, blob = _make_store(prefix="/payloads/")
    blob.exists.return_value = False

    payload = b"prefixed"
    ref = await store.store(payload)
    sha = content_hash(payload)

    expected_key = f"payloads/{sha[0:2]}/{sha[2:4]}/{sha}"
    assert ref.uri == f"azure://{_ACCOUNT}/{_CONTAINER}/{expected_key}"
    container_client.get_blob_client.assert_any_call(expected_key)


@pytest.mark.asyncio
async def test_uri_is_azure_scheme():
    store, _, _, blob = _make_store()
    blob.exists.return_value = False

    ref = await store.store(b"scheme-check")
    assert ref.uri is not None
    assert ref.uri.startswith(f"azure://{_ACCOUNT}/{_CONTAINER}/")


@pytest.mark.asyncio
async def test_uri_falls_back_when_account_name_missing():
    client = MagicMock(name="BlobServiceClient")
    container_client = MagicMock(name="ContainerClient")
    blob = MagicMock(name="BlobClient")
    blob.exists.return_value = False
    container_client.get_blob_client.return_value = blob
    client.get_container_client.return_value = container_client
    # Explicitly drop account_name attribute
    client.account_name = None

    store = AzureBlobPayloadStore(_CONTAINER, client=client)
    ref = await store.store(b"no-account")
    assert ref.uri is not None
    assert ref.uri.startswith(f"azure://{_CONTAINER}/")


@pytest.mark.asyncio
async def test_metadata_validation_rejects_non_ascii_value():
    store, _, _, blob = _make_store()
    blob.exists.return_value = False

    with pytest.raises(ValueError, match="ASCII"):
        await store.store(b"data", metadata={"key": "vä lue"})


@pytest.mark.asyncio
@pytest.mark.parametrize("bad_key", ["my-key", "1bad", "bad.key", "with space"])
async def test_metadata_key_rejects_invalid_identifier(bad_key: str):
    store, _, _, blob = _make_store()
    blob.exists.return_value = False

    with pytest.raises(ValueError, match="C# identifier"):
        await store.store(b"data", metadata={bad_key: "value"})


@pytest.mark.asyncio
async def test_missing_container_propagates_error():
    store, _, _, blob = _make_store()
    blob.exists.return_value = False
    blob.upload_blob.side_effect = ResourceNotFoundError(
        "container does not exist"
    )

    with pytest.raises(ResourceNotFoundError):
        await store.store(b"oops")
