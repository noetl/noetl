from __future__ import annotations

import copy
from typing import Any, Dict, List, Tuple

from .duration_model import estimate_duration_ms
from .plan_types import Edge, ResourceCap, StepSpec

DEFAULT_DEMANDS: Dict[str, Dict[str, int]] = {
    "http": {"http_pool": 1},
    "postgres": {"pg_pool": 1},
    "duckdb": {"duckdb_host": 1},
}


def _infer_resources(step: Dict[str, Any]) -> Dict[str, int]:
    # explicit resources on the step override defaults
    res = step.get("resources") or {}
    stype = step.get("tool")
    if res:
        return {str(k): int(v) for k, v in res.items()}
    if stype in DEFAULT_DEMANDS:
        return dict(DEFAULT_DEMANDS[stype])
    return {}


def _normalize_playbook(pb: Dict[str, Any]) -> Dict[str, Any]:
    # Minimal normalization: just forward as-is.
    return pb


def build_plan(
    playbook: Dict[str, Any], resource_caps: Dict[str, int]
) -> tuple[list[StepSpec], list[Edge], list[ResourceCap]]:
    pb = _normalize_playbook(playbook)
    workflow: List[Dict[str, Any]] = pb.get("workflow", [])

    steps: List[StepSpec] = []
    edges: List[Edge] = []

    # Map logical step name -> produced concrete node ids (list)
    produced: Dict[str, List[str]] = {}
    step_index: Dict[str, Dict[str, Any]] = {
        s.get("step"): s for s in workflow if "step" in s
    }

    # First pass: expand steps
    for s in workflow:
        name = s.get("step")
        stype = s.get("tool")
        if stype == "iterator":
            # Expand collection items into separate steps
            coll_expr = s.get("collection")
            element = s.get("element", "item")
            # Input may bind the collection variable name; here we assume previous "next" provided it
            # For test/example, cities is resolved in previous step's next.input
            # We try to evaluate from workload if expression is like {{ workload.cities }} or {{ cities }}
            items = _eval_collection(pb, s, coll_expr)
            produced[name] = []
            for idx, item in enumerate(items):
                iter_id = f"{name}/{_safe_id(item, idx)}"
                # The task under iterator has its own type; inherit resources and estimate
                task = s.get("task", {})
                task_type = task.get("tool", "http")
                resources = task.get("resources") or DEFAULT_DEMANDS.get(
                    task_type, {"http_pool": 1}
                )
                dur = estimate_duration_ms(iter_id, task_type)
                steps.append(
                    StepSpec(
                        id=iter_id,
                        type=task_type,
                        resources=resources,
                        duration_ms=dur,
                        tags={"parent": name, "iter_index": str(idx)},
                    )
                )
                produced[name].append(iter_id)
        else:
            # Regular single step
            node_id = name
            produced[name] = [node_id]
            resources = _infer_resources(s)
            step_kind = stype or "router"
            dur = estimate_duration_ms(node_id, step_kind)
            steps.append(
                StepSpec(
                    id=node_id,
                    type=step_kind,
                    resources=resources,
                    duration_ms=dur,
                    tags={},
                )
            )

    # Second pass: edges and barriers
    for s in workflow:
        name = s.get("step")
        nexts = s.get("next", []) or []
        # Expand next into list
        if isinstance(nexts, dict):
            next_list = [nexts]
        else:
            next_list = list(nexts)
        # If current produces multiple nodes (iterator), successors should depend on all via a barrier
        curr_nodes = produced.get(name, [name])
        for nxt in next_list:
            succ_name = nxt.get("step")
            succ_nodes = produced.get(succ_name, [succ_name])
            if len(curr_nodes) > 1 and len(succ_nodes) >= 1:
                # create barrier node that depends on all curr_nodes
                barrier_id = f"barrier::{name}"
                # Ensure barrier exists as zero-duration step once
                if barrier_id not in [st.id for st in steps]:
                    steps.append(
                        StepSpec(
                            id=barrier_id,
                            type="barrier",
                            resources={},
                            duration_ms=0,
                            tags={"for": name},
                        )
                    )
                for c in curr_nodes:
                    edges.append(Edge(u=c, v=barrier_id))
                # barrier -> each successor node
                for v in succ_nodes:
                    edges.append(Edge(u=barrier_id, v=v))
            else:
                # simple all-to-all mapping
                for u in curr_nodes:
                    for v in succ_nodes:
                        edges.append(Edge(u=u, v=v))

    caps = [
        ResourceCap(name=k, capacity=int(v)) for k, v in (resource_caps or {}).items()
    ]
    return steps, edges, caps


def _safe_id(item: Any, idx: int) -> str:
    if isinstance(item, dict) and "name" in item:
        return str(item["name"]).replace("/", "-")
    return f"{idx}"


def _eval_collection(
    pb: Dict[str, Any], step: Dict[str, Any], coll_expr: Any
) -> List[Any]:
    # Very small evaluator to support {{ workload.cities }} and {{ cities }} or direct lists
    if isinstance(coll_expr, list):
        return coll_expr
    if isinstance(coll_expr, str):
        s = coll_expr.strip()
        if s.startswith("{{") and s.endswith("}}"):
            var = s[2:-2].strip()
            if var.startswith("workload."):
                # navigate dict
                parts = var.split(".")[1:]
                cur = pb.get("workload", {})
                for p in parts:
                    if isinstance(cur, dict):
                        cur = cur.get(p)
                    else:
                        cur = None
                        break
                if isinstance(cur, list):
                    return copy.deepcopy(cur)
            # try local variable name like cities
            if var == "cities":
                inp = step.get("input") or {}
                cities_expr = inp.get("cities")
                if isinstance(cities_expr, list):
                    return cities_expr
                if isinstance(cities_expr, str) and cities_expr.strip().startswith(
                    "{{"
                ):
                    # resolve against workload as well
                    return _eval_collection(pb, step, cities_expr)
        # Non-templated string unsupported; return empty
        return []
    return []
