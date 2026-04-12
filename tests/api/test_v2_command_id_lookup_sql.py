import noetl.server.api.core as v2_api


def _normalize_sql(sql: str) -> str:
    return " ".join(sql.split())


def _assert_index_friendly_lookup(sql: str) -> None:
    normalized = _normalize_sql(sql)
    normalized_upper = normalized.upper()
    assert "UNION ALL" not in normalized
    assert "meta ? 'command_id'" in normalized
    assert "meta->>'command_id' = %s" in normalized
    assert "result->'data'" not in normalized
    assert " OR " not in normalized_upper


def test_claim_command_lookup_sql_remains_index_friendly():
    _assert_index_friendly_lookup(v2_api._CLAIM_TERMINAL_LOOKUP_SQL)
    _assert_index_friendly_lookup(v2_api._CLAIM_EXISTING_LOOKUP_SQL)
    _assert_index_friendly_lookup(v2_api._CLAIM_SAME_WORKER_LATEST_LOOKUP_SQL)
    assert "command.heartbeat" in v2_api._CLAIM_EXISTING_LOOKUP_SQL


def test_handle_event_claim_lookup_sql_remains_index_friendly():
    _assert_index_friendly_lookup(v2_api._HANDLE_EVENT_CLAIMED_LOOKUP_SQL)


def test_command_id_lookup_params_include_execution_and_command_ids():
    assert v2_api._command_id_lookup_params(101, "cmd-101") == (101, "cmd-101")
