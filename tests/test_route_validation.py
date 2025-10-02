import pytest

route_validation = pytest.importorskip(
    "noetl.route_validation",
    reason="Route validation helpers removed from the server package; test retained for backward compatibility."
)


def test_api_tables_exist():
    """Ensure every table referenced by API routes is defined in schema."""
    missing = route_validation.get_missing_tables()
    assert not missing, f"Missing tables referenced in API routes: {sorted(missing)}"
