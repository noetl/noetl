"""Guard test: the Python EHDB integration path is retired.

The EHDB (Event Horizon Database) integration is Rust-only — it lives in the
Rust worker (`noetl/worker`, `src/ehdb`), which calls the `ehdb-reference`
crate in process.  The former Python modules (`noetl.core.ehdb_*`), their
worker bootstrap wiring, and the bundled `ehdb-local-reference` helper binary
were removed so the Python path can never run as a parallel EHDB
implementation (noetl/ehdb#234).

This test locks that retirement in: it fails if any retired module reappears
or if the worker re-wires EHDB.
"""

from __future__ import annotations

import importlib
import inspect

import pytest

RETIRED_MODULES = [
    "noetl.core.ehdb_contract",
    "noetl.core.ehdb_control_plane",
    "noetl.core.ehdb_surface",
    "noetl.core.ehdb_adapter",
    "noetl.core.ehdb_readiness",
    "noetl.core.ehdb_dataplane",
    "noetl.core.ehdb_eventstream",
]


@pytest.mark.parametrize("module_name", RETIRED_MODULES)
def test_retired_ehdb_module_is_gone(module_name: str) -> None:
    """Importing a retired Python EHDB module must fail."""
    with pytest.raises(ModuleNotFoundError):
        importlib.import_module(module_name)


def test_worker_does_not_wire_ehdb_readiness() -> None:
    """The worker bootstrap no longer carries the EHDB readiness preflight."""
    from noetl.worker import nats_worker

    assert not hasattr(nats_worker, "_ehdb_readiness_preflight")
    source = inspect.getsource(nats_worker.run_worker)
    assert "ehdb" not in source.lower() or "Rust-only" in source


def test_worker_metrics_render_has_no_ehdb_lines() -> None:
    """The worker `/metrics` renderer emits no EHDB metric families."""
    from noetl.worker import metrics

    source = inspect.getsource(metrics.render_worker_metrics)
    # No live EHDB renderer import/extend remains; only the retirement note.
    assert "render_ehdb_" not in source
