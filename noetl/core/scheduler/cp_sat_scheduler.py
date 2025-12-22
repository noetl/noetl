from typing import List
from ortools.sat.python import cp_model
from .plan_types import StepSpec, Edge, ResourceCap, Schedule


class CpSatScheduler:
    def __init__(self, max_seconds: float = 5.0):
        self.max_seconds = max_seconds

    def solve(
        self,
        steps: List[StepSpec],
        edges: List[Edge],
        capacities: List[ResourceCap],
        horizon_ms: int | None = None,
    ) -> Schedule:
        m = cp_model.CpModel()
        durs = {s.id: max(1, int(s.duration_ms)) for s in steps}
        H = int(horizon_ms or sum(durs.values()) or 1)

        S: dict[str, cp_model.IntVar] = {}
        E: dict[str, cp_model.IntVar] = {}
        I: dict[str, cp_model.IntervalVar] = {}

        for s in steps:
            S[s.id] = m.NewIntVar(0, H, f"s_{s.id}")
            E[s.id] = m.NewIntVar(0, H, f"e_{s.id}")
            I[s.id] = m.NewIntervalVar(S[s.id], durs[s.id], E[s.id], f"i_{s.id}")

        for e in edges:
            if e.u in E and e.v in S:
                m.Add(S[e.v] >= E[e.u])

        # Cumulative resources by name
        from collections import defaultdict

        by_res: dict[str, list[tuple[cp_model.IntervalVar, int]]] = defaultdict(list)
        for s in steps:
            for rname, demand in s.resources.items():
                by_res[rname].append((I[s.id], int(demand)))

        for cap in capacities:
            ivs, demands = [], []
            for iv, dem in by_res.get(cap.name, []):
                ivs.append(iv)
                demands.append(int(dem))
            if ivs:
                m.AddCumulative(ivs, demands, int(cap.capacity))

        makespan = m.NewIntVar(0, H, "makespan")
        m.AddMaxEquality(makespan, [E[s.id] for s in steps])
        m.Minimize(makespan)

        solver = cp_model.CpSolver()
        solver.parameters.max_time_in_seconds = float(self.max_seconds)
        status = solver.Solve(m)
        if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            raise RuntimeError("No feasible schedule")

        return Schedule(
            starts_ms={sid: int(solver.Value(S[sid])) for sid in S},
            ends_ms={sid: int(solver.Value(E[sid])) for sid in E},
            durations_ms=durs,
        )
