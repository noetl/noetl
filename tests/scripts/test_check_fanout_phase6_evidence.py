from scripts.check_fanout_phase6_evidence import validate_fanout_phase6_report


def test_validate_fanout_phase6_report_accepts_matching_report():
    report = {
        "planner_version": 1,
        "summary": {"playbooks": 1, "fanouts": 1, "reduces": 1},
        "playbooks": [
            {
                "path": "playbooks/fanout.yaml",
                "name": "fanout",
                "planner": {
                    "fanouts": [
                        {
                            "step": "start",
                            "arcs": ["a", "b"],
                            "reduce_steps": ["join"],
                        }
                    ],
                    "reduces": [
                        {
                            "step": "join",
                            "upstream_steps": ["a", "b"],
                        }
                    ],
                },
            }
        ],
    }

    result = validate_fanout_phase6_report(report, require_fanout=True, require_reduce=True)

    assert result["matched"] is True
    assert result["summary"] == {"playbooks": 1, "fanouts": 1, "reduces": 1}
    assert result["failures"] == []


def test_validate_fanout_phase6_report_rejects_count_mismatch():
    report = {
        "planner_version": 1,
        "summary": {"playbooks": 1, "fanouts": 2, "reduces": 0},
        "playbooks": [
            {
                "path": "playbooks/fanout.yaml",
                "name": "fanout",
                "planner": {
                    "fanouts": [{"step": "start", "arcs": ["a", "b"], "reduce_steps": []}],
                    "reduces": [],
                },
            }
        ],
    }

    result = validate_fanout_phase6_report(report)

    assert result["matched"] is False
    assert any(failure["field"] == "summary.fanouts" for failure in result["failures"])


def test_validate_fanout_phase6_report_rejects_missing_required_reduce():
    report = {
        "planner_version": 1,
        "summary": {"playbooks": 1, "fanouts": 1, "reduces": 0},
        "playbooks": [
            {
                "path": "playbooks/fanout.yaml",
                "name": "fanout",
                "planner": {
                    "fanouts": [{"step": "start", "arcs": ["a", "b"], "reduce_steps": []}],
                    "reduces": [],
                },
            }
        ],
    }

    result = validate_fanout_phase6_report(report, require_fanout=True, require_reduce=True)

    assert result["matched"] is False
    assert any(failure["field"] == "summary.reduces" for failure in result["failures"])
