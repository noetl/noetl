import json
import os
from noetl.core.common import ordered_yaml_load
from noetl.core.scheduler import build_plan, CpSatScheduler

EXAMPLE = os.path.join(os.path.dirname(__file__), "fixtures", "playbooks", "http_duckdb_postgres", "http_duckdb_postgres.yaml")


def test_iterator_expansion_and_barrier():
    with open(EXAMPLE, "r", encoding="utf-8") as f:
        pb = ordered_yaml_load(f)
    steps, edges, caps = build_plan(pb, {"http_pool": 2, "pg_pool": 1, "duckdb_host": 1})

    ids = {s.id for s in steps}
    # Expect iterator child steps
    assert any(i.startswith("http_loop/") for i in ids)
    # Barrier exists
    assert "barrier::http_loop" in ids

    # Ensure edges include dependencies from each http_loop child to barrier
    http_children = [i for i in ids if i.startswith("http_loop/")]
    edge_set = {(e.u, e.v) for e in edges}
    for c in http_children:
        assert (c, "barrier::http_loop") in edge_set


def test_cp_sat_schedule_feasible():
    with open(EXAMPLE, "r", encoding="utf-8") as f:
        pb = ordered_yaml_load(f)
    steps, edges, caps = build_plan(pb, {"http_pool": 2, "pg_pool": 1, "duckdb_host": 1})

    sched = CpSatScheduler(max_seconds=3.0).solve(steps, edges, caps)
    assert sched.starts_ms and sched.ends_ms
    # Makespan equals max end
    assert max(sched.ends_ms.values()) >= max(sched.starts_ms.values())
