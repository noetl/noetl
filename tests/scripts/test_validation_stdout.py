from scripts.validation_stdout import parse_json_output


def test_parse_json_output_accepts_plain_json():
    assert parse_json_output('{"matched": true}') == {"matched": True}


def test_parse_json_output_accepts_log_prefixed_json_object():
    output = "2026-05-20T20:48:51 [INFO] config validated\n{\"matched\": true, \"failures\": []}\n"

    assert parse_json_output(output) == {"matched": True, "failures": []}


def test_parse_json_output_accepts_log_prefixed_json_array():
    output = "INFO warmup complete\n[{\"name\": \"fetch\"}]\n"

    assert parse_json_output(output) == [{"name": "fetch"}]


def test_parse_json_output_rejects_non_json_output():
    assert parse_json_output("INFO only\nnot-json") is None
