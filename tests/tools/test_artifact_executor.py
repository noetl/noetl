import gzip
import json
from typing import Any, Optional

from noetl.core.storage.backends import StorageBackend, clear_registered_backends, register_backend
from noetl.tools.artifact.executor import execute_artifact_get


class ArtifactKvBackend(StorageBackend):
    instances: list["ArtifactKvBackend"] = []

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.items = {"payload-key": gzip.compress(json.dumps({"ok": True}).encode("utf-8"))}
        ArtifactKvBackend.instances.append(self)

    async def put(self, key: str, data: bytes, metadata: Optional[dict[str, Any]] = None) -> str:
        self.items[key] = data
        return f"nats-kv://{self.kwargs.get('bucket_name', 'bucket')}/{key}"

    async def get(self, key: str) -> bytes:
        if key not in self.items:
            raise KeyError(key)
        return self.items[key]

    async def delete(self, key: str) -> bool:
        return self.items.pop(key, None) is not None

    async def exists(self, key: str) -> bool:
        return key in self.items


def teardown_function():
    clear_registered_backends()
    ArtifactKvBackend.instances = []


def test_artifact_get_nats_kv_uses_storage_backend_registry():
    register_backend("kv", ArtifactKvBackend, replace=True)

    result = execute_artifact_get(
        {"uri": "nats-kv://custom-bucket/payload-key"},
        context={},
        jinja_env=None,
        task_with={},
    )

    assert result["status"] == "success"
    assert result["data"] == {"ok": True}
    assert result["source"] == "nats_kv"
    assert ArtifactKvBackend.instances[0].kwargs["bucket_name"] == "custom-bucket"
