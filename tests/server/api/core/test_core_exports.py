def test_core_exports_execute_request_and_execute_endpoint():
    from noetl.server.api.core import ExecuteRequest, ExecuteResponse, execute, start_execution

    assert ExecuteRequest.__name__ == "ExecuteRequest"
    assert ExecuteResponse.__name__ == "ExecuteResponse"
    assert callable(execute)
    assert callable(start_execution)
