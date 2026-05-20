from __future__ import annotations

from typing import Any, Optional

import pytest

from noetl.core.storage.backends import StorageBackend, clear_registered_backends, register_backend
from noetl.core.storage.models import ResultRefMeta, Scope, StoreTier, TempRef
from noetl.core.storage.result_store import TempStore


class RegistryBackend(StorageBackend):
    instances: list["RegistryBackend"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.items: dict[str, bytes] = {}
        self.put_calls = 0
        self.get_calls = 0
        self.delete_calls = 0
        RegistryBackend.instances.append(self)

    async def put(self, key: str, data: bytes, metadata: Optional[dict[str, Any]] = None) -> str:
        self.put_calls += 1
        self.items[key] = data
        return f"registry://{key}"

    async def get(self, key: str) -> bytes:
        self.get_calls += 1
        if key not in self.items:
            raise KeyError(key)
        return self.items[key]

    async def delete(self, key: str) -> bool:
        self.delete_calls += 1
        return self.items.pop(key, None) is not None

    async def exists(self, key: str) -> bool:
        return key in self.items


class DiskRegistryBackend(RegistryBackend):
    pass


def setup_function():
    RegistryBackend.instances = []


def teardown_function():
    clear_registered_backends()


def _temp_ref(store: StoreTier = StoreTier.KV) -> TempRef:
    return TempRef(
        ref="noetl://execution/123/result/load/abcd",
        store=store,
        scope=Scope.EXECUTION,
        meta=ResultRefMeta(content_type="application/json", bytes=13),
    )


@pytest.mark.asyncio
async def test_temp_store_uses_registry_for_kv_roundtrip_and_delete():
    register_backend("kv", RegistryBackend, replace=True)
    store = TempStore()
    ref = _temp_ref(StoreTier.KV)

    uri = await store._store_data(ref, b'{"ok": true}')
    assert uri == "registry://execution_123_result_load_abcd"
    assert await store._retrieve_data_bytes(ref) == b'{"ok": true}'

    await store._delete_data(ref)
    backend = RegistryBackend.instances[0]
    assert backend.put_calls == 1
    assert backend.get_calls == 1
    assert backend.delete_calls == 1


@pytest.mark.asyncio
async def test_temp_store_direct_fetch_uses_registry_backend():
    register_backend("kv", RegistryBackend, replace=True)
    store = TempStore()
    key = "execution_123_result_load_abcd"
    backend = store._backend_for_tier(StoreTier.KV)
    await backend.put(key, b'{"direct": true}')

    assert await store._fetch_direct("noetl://execution/123/result/load/abcd") == {"direct": True}


@pytest.mark.asyncio
async def test_temp_store_uses_registry_for_cloud_tiers():
    register_backend("s3", RegistryBackend, replace=True)
    register_backend("gcs", RegistryBackend, replace=True)
    store = TempStore()

    s3_ref = _temp_ref(StoreTier.S3)
    gcs_ref = _temp_ref(StoreTier.GCS)
    await store._store_data(s3_ref, b'{"s3": true}')
    await store._store_data(gcs_ref, b'{"gcs": true}')

    assert await store._retrieve_data_bytes(s3_ref) == b'{"s3": true}'
    assert await store._retrieve_data_bytes(gcs_ref) == b'{"gcs": true}'


@pytest.mark.asyncio
async def test_temp_store_disk_backend_receives_registry_cloud_spill():
    register_backend("s3", RegistryBackend, replace=True)
    register_backend("disk", DiskRegistryBackend, replace=True)
    store = TempStore()

    backend = await store._get_or_init_disk_backend()

    assert isinstance(backend, DiskRegistryBackend)
    assert isinstance(backend.kwargs["cloud_backend"], RegistryBackend)
