from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from noetl.api.models.dict_flow import DictFlow


async def seed_dict_flow(session: AsyncSession) -> None:
    flow_records = [
        DictFlow(
            event_type="CatalogEntryRegistered",
            unit_name="workflow",
            route_path="/events/emit",
            http_method="POST",
            module_name="Event",
            route_module="noetl.api.routes.event",
            service_module="noetl.api.services.event",
            model_module="noetl.api.models.event",
            table_name="event",
            description="Handle catalog entry registration; emits a tracking event.",
            next_event="EventRecorded"
        ),
        DictFlow(
            event_type="WorkloadRegistryRequested",
            unit_name="workflow",
            route_path="/events/emit",
            http_method="POST",
            module_name="Event",
            route_module="noetl.api.routes.event",
            service_module="noetl.api.services.event",
            model_module="noetl.api.models.event",
            table_name="event",
            description="Emit event to track that workload registry was requested.",
            next_event="EventRecorded"
        ),
        DictFlow(
            event_type="EventRecorded",
            unit_name="workflow",
            route_path="/workload/register",
            http_method="POST",
            module_name="Registry",
            route_module="noetl.api.routes.registry",
            service_module="noetl.api.services.workload",
            model_module="noetl.api.models.workload",
            table_name="workload",
            description="Registers a workload instance for execution.",
            next_event="RegistryRecorded"
        ),
        DictFlow(
            event_type="RegistryRecorded",
            unit_name="workflow",
            route_path="/execution/start",
            http_method="POST",
            module_name="Execution",
            route_module="noetl.api.routes.execution",
            service_module="noetl.api.services.execution",
            model_module="noetl.api.models.execution",
            table_name="runtime",
            description="Starts a runtime execution from a registered workload.",
            next_event="ExecutionEvent"
        ),
        DictFlow(
            event_type="ExecutionEvent",
            unit_name="workflow",
            route_path="/context/register",
            http_method="POST",
            module_name="Context",
            route_module="noetl.api.routes.context",
            service_module="noetl.api.services.context",
            model_module="noetl.api.models.context",
            table_name="context",
            description="Registers step/task/action context for the current workflow.",
            next_event="ContextEvent"
        ),
        DictFlow(
            event_type="ContextEvent",
            unit_name="task",
            route_path="/result/save",
            http_method="POST",
            module_name="Result",
            route_module="noetl.api.routes.result",
            service_module="noetl.api.services.result",
            model_module="noetl.api.models.result",
            table_name="result",
            description="Saves final or intermediate result of task execution.",
            next_event="ResultRecorded"
        )
    ]

    result = await session.exec(select(DictFlow))
    existing_event_types = {r.event_type for r in result.all()}
    new_records = [record for record in flow_records if record.event_type not in existing_event_types]

    session.add_all(new_records)
    await session.commit()