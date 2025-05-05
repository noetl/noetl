from sqlmodel import SQLModel
from noetl.api.models.catalog import Catalog, ResourceType
from noetl.api.models.event import Event, EventState
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

def create_noetl_tables(engine):
    SQLModel.metadata.create_all(engine)


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
            "REQUESTED",
            "Execution requested for {{ namespace }}.",
            "Initial event when an execution is triggered.",
            ["REGISTERED", "CANCELED"]
        ),
        (
            "REGISTERED",
            "{{ namespace }} was registered.",
            "The resource has been registered in the system.",
            ["CANCELED"]
        ),
        (
            "STARTED",
            "Execution started for {{ namespace }}.",
            "Execution has begun.",
            ["FAILED", "COMPLETED", "TERMINATED", "PAUSED"]
        ),
        (
            "CANCELED",
            "Execution canceled for {{ namespace }}.",
            "Execution was manually or automatically canceled.",
            []
        ),
        (
            "FAILED",
            "Execution failed for {{ namespace }}.",
            "Execution encountered an error and did not complete successfully.",
            ["RESTARTED"]
        ),
        (
            "COMPLETED",
            "Execution completed for {{ namespace }}.",
            "Execution completed successfully.",
            []
        ),
        (
            "TERMINATED",
            "Execution terminated for {{ namespace }}.",
            "Execution was forcibly terminated.",
            ["RESTARTED"]
        ),
        (
            "PAUSED",
            "Execution paused for {{ namespace }}.",
            "Execution has been paused.",
            ["COMPLETED", "TERMINATED", "CONTINUED"]
        ),
        (
            "CONTINUED",
            "Execution continued for {{ namespace }}.",
            "Paused execution has resumed.",
            ["FAILED", "COMPLETED", "TERMINATED", "PAUSED"]
        ),
        (
            "RESTARTED",
            "Execution restarted for {{ namespace }}.",
            "Execution restarted from the beginning or a checkpoint.",
            ["FAILED", "COMPLETED", "TERMINATED", "PAUSED", "CONTINUED"]
        ),
        (
            "UPDATED",
            "Resource {{ namespace }} was updated.",
            "The registered resource has changed.",
            []
        ),
        (
            "UNCHANGED",
            "Resource {{ namespace }} is already registered.",
            "The resource is already registered and hasn't changed.",
            []
        ),
    ]

    result = await session.exec(select(EventState))
    existing_events = {e.name for e in result.all()}

    new_event_types = [
        EventState(
            name=name,
            template=template,
            description=description,
            transitions=transitions
        )
        for name, template, description, transitions in event_definitions
        if name not in existing_events
    ]
    session.add_all(new_event_types)

    await session.commit()