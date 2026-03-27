from noetl.tools.postgres.response import collapse_results_to_last_command


def test_collapse_results_returns_last_statement_payload_without_command_keys():
    collapsed = collapse_results_to_last_command(
        {
            "command_0": {"status": "success", "rows": [{"id": 1}]},
            "command_1": {"status": "success", "rows": [{"id": 2}]},
        }
    )

    assert collapsed["rows"][0]["id"] == 2
    assert collapsed["statement_count"] == 2
    assert "command_count" not in collapsed
    assert "last_command" not in collapsed


def test_collapse_results_reports_statement_index_for_errors():
    collapsed = collapse_results_to_last_command(
        {
            "command_0": {"status": "success", "rows": [{"id": 1}]},
            "command_1": {"status": "error", "message": "syntax error"},
        }
    )

    assert collapsed["status"] == "error"
    assert collapsed["errors"] == [{"statement_index": 1, "message": "syntax error"}]
    assert "command_1" not in collapsed["message"]
