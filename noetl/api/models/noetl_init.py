from sqlmodel import SQLModel
from noetl.api.models.catalog import Catalog, ResourceType
from noetl.api.models.eventlog import EventLog, EventState
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
            "Execution requested for {{ resource_path }}.",
            "Initial event when an execution is triggered.",
            ["REGISTERED", "CANCELED"]
        ),
        (
            "REGISTERED",
            "Resource {{ resource_path }} version {{ resource_version }} was registered.",
            "The resource has been registered in the system.",
            ["CANCELED"]
        ),
        (
            "STARTED",
            "Execution started for {{ resource_path }}.",
            "Execution has begun.",
            ["FAILED", "COMPLETED", "TERMINATED", "PAUSED"]
        ),
        (
            "CANCELED",
            "Execution canceled for {{ resource_path }}.",
            "Execution was manually or automatically canceled.",
            []
        ),
        (
            "FAILED",
            "Execution failed for {{ resource_path }}.",
            "Execution encountered an error and did not complete successfully.",
            ["RESTARTED"]
        ),
        (
            "COMPLETED",
            "Execution completed for {{ resource_path }}.",
            "Execution completed successfully.",
            []
        ),
        (
            "TERMINATED",
            "Execution terminated for {{ resource_path }}.",
            "Execution was forcibly terminated.",
            ["RESTARTED"]
        ),
        (
            "PAUSED",
            "Execution paused for {{ resource_path }}.",
            "Execution has been paused.",
            ["COMPLETED", "TERMINATED", "CONTINUED"]
        ),
        (
            "CONTINUED",
            "Execution continued for {{ resource_path }}.",
            "Paused execution has resumed.",
            ["FAILED", "COMPLETED", "TERMINATED", "PAUSED"]
        ),
        (
            "RESTARTED",
            "Execution restarted for {{ resource_path }}.",
            "Execution restarted from the beginning or a checkpoint.",
            ["FAILED", "COMPLETED", "TERMINATED", "PAUSED", "CONTINUED"]
        ),
        (
            "UPDATED",
            "Resource {{ resource_path }} version {{ resource_version }} was updated.",
            "The registered resource has changed.",
            []
        ),
        (
            "UNCHANGED",
            "Resource {{ resource_path }} already registered.",
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
