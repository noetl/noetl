"""S3-specific tests for :class:`S3PayloadStore`.

Cross-adapter behavior is covered by the compliance suite in
``test_compliance.py``. This file exercises shape that's specific to
the S3 backend: key layout, prefix handling, dedup-skipping the PUT,
non-ASCII metadata rejection, URI scheme, and missing-bucket
propagation.
"""

from __future__ import annotations

from typing import AsyncIterator

import pytest
import pytest_asyncio

from noetl.core.payload_store import (
    PayloadReference,
    S3PayloadStore,
    content_hash,
)

# Skip cleanly if moto isn't installed (CI environments without dev extras)
moto = pytest.importorskip("moto", reason="moto[s3] is required for the S3 adapter tests")
boto3 = pytest.importorskip("boto3", reason="boto3 is required for the S3 adapter tests")

mock_aws = moto.mock_aws

_BUCKET = "noetl-payload-s3"


@pytest_asyncio.fixture
async def s3_store() -> AsyncIterator[S3PayloadStore]:
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=_BUCKET)
        yield S3PayloadStore(_BUCKET, region_name="us-east-1")


@pytest.mark.asyncio
async def test_key_layout_matches_filesystem_sharding(s3_store: S3PayloadStore):
    payload = b"key layout"
    ref = await s3_store.store(payload)
    sha = content_hash(payload)
    assert ref.uri is not None
    assert ref.uri.endswith(f"{sha[0:2]}/{sha[2:4]}/{sha}")
    assert ref.uri == f"s3://{_BUCKET}/{sha[0:2]}/{sha[2:4]}/{sha}"


@pytest.mark.asyncio
async def test_prefix_is_respected():
    with mock_aws():
        boto3.client("s3", region_name="us-east-1").create_bucket(Bucket=_BUCKET)
        store = S3PayloadStore(_BUCKET, prefix="payloads/", region_name="us-east-1")
        payload = b"prefixed"
        ref = await store.store(payload)
        sha = content_hash(payload)
        # Leading + trailing slashes on the prefix are normalized away
        expected_key = f"payloads/{sha[0:2]}/{sha[2:4]}/{sha}"
        assert ref.uri == f"s3://{_BUCKET}/{expected_key}"

        # Verify the key actually landed at the prefixed path
        boto3.client("s3", region_name="us-east-1").head_object(
            Bucket=_BUCKET, Key=expected_key
        )


@pytest.mark.asyncio
async def test_dedup_skips_put_when_object_exists(s3_store: S3PayloadStore):
    payload = b"dedup-target"
    # First store admits the object
    await s3_store.store(payload)

    # Wrap put_object on the underlying client to count invocations
    real_put = s3_store.client.put_object
    put_calls = {"count": 0}

    def _spy_put(**kwargs):
        put_calls["count"] += 1
        return real_put(**kwargs)

    s3_store.client.put_object = _spy_put  # type: ignore[method-assign]

    # Re-store the same payload — put_object should be skipped (dedup)
    await s3_store.store(payload)
    assert put_calls["count"] == 0, "dedup path invoked PutObject"

    # Storing a different payload still PUTs
    await s3_store.store(b"different-payload")
    assert put_calls["count"] == 1


@pytest.mark.asyncio
async def test_metadata_validation_rejects_non_ascii(s3_store: S3PayloadStore):
    with pytest.raises(ValueError, match="ASCII"):
        await s3_store.store(b"data", metadata={"key": "vä lue"})


@pytest.mark.asyncio
async def test_uri_is_s3_scheme(s3_store: S3PayloadStore):
    ref = await s3_store.store(b"scheme-check")
    assert ref.uri is not None
    assert ref.uri.startswith(f"s3://{_BUCKET}/")


@pytest.mark.asyncio
async def test_missing_bucket_raises():
    """Storing against a non-existent bucket propagates boto3's ClientError."""
    from botocore.exceptions import ClientError

    with mock_aws():
        # Intentionally do not create the bucket
        store = S3PayloadStore("nonexistent-bucket-xyz", region_name="us-east-1")
        with pytest.raises(ClientError):
            await store.store(b"oops")


def test_constructor_rejects_empty_bucket():
    with pytest.raises(ValueError, match="bucket name"):
        S3PayloadStore("")


@pytest.mark.asyncio
async def test_object_metadata_round_trips_through_s3(s3_store: S3PayloadStore):
    """S3 stores metadata as object headers; verify they come back on HeadObject."""
    payload = b"metadata-on-s3"
    metadata = {"origin": "test", "tenant": "default"}
    ref = await s3_store.store(payload, metadata=metadata)

    # Round-trip via raw boto3 (mocked) — the S3 object should carry
    # the metadata keys we passed (S3 lowercases them internally but the
    # API surface preserves what we sent).
    client = boto3.client("s3", region_name="us-east-1")
    key = ref.uri.replace(f"s3://{_BUCKET}/", "")
    head = client.head_object(Bucket=_BUCKET, Key=key)
    returned = head["Metadata"]
    # S3 returns metadata keys lowercased; compare case-insensitively
    assert {k.lower(): v for k, v in returned.items()} == {
        k.lower(): v for k, v in metadata.items()
    }
