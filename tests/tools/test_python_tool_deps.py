"""Tests for the _resolve_deps hot-pluggable dependency mechanism."""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

# Pre-import to break circular init chain (same pattern as test_agent_executor.py).
import noetl.worker.auth_resolver  # noqa: F401
from noetl.tools.python.executor import _resolve_deps, _venv_site_packages, _venv_python


# ---------------------------------------------------------------------------
# _venv_site_packages
# ---------------------------------------------------------------------------


def test_venv_site_packages_unix_layout(tmp_path):
    site = tmp_path / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    result = _venv_site_packages(str(tmp_path))
    assert result == str(site)


def test_venv_site_packages_windows_layout(tmp_path):
    site = tmp_path / "Lib" / "site-packages"
    site.mkdir(parents=True)
    result = _venv_site_packages(str(tmp_path))
    assert result == str(site)


def test_venv_site_packages_missing(tmp_path):
    assert _venv_site_packages(str(tmp_path)) is None


# ---------------------------------------------------------------------------
# _venv_python
# ---------------------------------------------------------------------------


def test_venv_python_returns_bin_python_when_present(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    py = bin_dir / "python"
    py.write_text("#!/usr/bin/env python3")
    result = _venv_python(str(tmp_path))
    assert result == str(py)


def test_venv_python_fallback(tmp_path):
    result = _venv_python(str(tmp_path))
    assert result == str(tmp_path / "bin" / "python")


# ---------------------------------------------------------------------------
# _resolve_deps — skip guard
# ---------------------------------------------------------------------------


def test_resolve_deps_skipped_by_env_var(monkeypatch):
    monkeypatch.setenv("NOETL_SKIP_DEPS_RESOLUTION", "true")
    # Should not touch sys.path at all
    before = list(sys.path)
    _resolve_deps({"sys_path": ["/nonexistent/path"]})
    assert sys.path == before


def test_resolve_deps_none_is_noop():
    before = list(sys.path)
    _resolve_deps(None)
    assert sys.path == before


def test_resolve_deps_empty_dict_is_noop():
    before = list(sys.path)
    _resolve_deps({})
    assert sys.path == before


# ---------------------------------------------------------------------------
# _resolve_deps — sys_path
# ---------------------------------------------------------------------------


def test_resolve_deps_sys_path_injects_existing(tmp_path, monkeypatch):
    monkeypatch.delenv("NOETL_SKIP_DEPS_RESOLUTION", raising=False)
    target = str(tmp_path)
    if target in sys.path:
        sys.path.remove(target)
    try:
        _resolve_deps({"sys_path": [target]})
        assert sys.path[0] == target
    finally:
        if target in sys.path:
            sys.path.remove(target)


def test_resolve_deps_sys_path_skips_missing(monkeypatch, caplog):
    monkeypatch.delenv("NOETL_SKIP_DEPS_RESOLUTION", raising=False)
    missing = "/definitely/does/not/exist/12345"
    before = list(sys.path)
    _resolve_deps({"sys_path": [missing]})
    assert missing not in sys.path
    assert sys.path == before


def test_resolve_deps_sys_path_not_duplicated(tmp_path, monkeypatch):
    monkeypatch.delenv("NOETL_SKIP_DEPS_RESOLUTION", raising=False)
    target = str(tmp_path)
    if target not in sys.path:
        sys.path.insert(0, target)
    original_count = sys.path.count(target)
    try:
        _resolve_deps({"sys_path": [target]})
        assert sys.path.count(target) == original_count
    finally:
        while target in sys.path:
            sys.path.remove(target)


# ---------------------------------------------------------------------------
# _resolve_deps — venv_path
# ---------------------------------------------------------------------------


def test_resolve_deps_venv_path_injects_site_packages(tmp_path, monkeypatch):
    monkeypatch.delenv("NOETL_SKIP_DEPS_RESOLUTION", raising=False)
    site = tmp_path / "lib" / "python3.12" / "site-packages"
    site.mkdir(parents=True)
    site_str = str(site)
    if site_str in sys.path:
        sys.path.remove(site_str)
    try:
        _resolve_deps({"venv_path": str(tmp_path)})
        assert site_str in sys.path
    finally:
        if site_str in sys.path:
            sys.path.remove(site_str)


def test_resolve_deps_venv_path_missing_raises(monkeypatch):
    monkeypatch.delenv("NOETL_SKIP_DEPS_RESOLUTION", raising=False)
    with pytest.raises(RuntimeError, match="venv_path does not exist"):
        _resolve_deps({"venv_path": "/this/does/not/exist/at/all"})


# ---------------------------------------------------------------------------
# _resolve_deps — packages (mocked subprocess + venv.create)
# ---------------------------------------------------------------------------


def test_resolve_deps_packages_creates_venv_and_installs(tmp_path, monkeypatch):
    monkeypatch.delenv("NOETL_SKIP_DEPS_RESOLUTION", raising=False)
    monkeypatch.setenv("NOETL_TENANT_ENVS_DIR", str(tmp_path))

    tenant_venv_dir = tmp_path / "my-tenant"
    # site-packages will be created after venv.create mock
    site_pkgs = tenant_venv_dir / "lib" / "python3.12" / "site-packages"

    def fake_venv_create(path, **kwargs):
        os.makedirs(str(site_pkgs), exist_ok=True)
        py_bin = os.path.join(path, "bin", "python")
        os.makedirs(os.path.dirname(py_bin), exist_ok=True)
        open(py_bin, "w").close()

    mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    site_str = str(site_pkgs)

    with patch("noetl.tools.python.executor.venv.create", side_effect=fake_venv_create), \
         patch("noetl.tools.python.executor.subprocess.run", mock_run):
        if site_str in sys.path:
            sys.path.remove(site_str)
        try:
            _resolve_deps({"packages": {"my-tenant": ["rdkit>=2024.03.1", "meeko>=0.5.0"]}})
            assert site_str in sys.path
            mock_run.assert_called_once()
            call_args = mock_run.call_args[0][0]
            assert "rdkit>=2024.03.1" in call_args
            assert "meeko>=0.5.0" in call_args
        finally:
            if site_str in sys.path:
                sys.path.remove(site_str)


def test_resolve_deps_packages_reuses_existing_venv(tmp_path, monkeypatch):
    monkeypatch.delenv("NOETL_SKIP_DEPS_RESOLUTION", raising=False)
    monkeypatch.setenv("NOETL_TENANT_ENVS_DIR", str(tmp_path))

    tenant_venv_dir = tmp_path / "cached-tenant"
    site_pkgs = tenant_venv_dir / "lib" / "python3.12" / "site-packages"
    site_pkgs.mkdir(parents=True)
    py_bin = tenant_venv_dir / "bin" / "python"
    py_bin.parent.mkdir(parents=True)
    py_bin.write_text("")

    mock_run = MagicMock(return_value=MagicMock(returncode=0, stdout="", stderr=""))
    mock_venv_create = MagicMock()
    site_str = str(site_pkgs)

    with patch("noetl.tools.python.executor.venv.create", mock_venv_create), \
         patch("noetl.tools.python.executor.subprocess.run", mock_run):
        if site_str in sys.path:
            sys.path.remove(site_str)
        try:
            _resolve_deps({"packages": {"cached-tenant": ["pandas>=2.2.3"]}})
            mock_venv_create.assert_not_called()
            mock_run.assert_called_once()
            assert site_str in sys.path
        finally:
            if site_str in sys.path:
                sys.path.remove(site_str)


def test_resolve_deps_packages_pip_failure_raises(tmp_path, monkeypatch):
    monkeypatch.delenv("NOETL_SKIP_DEPS_RESOLUTION", raising=False)
    monkeypatch.setenv("NOETL_TENANT_ENVS_DIR", str(tmp_path))

    import subprocess as _sp
    site_pkgs = tmp_path / "bad-tenant" / "lib" / "python3.12" / "site-packages"

    def fake_venv_create(path, **kwargs):
        os.makedirs(str(site_pkgs), exist_ok=True)
        py_bin = os.path.join(path, "bin", "python")
        os.makedirs(os.path.dirname(py_bin), exist_ok=True)
        open(py_bin, "w").close()

    mock_run = MagicMock(
        side_effect=_sp.CalledProcessError(1, "pip", stderr="No matching distribution")
    )

    with patch("noetl.tools.python.executor.venv.create", side_effect=fake_venv_create), \
         patch("noetl.tools.python.executor.subprocess.run", mock_run):
        with pytest.raises(RuntimeError, match="pip install failed for tenant 'bad-tenant'"):
            _resolve_deps({"packages": {"bad-tenant": ["nonexistent-pkg-xyz==99.0"]}})


def test_resolve_deps_packages_empty_list_skipped(tmp_path, monkeypatch):
    monkeypatch.delenv("NOETL_SKIP_DEPS_RESOLUTION", raising=False)
    monkeypatch.setenv("NOETL_TENANT_ENVS_DIR", str(tmp_path))
    mock_run = MagicMock()
    mock_venv_create = MagicMock()
    with patch("noetl.tools.python.executor.venv.create", mock_venv_create), \
         patch("noetl.tools.python.executor.subprocess.run", mock_run):
        _resolve_deps({"packages": {"empty-tenant": []}})
        mock_venv_create.assert_not_called()
        mock_run.assert_not_called()
