from __future__ import annotations

from dataclasses import dataclass, field

from noetl.core.dsl.engine.models import Arc, Playbook, Step


@dataclass(frozen=True)
class PlannedFanout:
    """Static fan-out boundary derived from an inclusive next router."""

    step: str
    arcs: tuple[str, ...]
    reduce_steps: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class PlannedReduce:
    """Static reduce boundary for a step with more than one upstream."""

    step: str
    upstream_steps: tuple[str, ...]


@dataclass(frozen=True)
class FanoutReducePlan:
    """Deterministic stage topology extracted from a playbook."""

    fanouts: tuple[PlannedFanout, ...] = field(default_factory=tuple)
    reduces: tuple[PlannedReduce, ...] = field(default_factory=tuple)

    def is_empty(self) -> bool:
        return not self.fanouts and not self.reduces


def build_fanout_reduce_plan(playbook: Playbook) -> FanoutReducePlan:
    """Build a deterministic static fan-out/reduce plan for a playbook.

    Phase 6 treats canonical `next.spec.mode: inclusive` routers with multiple
    targets as fan-out boundaries. A step targeted by multiple upstream steps is
    a reduce boundary. The planner intentionally stays side-effect free so it can
    be used by validation, replay tooling, and later by the runtime stage opener.
    """

    steps_by_name = {step.step: step for step in playbook.workflow}
    workflow_order = {step.step: idx for idx, step in enumerate(playbook.workflow)}
    graph: dict[str, tuple[str, ...]] = {}
    incoming: dict[str, set[str]] = {step.step: set() for step in playbook.workflow}

    for step in playbook.workflow:
        targets = tuple(_arc_targets(step, steps_by_name))
        graph[step.step] = targets
        for target in targets:
            incoming.setdefault(target, set()).add(step.step)

    reduce_names = {
        step_name for step_name, upstream in incoming.items()
        if step_name in steps_by_name and len(upstream) > 1
    }

    fanouts: list[PlannedFanout] = []
    for step in playbook.workflow:
        router = step.next
        if not router or not router.spec or router.spec.mode != "inclusive":
            continue
        targets = tuple(_arc_targets(step, steps_by_name))
        if len(targets) < 2:
            continue
        fanouts.append(
            PlannedFanout(
                step=step.step,
                arcs=targets,
                reduce_steps=tuple(
                    sorted(
                        _reachable_reduces(graph, reduce_names, targets),
                        key=lambda name: workflow_order.get(name, len(workflow_order)),
                    )
                ),
            )
        )

    reduces = tuple(
        PlannedReduce(
            step=step_name,
            upstream_steps=tuple(
                sorted(upstream, key=lambda name: workflow_order.get(name, len(workflow_order)))
            ),
        )
        for step_name, upstream in sorted(
            incoming.items(),
            key=lambda item: workflow_order.get(item[0], len(workflow_order)),
        )
        if step_name in reduce_names
    )

    return FanoutReducePlan(fanouts=tuple(fanouts), reduces=reduces)


def _arc_targets(step: Step, steps_by_name: dict[str, Step]) -> list[str]:
    if not step.next:
        return []
    targets: list[str] = []
    seen: set[str] = set()
    for arc in step.next.arcs:
        target = _target_name(arc)
        if target and target in steps_by_name and target not in seen:
            targets.append(target)
            seen.add(target)
    return targets


def _target_name(arc: Arc) -> str | None:
    target = arc.step.strip() if isinstance(arc.step, str) else None
    return target or None


def _reachable_reduces(
    graph: dict[str, tuple[str, ...]],
    reduce_names: set[str],
    roots: tuple[str, ...],
) -> set[str]:
    found: set[str] = set()
    stack = list(reversed(roots))
    visited: set[str] = set()

    while stack:
        step_name = stack.pop()
        if step_name in visited:
            continue
        visited.add(step_name)
        if step_name in reduce_names:
            found.add(step_name)
            continue
        for target in reversed(graph.get(step_name, ())):
            if target not in visited:
                stack.append(target)

    return found
