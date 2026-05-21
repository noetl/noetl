import json

from scripts.build_fanout_phase6_report import build_fanout_phase6_report


def test_build_fanout_phase6_report_counts_planned_boundaries(tmp_path):
    playbook = tmp_path / "fanout.yaml"
    playbook.write_text(
        """
apiVersion: noetl.io/v2
kind: Playbook
metadata:
  name: fanout_report

workflow:
  - step: start
    tool:
      kind: python
      code: "def main(): return {}"
    next:
      spec:
        mode: inclusive
      arcs:
        - step: a
        - step: b
  - step: a
    tool:
      kind: python
      code: "def main(): return {}"
    next:
      spec:
        mode: exclusive
      arcs:
        - step: join
  - step: b
    tool:
      kind: python
      code: "def main(): return {}"
    next:
      spec:
        mode: exclusive
      arcs:
        - step: join
  - step: join
    tool:
      kind: python
      code: "def main(): return {}"
""",
        encoding="utf-8",
    )

    report = build_fanout_phase6_report([playbook])

    assert json.loads(json.dumps(report))
    assert report["planner_version"] == 1
    assert report["summary"] == {"playbooks": 1, "fanouts": 1, "reduces": 1}
    planner = report["playbooks"][0]["planner"]
    assert planner["fanouts"][0]["reduce_steps"] == ["join"]
    assert planner["reduces"][0]["upstream_steps"] == ["a", "b"]
