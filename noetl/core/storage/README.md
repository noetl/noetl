# Storage Backend Registry

NoETL storage tiers are resolved through `noetl.core.storage.get_backend`.
Built-in tiers remain `memory`, `kv`, `disk`, `s3`, and `gcs`; the
deprecated `object` tier is still mapped to `disk`.

Custom backends can be installed in either of two ways:

1. Register in process:

```python
from noetl.core.storage import StorageBackend, register_backend


class AzureBlobBackend(StorageBackend):
    ...


register_backend("azure-blob", AzureBlobBackend)
```

2. Use an import hook:

```shell
NOETL_STORAGE_BACKEND_AZURE_BLOB=package.module:factory
```

The factory receives keyword arguments from the caller and must return a
`StorageBackend` instance. It may be a class or a function. To override a
built-in tier intentionally, call `register_backend("s3", factory,
replace=True)` or set the corresponding environment variable, for example
`NOETL_STORAGE_BACKEND_S3=package.module:factory`.

`TempStore`, `artifact.get`, and agent result fallback resolution resolve
KV/S3/GCS/DISK access through the registry, so plugin backends participate in
normal result storage, resolution, cleanup, `nats-kv://` artifact reads, and
direct disk ref hydration.
