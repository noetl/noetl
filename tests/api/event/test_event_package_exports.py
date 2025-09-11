def test_event_package_exports():
    from noetl.api import event as event_api

    # router exists
    assert hasattr(event_api, "router"), "event_api.router missing"

    # service + factory exports
    assert hasattr(event_api, "EventService"), "EventService export missing"
    assert hasattr(event_api, "get_event_service"), "get_event_service export missing"
    assert hasattr(event_api, "get_event_service_dependency"), "get_event_service_dependency export missing"

    # processing helpers
    assert hasattr(event_api, "evaluate_broker_for_execution"), "evaluate_broker_for_execution export missing"
    assert hasattr(event_api, "check_and_process_completed_loops"), "check_and_process_completed_loops export missing"
    assert hasattr(event_api, "check_and_process_completed_child_executions"), "check_and_process_completed_child_executions export missing"
    assert hasattr(event_api, "_check_distributed_loop_completion"), "_check_distributed_loop_completion export missing"

    # helper utility
    assert hasattr(event_api, "encode_task_for_queue"), "encode_task_for_queue export missing"

