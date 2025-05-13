from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from noetl.api.models.dict_flow import DictFlow

async def seed_dict_flow(session: AsyncSession) -> None:
    flow_definitions = [
        DictFlow(
            event_type="ContextRegistration",
            description="Handles context lifecycle for any execution unit."
        ),
        DictFlow(
            event_type="ExecutionTrigger",
            description="Controls when execution is started or resumed."
        ),
        DictFlow(
            event_type="ResultProcessing",
            description="Handles the collection, storage, and evaluation of result outputs."
        ),
        DictFlow(
            event_type="WorkloadClose",
            description="Finalizes the workload, cleaning up runtime and context."
        ),
        DictFlow(
            event_type="CatalogEntryRegistration",
            description="Triggers when a new or updated catalog entry is recorded."
        ),
        DictFlow(
            event_type="WorkloadRegistration",
            description="Registers a workload entity for a given execution unit."
        ),
        DictFlow(
            event_type="RuntimeInit",
            description="Starts the runtime instance for an execution unit."
        ),
        DictFlow(
            event_type="RuntimeClose",
            description="Stops or finalizes a runtime instance."
        ),
        DictFlow(
            event_type="ResultSaved",
            description="Indicates that the result for a task or action has been successfully saved."
        )
    ]

    result = await session.exec(select(DictFlow))
    existing_event_types = {r.event_type for r in result.all()}
    new_records = [record for record in flow_definitions if record.event_type not in existing_event_types]

    session.add_all(new_records)
    await session.commit()
