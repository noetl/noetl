import sys

import pytest

from noetl.core.storage.backends import (
    MemoryBackend,
    StorageBackend,
    get_backend,
    register_backend,
    registered_backend_names,
    unregister_backend,
)


class CustomMemoryBackend(MemoryBackend):
    pass


def teardown_function():
    unregister_backend("custom")


def test_registered_backend_names_include_builtins():
    names = registered_backend_names()

    assert {"memory", "kv", "disk", "s3", "gcs"} <= set(names)
    assert tuple(sorted(names)) == names


def test_registry_helpers_are_public_storage_exports():
    from noetl.core.storage import (
        register_backend as public_register_backend,
        registered_backend_names as public_registered_backend_names,
        unregister_backend as public_unregister_backend,
    )

    assert public_register_backend is register_backend
    assert public_registered_backend_names is registered_backend_names
    assert public_unregister_backend is unregister_backend


def test_get_backend_uses_in_process_registration():
    register_backend("custom", CustomMemoryBackend)

    backend = get_backend("custom", max_size_bytes=123)

    assert isinstance(backend, CustomMemoryBackend)
    assert isinstance(backend, StorageBackend)


def test_register_backend_rejects_accidental_builtin_override():
    with pytest.raises(ValueError, match="already registered"):
        register_backend("memory", CustomMemoryBackend)

    register_backend("memory", CustomMemoryBackend, replace=True)
    try:
        assert isinstance(get_backend("memory"), CustomMemoryBackend)
    finally:
        unregister_backend("memory")


def test_get_backend_loads_env_import_hook(monkeypatch, tmp_path):
    module_path = tmp_path / "custom_storage_backend.py"
    module_path.write_text(
        "from noetl.core.storage.backends import MemoryBackend\n"
        "class PluginBackend(MemoryBackend):\n"
        "    pass\n"
        "def make_backend(**kwargs):\n"
        "    return PluginBackend(**kwargs)\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("NOETL_STORAGE_BACKEND_PLUGIN", "custom_storage_backend:make_backend")

    backend = get_backend("plugin", max_size_bytes=456)

    assert backend.__class__.__name__ == "PluginBackend"
    assert isinstance(backend, MemoryBackend)


def test_get_backend_rejects_bad_env_import_hook(monkeypatch):
    monkeypatch.setenv("NOETL_STORAGE_BACKEND_PLUGIN", "bad-spec")

    with pytest.raises(ValueError, match="module:attribute"):
        get_backend("plugin")


def test_get_backend_requires_storage_backend_return(monkeypatch, tmp_path):
    module_path = tmp_path / "bad_storage_backend.py"
    module_path.write_text("def make_backend(**kwargs):\n    return object()\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.setenv("NOETL_STORAGE_BACKEND_PLUGIN", "bad_storage_backend:make_backend")

    with pytest.raises(TypeError, match="did not return StorageBackend"):
        get_backend("plugin")


def test_get_backend_preserves_object_alias():
    backend = get_backend("object", cache_dir="/tmp/noetl-storage-registry-test")

    assert backend.__class__.__name__ == "DiskCacheBackend"


def test_no_test_plugin_modules_leak():
    assert "custom_storage_backend" not in sys.builtin_module_names
