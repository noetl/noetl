"""Backward compatible proxy to the refactored DuckDB plugin."""

from importlib import import_module
import sys

from noetl.plugin.tools.duckdb import *  # noqa: F401,F403

_BASE = "noetl.plugin.tools.duckdb"
_SUBMODULES = [
	"auth",
	"cloud",
	"config",
	"connections",
	"errors",
	"excel",
	"extensions",
	"sql",
	"types",
]

for _name in _SUBMODULES:
	module = import_module(f"{_BASE}.{_name}")
	sys.modules[f"{__name__}.{_name}"] = module
