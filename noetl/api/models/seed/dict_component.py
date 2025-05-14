from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from noetl.api.models.dict_component import DictComponent

async def seed_dict_component(session: AsyncSession) -> None:
    component_definitions = [
        DictComponent(
            component_name="catalog",
            route_module="noetl.api.routes.catalog",
            schema_module="noetl.api.schemas.catalog",
            service_module="noetl.api.services.catalog",
            model_module="noetl.api.models.catalog",
            table_name="catalog",
            description="Catalog of playbooks and definitions."
        ),
        DictComponent(
            component_name="workload",
            route_module="noetl.api.routes.workload",
            schema_module="noetl.api.schemas.workload",
            service_module="noetl.api.services.workload",
            model_module="noetl.api.models.workload",
            table_name="workload",
            description="Context for executing workloads."
        ),
        DictComponent(
            component_name="runtime",
            route_module="noetl.api.routes.runtime",
            schema_module="noetl.api.schemas.runtime",
            service_module="noetl.api.services.runtime",
            model_module="noetl.api.models.runtime",
            table_name="runtime",
            description="Runtime execution environment."
        ),
        DictComponent(
            component_name="context",
            route_module="noetl.api.routes.context",
            schema_module="noetl.api.schemas.context",
            service_module="noetl.api.services.context",
            model_module="noetl.api.models.context",
            table_name="context",
            description="Execution context management."
        ),
        DictComponent(
            component_name="result",
            route_module="noetl.api.routes.result",
            schema_module="noetl.api.schemas.result",
            service_module="noetl.api.services.result",
            model_module="noetl.api.models.result",
            table_name="result",
            description="Management and persistence of execution results."
        ),
    ]

    existing_components = await session.exec(select(DictComponent))
    existing_component_names = {c.component_name for c in existing_components.all()}

    new_components = [
        component for component in component_definitions
        if component.component_name not in existing_component_names
    ]

    session.add_all(new_components)
    await session.commit()
