from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from noetl.core.payload_store import (
    FilesystemPayloadStore,
    PayloadNotFound,
    PayloadReference,
    content_hash,
)


@pytest.mark.asyncio
async def test_store_and_fetch_round_trip(tmp_path: Path):
    store = FilesystemPayloadStore(tmp_path)
    payload = b"hello chemistry cloud"

    ref = await store.store(payload, content_type="text/plain")

    assert ref.sha256 == content_hash(payload)
    assert ref.byte_length == len(payload)
    assert ref.content_type == "text/plain"
    assert ref.uri is not None and ref.uri.endswith(ref.sha256)

    fetched = await store.fetch(ref)
    assert fetched == payload


@pytest.mark.asyncio
async def test_content_addressing_is_deterministic(tmp_path: Path):
    store = FilesystemPayloadStore(tmp_path)
    payload = b"deterministic"

    ref_a = await store.store(payload)
    ref_b = await store.store(payload)

    assert ref_a.sha256 == ref_b.sha256
    # Only one physical blob on disk
    matches = list(tmp_path.rglob(ref_a.sha256))
    # the blob file itself
    blob_files = [p for p in matches if p.is_file() and not p.name.endswith(".meta.json")]
    assert len(blob_files) == 1


@pytest.mark.asyncio
async def test_store_skips_write_when_blob_exists(tmp_path: Path):
    store = FilesystemPayloadStore(tmp_path)
    payload = b"dedup-test"

    ref = await store.store(payload)
    blob_path = Path(ref.uri)
    first_mtime = blob_path.stat().st_mtime_ns

    # Sleep beyond mtime granularity, store again — mtime must not change
    time.sleep(0.05)
    await store.store(payload)
    second_mtime = blob_path.stat().st_mtime_ns

    assert first_mtime == second_mtime


@pytest.mark.asyncio
async def test_atomic_write_temp_file_cleanup(tmp_path: Path):
    store = FilesystemPayloadStore(tmp_path)
    await store.store(b"atomic")

    leftover = [p for p in tmp_path.rglob(".tmp-*") if p.is_file()]
    assert leftover == []


@pytest.mark.asyncio
async def test_fetch_missing_raises_payload_not_found(tmp_path: Path):
    store = FilesystemPayloadStore(tmp_path)
    bogus_sha = "0" * 64
    ref = PayloadReference(
        sha256=bogus_sha,
        byte_length=0,
    )
    with pytest.raises(PayloadNotFound):
        await store.fetch(ref)


@pytest.mark.asyncio
async def test_exists_reflects_state(tmp_path: Path):
    store = FilesystemPayloadStore(tmp_path)
    payload = b"toggle"

    # Before store: reference exists() is False
    bogus_ref = PayloadReference(
        sha256=content_hash(payload),
        byte_length=len(payload),
    )
    assert await store.exists(bogus_ref) is False

    real_ref = await store.store(payload)
    assert await store.exists(real_ref) is True

    deleted = await store.delete(real_ref)
    assert deleted is True
    assert await store.exists(real_ref) is False


@pytest.mark.asyncio
async def test_delete_returns_false_when_missing(tmp_path: Path):
    store = FilesystemPayloadStore(tmp_path)
    bogus_ref = PayloadReference(
        sha256="1" * 64,
        byte_length=0,
    )
    assert await store.delete(bogus_ref) is False


@pytest.mark.asyncio
async def test_metadata_sidecar_round_trip(tmp_path: Path):
    store = FilesystemPayloadStore(tmp_path)
    payload = b"with-metadata"
    metadata = {"origin": "test", "tool": "python"}

    ref = await store.store(payload, content_type="application/json", metadata=metadata)

    assert ref.metadata == metadata
    sidecar_path = Path(ref.uri + ".meta.json")
    assert sidecar_path.exists()

    parsed = json.loads(sidecar_path.read_text())
    assert parsed["content_type"] == "application/json"
    assert parsed["metadata"] == metadata
    assert parsed["byte_length"] == len(payload)
    assert isinstance(parsed["created_at"], str)


@pytest.mark.asyncio
async def test_content_type_default(tmp_path: Path):
    store = FilesystemPayloadStore(tmp_path)
    ref = await store.store(b"default-type")
    assert ref.content_type == "application/octet-stream"


@pytest.mark.asyncio
async def test_delete_also_removes_sidecar(tmp_path: Path):
    store = FilesystemPayloadStore(tmp_path)
    payload = b"with-sidecar"
    ref = await store.store(payload, metadata={"k": "v"})

    sidecar = Path(ref.uri + ".meta.json")
    assert sidecar.exists()

    assert await store.delete(ref) is True
    assert sidecar.exists() is False


@pytest.mark.asyncio
async def test_sharded_layout_uses_sha_prefix(tmp_path: Path):
    """Default shard_depth=2, shard_width=2 → <root>/<sha[:2]>/<sha[2:4]>/<sha>."""
    store = FilesystemPayloadStore(tmp_path)
    ref = await store.store(b"sharded")
    blob = Path(ref.uri)
    relative = blob.relative_to(tmp_path)
    parts = relative.parts
    assert len(parts) == 3
    assert parts[0] == ref.sha256[:2]
    assert parts[1] == ref.sha256[2:4]
    assert parts[2] == ref.sha256


@pytest.mark.asyncio
async def test_constructor_rejects_invalid_shard_config(tmp_path: Path):
    with pytest.raises(ValueError):
        FilesystemPayloadStore(tmp_path, shard_depth=-1)
    with pytest.raises(ValueError):
        FilesystemPayloadStore(tmp_path, shard_width=0)
    with pytest.raises(ValueError):
        FilesystemPayloadStore(tmp_path, shard_depth=20, shard_width=4)


def test_content_hash_rejects_non_bytes():
    with pytest.raises(TypeError):
        content_hash("not bytes")  # type: ignore[arg-type]


def test_content_hash_is_stable():
    assert content_hash(b"abc") == content_hash(b"abc")
    assert content_hash(b"abc") != content_hash(b"abd")
