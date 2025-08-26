from noetl.route_validation import get_missing_tables


def test_api_tables_exist():
    """Ensure every table referenced by API routes is defined in schema."""
    missing = get_missing_tables()
    assert not missing, f"Missing tables referenced in API routes: {sorted(missing)}"
