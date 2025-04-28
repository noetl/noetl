from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from noetl.api.models.resources import ResourceType, EventType


async def seed_default_types(session: AsyncSession) -> None:
    resource_names = [
        "Playbook",
        "Workflow",
        "Target",
        "Step",
        "Task",
        "Action",
    ]
    result = await session.exec(select(ResourceType))
    existing = {r.name for r in result.all()}
    new_resource_types = [
        ResourceType(name=name)
        for name in resource_names
        if name not in existing
    ]
    session.add_all(new_resource_types)

    event_definitions = [
        (
            "REGISTERED",
            "Resource {{ resource_path }} version {{ resource_version }} was registered.",
        ),
        (
            "UPDATED",
            "Resource {{ resource_path }} version {{ resource_version }} was updated.",
        ),
        (
            "UNCHANGED",
            "Resource {{ resource_path }} already registered.",
        ),
        (
            "EXECUTION_STARTED",
            "Execution started for {{ resource_path }}.",
        ),
        (
            "EXECUTION_FAILED",
            "Execution failed for {{ resource_path }}.",
        ),
        (
            "EXECUTION_COMPLETED",
            "Execution completed for {{ resource_path }}.",
        ),
    ]
    result = await session.exec(select(EventType))
    existing_events = {e.name for e in result.all()}
    new_event_types = [
        EventType(name=name, template=template)
        for name, template in event_definitions
        if name not in existing_events
    ]
    session.add_all(new_event_types)

    await session.commit()
