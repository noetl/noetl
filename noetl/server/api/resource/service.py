"""Service layer for resource execution endpoint."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Tuple, Union

import yaml
from fastapi import HTTPException
from jinja2 import BaseLoader, Environment
from psycopg.rows import dict_row

from noetl.server.api.resource.schema import (
    DispatchedStep,
    ResourceRunRequest,
    ResourceRunResponse,
)
from noetl.core.common import (
    get_async_db_connection,
    get_snowflake_id,
    snowflake_id_to_int,
)
from noetl.core.dsl.normalize import normalize_step
from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger
from noetl.server.api.event.service import get_event_service

logger = setup_logger(__name__, include_location=True)


@dataclass
class StepPlan:
    name: str
    definition: Dict[str, Any]
    transition: Dict[str, Any]
    actionable: bool


class ResourceExecutionService:
    """Main entry point that prepares playbooks and emits kickoff events."""

    @classmethod
    async def run(cls, request: ResourceRunRequest) -> ResourceRunResponse:
        catalog_row = await cls._fetch_catalog(request.path, request.version)
        catalog_id = catalog_row["catalog_id"]
        resolved_version = str(catalog_row["version"])
        playbook = cls._parse_playbook(catalog_row.get("content"))
        base_workload = cls._coerce_dict(playbook.get("workload"))
        workload = cls._prepare_workload(request, base_workload)

        execution_id_int = get_snowflake_id()
        execution_id = str(execution_id_int)
        await cls._persist_workload(execution_id_int, request.path, resolved_version, workload)

        await cls._emit_execution_started(
            execution_id,
            catalog_id,
            request.path,
            resolved_version,
            workload,
        )

        step_plans = cls._resolve_start_plans(playbook, workload, request.path, resolved_version)
        dispatched: List[DispatchedStep] = []

        for plan in step_plans:
            step_context = cls._build_step_context(workload, request.path, resolved_version, plan.name, plan.transition)
            if plan.actionable:
                await cls._emit_step_started(
                    execution_id,
                    catalog_id,
                    plan.name,
                    plan.definition,
                    step_context,
                )
                queue_id = await cls._enqueue_step(
                    execution_id,
                    catalog_id,
                    plan.name,
                    plan.definition,
                    plan.transition,
                    step_context,
                )
                await cls._emit_queue_registered(
                    execution_id,
                    catalog_id,
                    plan.name,
                    plan.definition,
                    step_context,
                    queue_id,
                )
                dispatched.append(
                    DispatchedStep(
                        name=plan.name,
                        node_type=str(plan.definition.get("type") or "task"),
                        actionable=True,
                        queue_id=str(queue_id) if queue_id is not None else None,
                    )
                )
            else:
                dispatched.append(
                    DispatchedStep(
                        name=plan.name,
                        node_type=str(plan.definition.get("type") or "event"),
                        actionable=False,
                        queue_id=None,
                    )
                )

        return ResourceRunResponse(
            execution_id=execution_id,
            catalog_id=str(catalog_id),
            path=request.path,
            version=resolved_version,
            workload=workload,
            steps=dispatched,
        )

    @staticmethod
    async def _fetch_catalog(path: str, version: Optional[str]) -> Dict[str, Any]:
        if not path:
            raise HTTPException(status_code=400, detail="path is required")

        async with get_async_db_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                if not version or version.lower() == "latest":
                    await cur.execute(
                        """
                        SELECT catalog_id, path, version, content
                        FROM noetl.catalog
                        WHERE path = %s
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        (path,),
                    )
                else:
                    await cur.execute(
                        """
                        SELECT catalog_id, path, version, content
                        FROM noetl.catalog
                        WHERE path = %s AND version = %s
                        LIMIT 1
                        """,
                        (path, version),
                    )
                row = await cur.fetchone()

        if not row:
            raise HTTPException(status_code=404, detail=f"Catalog entry not found for path '{path}'")

        return dict(row)

    @staticmethod
    def _parse_playbook(content: Optional[str]) -> Dict[str, Any]:
        if not content:
            return {}
        try:
            parsed = yaml.safe_load(content) or {}
            if not isinstance(parsed, dict):
                raise ValueError("Playbook content must deserialize to a mapping")
            return parsed
        except yaml.YAMLError as exc:
            raise HTTPException(status_code=400, detail=f"Invalid playbook YAML: {exc}") from exc

    @staticmethod
    def _coerce_dict(value: Any) -> Dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @classmethod
    def _prepare_workload(cls, request: ResourceRunRequest, base_workload: Dict[str, Any]) -> Dict[str, Any]:
        jinja_env = Environment(loader=BaseLoader())
        render_context = cls._build_render_context(base_workload, request)
        rendered = cls._render_payload(jinja_env, request.payload, render_context)

        if isinstance(rendered, dict):
            if request.merge:
                merged = dict(base_workload)
                merged.update(rendered)
                return merged
            return rendered

        target = dict(base_workload) if request.merge else {}
        if rendered is not None:
            target["payload"] = rendered
        elif not request.merge:
            return dict(base_workload)
        return target

    @staticmethod
    def _render_payload(env: Environment, payload: Any, context: Dict[str, Any]) -> Any:
        if payload is None:
            return None
        rendered = render_template(env, payload, context)
        if isinstance(rendered, str):
            trimmed = rendered.strip()
            if not trimmed:
                return ""
            for decoder in (json.loads, yaml.safe_load):
                try:
                    candidate = decoder(trimmed)
                    if isinstance(candidate, (dict, list)):
                        return candidate
                except Exception:
                    continue
            return trimmed
        return rendered

    @staticmethod
    def _build_render_context(base_workload: Dict[str, Any], request: ResourceRunRequest) -> Dict[str, Any]:
        context: Dict[str, Any] = {
            "workload": base_workload,
            "path": request.path,
            "version": request.version or "latest",
        }
        context.update(base_workload)
        return context

    @staticmethod
    async def _persist_workload(execution_id: int, path: str, version: str, workload: Dict[str, Any]) -> None:
        payload = {
            "path": path,
            "version": version,
            "workload": workload,
        }
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO noetl.workload (execution_id, data)
                    VALUES (%s, %s::jsonb)
                    ON CONFLICT (execution_id) DO UPDATE SET data = EXCLUDED.data
                    """,
                    (execution_id, json.dumps(payload)),
                )
                await conn.commit()

    @staticmethod
    async def _emit_execution_started(
        execution_id: str,
        catalog_id: Union[int, str],
        path: str,
        version: str,
        workload: Dict[str, Any],
    ) -> None:
        event_service = get_event_service()
        await event_service.emit(
            {
                "execution_id": execution_id,
                "catalog_id": str(catalog_id),
                "event_type": "execution_started",
                "status": "STARTED",
                "node_id": execution_id,
                "node_name": path.split("/")[-1] or path,
                "node_type": "playbook",
                "meta": {"path": path, "version": version, "catalog_id": str(catalog_id)},
                "context": {"path": path, "version": version, "workload": workload},
            }
        )

    @classmethod
    def _resolve_start_plans(
        cls,
        playbook: Dict[str, Any],
        workload: Dict[str, Any],
        path: str,
        version: str,
    ) -> List[StepPlan]:
        steps = cls._extract_steps(playbook)
        if not steps:
            raise HTTPException(status_code=400, detail="Playbook workflow has no steps")

        index = {cls._step_name(step): step for step in steps if cls._step_name(step)}
        start = index.get("start")
        if not start:
            raise HTTPException(status_code=400, detail="Playbook is missing a 'start' step")

        env = Environment(loader=BaseLoader())
        context = {
            "workload": workload,
            "path": path,
            "version": version,
        }
        context.update(workload)

        plans: List[StepPlan] = []
        for name, transition in cls._iter_start_targets(start, env, context):
            definition = index.get(name)
            if not definition:
                logger.warning("Step '%s' referenced by start.next but not defined", name)
                continue
            actionable = cls._is_actionable(definition)
            plans.append(
                StepPlan(
                    name=name,
                    definition=definition,
                    transition=transition,
                    actionable=actionable,
                )
            )
        return plans

    @staticmethod
    def _extract_steps(playbook: Dict[str, Any]) -> List[Dict[str, Any]]:
        workflow = playbook.get("workflow") or playbook.get("steps") or []
        if isinstance(workflow, list):
            return [step for step in workflow if isinstance(step, dict)]
        return []

    @staticmethod
    def _step_name(step: Dict[str, Any]) -> str:
        return str(step.get("step") or step.get("name") or "").strip()

    @classmethod
    def _iter_start_targets(
        cls,
        start: Dict[str, Any],
        env: Environment,
        context: Dict[str, Any],
    ) -> Iterable[Tuple[str, Dict[str, Any]]]:
        raw_next = start.get("next")
        if not raw_next:
            return []
        entries: List[Any]
        if isinstance(raw_next, list):
            entries = raw_next
        else:
            entries = [raw_next]

        for entry in entries:
            yield from cls._resolve_next_entry(entry, env, context)

    @classmethod
    def _resolve_next_entry(
        cls,
        entry: Any,
        env: Environment,
        context: Dict[str, Any],
    ) -> Iterable[Tuple[str, Dict[str, Any]]]:
        if isinstance(entry, str):
            yield entry, {}
            return

        if not isinstance(entry, dict):
            return

        condition = entry.get("when") or entry.get("condition")
        if condition is not None and not cls._evaluate_condition(env, condition, context):
            return

        transition = cls._extract_transition(entry)

        target = entry.get("step") or entry.get("name")
        if target:
            yield str(target), transition

        then_block = entry.get("then")
        if then_block:
            targets = then_block if isinstance(then_block, list) else [then_block]
            for item in targets:
                if isinstance(item, str):
                    yield item, transition
                elif isinstance(item, dict):
                    name = item.get("step") or item.get("name")
                    if name:
                        yield str(name), transition

    @staticmethod
    def _evaluate_condition(env: Environment, template: Any, context: Dict[str, Any]) -> bool:
        try:
            rendered = render_template(env, template, context)
            if isinstance(rendered, str):
                value = rendered.strip().lower()
                if value in {"", "false", "0", "none", "null"}:
                    return False
                return True
            return bool(rendered)
        except Exception:
            logger.debug("Failed to evaluate condition '%s'", template, exc_info=True)
            return False

    @staticmethod
    def _extract_transition(transition_entry: Dict[str, Any]) -> Dict[str, Any]:
        transition: Dict[str, Any] = {}
        for key in ("input", "with", "payload", "data"):
            value = transition_entry.get(key)
            if isinstance(value, dict):
                transition[key] = value
        return transition

    @staticmethod
    def _is_actionable(step_def: Dict[str, Any]) -> bool:
        if not step_def:
            return False
        step_type = str(step_def.get("type") or "").lower()
        if step_type in {"", "start", "end", "route"}:
            return False
        if step_def.get("save"):
            return True
        if step_type == "python":
            code = step_def.get("code") or step_def.get("code_b64") or step_def.get("code_base64")
            return bool(code)
        return step_type in {
            "http",
            "python",
            "duckdb",
            "postgres",
            "snowflake",
            "snowflake_transfer",
            "transfer",
            "secrets",
            "workbook",
            "playbook",
            "save",
            "iterator",
        }

    @classmethod
    def _build_task(cls, definition: Dict[str, Any], transition: Dict[str, Any]) -> Dict[str, Any]:
        task = {
            "name": definition.get("name") or definition.get("step") or "task",
            "type": definition.get("type") or "python",
        }
        for field in (
            "task",
            "run",
            "code",
            "command",
            "commands",
            "sql",
            "url",
            "endpoint",
            "method",
            "headers",
            "params",
            "collection",
            "element",
            "mode",
            "concurrency",
            "enumerate",
            "where",
            "limit",
            "chunk",
            "order_by",
            "input",
            "payload",
            "with",
            "auth",
            "args",
            "resource_path",
            "content",
            "path",
            "iterator",
            "save",
            "credential",
            "credentials",
            "retry",
        ):
            if definition.get(field) is not None:
                task[field] = definition[field]

        if transition:
            transition_input = transition.get("input") or transition.get("data")
            if isinstance(transition_input, dict):
                base_args = task.get("args") if isinstance(task.get("args"), dict) else {}
                merged = dict(base_args)
                merged.update(transition_input)
                task["args"] = merged

        return normalize_step(task)

    @staticmethod
    def _build_step_context(
        workload: Dict[str, Any],
        path: str,
        version: str,
        step_name: str,
        transition: Dict[str, Any],
    ) -> Dict[str, Any]:
        context = {
            "workload": workload,
            "path": path,
            "version": version,
            "step_name": step_name,
        }
        if transition:
            context["transition"] = transition
        return context

    @classmethod
    async def _enqueue_step(
        cls,
        execution_id: str,
        catalog_id: Union[int, str],
        step_name: str,
        definition: Dict[str, Any],
        transition: Dict[str, Any],
        context: Dict[str, Any],
    ) -> Optional[int]:
        task = cls._build_task(definition, transition)
        encoded = cls._encode_task(task)
        max_attempts = cls._resolve_max_attempts(task)
        execution_id_int = snowflake_id_to_int(execution_id)

        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                await cur.execute(
                    """
                    INSERT INTO noetl.queue (
                        execution_id, catalog_id, node_id, action, context, priority, max_attempts, available_at
                    )
                    VALUES (%s, %s, %s, %s, %s::jsonb, %s, %s, now())
                    ON CONFLICT (execution_id, node_id) DO NOTHING
                    RETURNING queue_id
                    """,
                    (
                        execution_id_int,
                        int(catalog_id),
                        f"{execution_id}:{step_name}",
                        json.dumps(encoded),
                        json.dumps(context),
                        5,
                        max_attempts,
                        ),
                )
                row = await cur.fetchone()
                await conn.commit()

        return row[0] if row else None

    @staticmethod
    def _resolve_max_attempts(task: Dict[str, Any]) -> int:
        retry_config = task.get("retry")
        if isinstance(retry_config, bool):
            return 3 if retry_config else 1
        if isinstance(retry_config, int):
            return retry_config
        if isinstance(retry_config, dict):
            return int(retry_config.get("max_attempts", 3))
        return 3

    @staticmethod
    def _encode_task(task: Dict[str, Any]) -> Dict[str, Any]:
        encoded = dict(task)
        try:
            import base64

            def _encode_field(field: str) -> None:
                value = encoded.get(field)
                if isinstance(value, str) and value.strip():
                    encoded[f"{field}_b64"] = base64.b64encode(value.encode("utf-8")).decode("ascii")
                    encoded.pop(field, None)

            _encode_field("code")
            _encode_field("command")
            _encode_field("commands")
        except Exception:
            logger.debug("Task encoding failed; continuing with original payload", exc_info=True)
        return encoded

    @staticmethod
    async def _emit_step_started(
        execution_id: str,
        catalog_id: Union[int, str],
        step_name: str,
        definition: Dict[str, Any],
        context: Dict[str, Any],
    ) -> None:
        event_service = get_event_service()
        await event_service.emit(
            {
                "execution_id": execution_id,
                "catalog_id": str(catalog_id),
                "event_type": "step_started",
                "status": "STARTED",
                "node_id": f"{execution_id}:{step_name}",
                "node_name": step_name,
                "node_type": definition.get("type", "task"),
                "meta": {"catalog_id": str(catalog_id)},
                "context": context,
            }
        )

    @staticmethod
    async def _emit_queue_registered(
        execution_id: str,
        catalog_id: Union[int, str],
        step_name: str,
        definition: Dict[str, Any],
        context: Dict[str, Any],
        queue_id: Optional[int],
    ) -> None:
        event_service = get_event_service()
        await event_service.emit(
            {
                "execution_id": execution_id,
                "catalog_id": str(catalog_id),
                "event_type": "queue_registered",
                "status": "PENDING",
                "node_id": f"{execution_id}:{step_name}",
                "node_name": step_name,
                "node_type": definition.get("type", "task"),
                "meta": {"catalog_id": str(catalog_id)},
                "context": context,
                "result": {"queue_id": queue_id},
            }
        )
