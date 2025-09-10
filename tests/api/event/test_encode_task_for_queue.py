def test_encode_task_for_queue_encodes_and_strips_originals():
    from noetl.api.event.broker import encode_task_for_queue

    task = {
        "code": "print('hi')\nprint('bye')",
        "command": "SELECT 1;",
        "commands": "CREATE TABLE x as SELECT 1;"
    }

    out = encode_task_for_queue(task)

    # Originals should be removed
    assert "code" not in out
    assert "command" not in out
    assert "commands" not in out

    # Base64 versions should exist and be non-empty
    assert isinstance(out.get("code_b64"), str) and out["code_b64"].strip()
    assert isinstance(out.get("command_b64"), str) and out["command_b64"].strip()
    assert isinstance(out.get("commands_b64"), str) and out["commands_b64"].strip()

