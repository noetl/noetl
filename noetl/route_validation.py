"""Utilities for validating API routes against schema table definitions.

This module provides helper functions that scan SQL statements within the
modules under :mod:`noetl.api` and extract referenced table names.  The list
of tables is compared with the tables created in :mod:`noetl.schema` to
ensure that every referenced table exists in the schema definition.

The functions are intentionally lightweight and rely only on static analysis
of string literals; they do not perform any database access.  They are meant
for use in tests or sanity checks when adding new API routes.
"""
from __future__ import annotations

from pathlib import Path
import ast
import re
from typing import Set

API_PACKAGE = Path(__file__).parent / "api"
SCHEMA_FILE = Path(__file__).parent / "schema.py"

SCHEMA_TABLE_PATTERN = re.compile(
    r"CREATE TABLE IF NOT EXISTS \{(?:self\.noetl_schema|schema)\}\.([a-zA-Z_][a-zA-Z0-9_]*)"
)
API_TABLE_PATTERN = re.compile(r"noetl\.([a-zA-Z_][a-zA-Z0-9_]*)")


def extract_schema_tables(path: Path = SCHEMA_FILE) -> Set[str]:
    """Return set of table names created in ``schema.py``.

    The parser searches for ``CREATE TABLE`` statements that reference either
    ``{self.noetl_schema}`` or ``{schema}`` since both formats are used in the
    file.  The returned set contains each table name exactly once.
    """
    text = path.read_text()
    return set(SCHEMA_TABLE_PATTERN.findall(text))


def extract_api_tables(api_dir: Path = API_PACKAGE) -> Set[str]:
    """Return set of table names referenced by API modules.

    Each module is parsed using :mod:`ast` to collect all string literals.
    Any occurrences of ``"noetl.<table>"`` inside those strings are treated
    as table references.
    """
    tables: Set[str] = set()
    for file in api_dir.glob("*.py"):
        text = file.read_text()
        nodes = ast.walk(ast.parse(text))
        strings = [n.value for n in nodes if isinstance(n, ast.Constant) and isinstance(n.value, str)]
        for s in strings:
            tables.update(API_TABLE_PATTERN.findall(s))
    return tables


def get_missing_tables() -> Set[str]:
    """Return table names referenced by the API but missing in the schema."""
    api_tables = extract_api_tables()
    schema_tables = extract_schema_tables()
    return api_tables - schema_tables


if __name__ == "__main__":  # pragma: no cover - convenience CLI
    missing = get_missing_tables()
    if missing:
        print("Missing tables:", ", ".join(sorted(missing)))
    else:
        print("All API tables are present in the schema.")
