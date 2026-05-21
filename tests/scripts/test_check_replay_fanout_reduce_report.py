from scripts.check_replay_fanout_reduce_report import validate_replay_fanout_reduce_report


def _report():
    return {
        "commands": {
            "10": {
                "command_id": "10",
                "step": "normalize_customer",
                "fanout_reduce": {
                    "planner_version": 1,
                    "fanout_step": "start",
                    "fanout_targets": ["normalize_customer", "enrich_customer"],
                    "target_step": "normalize_customer",
                    "target_index": 0,
                    "reduce_steps": ["reduce_customer"],
                },
            }
        }
    }


def test_validate_replay_fanout_reduce_report_accepts_valid_metadata():
    result = validate_replay_fanout_reduce_report(_report())

    assert result["matched"] is True
    assert result["fanout_commands"] == 1
    assert result["fanout_steps"] == ["start"]
    assert result["reduce_steps"] == ["reduce_customer"]
    assert result["failures"] == []


def test_validate_replay_fanout_reduce_report_rejects_missing_metadata():
    result = validate_replay_fanout_reduce_report({"commands": {"10": {"command_id": "10"}}})

    assert result["matched"] is False
    assert result["failures"][0]["field"] == "commands"


def test_validate_replay_fanout_reduce_report_rejects_bad_target_index():
    report = _report()
    report["commands"]["10"]["fanout_reduce"]["target_index"] = 1

    result = validate_replay_fanout_reduce_report(report)

    assert result["matched"] is False
    assert any(
        failure["field"] == "commands.10.fanout_reduce.target_step"
        for failure in result["failures"]
    )


def test_validate_replay_fanout_reduce_report_can_allow_no_reduce():
    report = _report()
    report["commands"]["10"]["fanout_reduce"]["reduce_steps"] = []

    result = validate_replay_fanout_reduce_report(report, require_reduce=False)

    assert result["matched"] is True
    assert result["reduce_steps"] == []
