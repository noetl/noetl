from typing import Optional

from sqlalchemy.future import select

from noetl.api.schemas.registry import RegistryResponse, RegistryRequest
from noetl.ctx.app_context import AppContext
from noetl.api.models.registry import Registry
from noetl.util import setup_logger

logger = setup_logger(__name__, include_location=True)


def get_registry_service(context: AppContext):
    return RegistryService(context)


class RegistryService:
    def __init__(self, context: AppContext) -> None:
        self.context = context

    async def check_registry_entry(self, resource_path: str, resource_version: str,
                                   event_id: Optional[str] = None) -> bool:
        logger.debug(
            f"Checking if registry exists for path={resource_path}, version={resource_version}, event_id={event_id}")

        async with self.context.postgres.get_session() as session:
            query = select(Registry).where(
                Registry.resource_path == resource_path,
                Registry.resource_version == resource_version,
            )
            if event_id:
                query = query.where(Registry.event_id == event_id)

            result = await session.execute(query)
            registry_entry = result.scalars().first()
            return registry_entry

    async def save_registry_entry(self, registry_data: Registry) -> (

            Registry):
        logger.info(f"Saving registry: path={registry_data.resource_path}, version={registry_data.resource_version}")

        async with self.context.postgres.get_session() as session:
            session.add(registry_data)
            await session.commit()
            await session.refresh(registry_data)
        return registry_data

    async def register(self, registry_data: RegistryRequest) -> RegistryResponse:
        logger.info(f"Attempting to register new entry: path={registry_data.resource_path}, version={registry_data.resource_version}")

        exists = await self.check_registry_entry(registry_data.resource_path, registry_data.resource_version, registry_data.event_id)
        if exists:
            logger.warning(
                f"Registry already exists for: path={registry_data.resource_path}, version={registry_data.resource_version}"
            )
            raise ValueError(
                f"Registry entry for resource_path '{registry_data.resource_path}' and version '{registry_data.resource_version}' already exists."
            )

        registry = Registry(
            event_id=registry_data.event_id,
            resource_path=registry_data.resource_path,
            resource_version=registry_data.resource_version,
            namespace=registry_data.namespace,
            status=registry_data.status,
            payload=registry_data.payload,
            meta=registry_data.meta,
            labels=registry_data.labels,
            tags=registry_data.tags
        )
        new_entry = await self.save_registry_entry(registry)

        event_data = {
            "registry_id": new_entry.registry_id,
            "parent_id": new_entry.event_id,
            "event_type": "RegistryEntryCreated",
            "state": "REGISTERED",
            "meta": {
                "registry_id": new_entry.registry_id,
                "parent_id": new_entry.event_id,
                "resource_path": new_entry.resource_path,
                "resource_version": new_entry.resource_version,
            },
        }

        response = await self.context.request.request(
            url=f"{self.context.config.noetl_url}/events/emit",
            method="POST",
            json_data=event_data,
        )

        if response.get("status_code") != 200:
            error_message = response.get("body", {}).get("detail", "Unknown error")
            logger.error(f"Failed to emit event: {error_message}")
            raise Exception(f"Failed to emit event: {error_message}")

        logger.info(f"Registry entry registered successfully. Event emitted for: {new_entry.registry_id}")
        return RegistryResponse(
            registry_id=new_entry.registry_id,
            event_id=new_entry.event_id,
            namespace=new_entry.namespace,
            status=new_entry.status,
            payload=new_entry.payload,
            meta=new_entry.meta,
            labels=new_entry.labels,
            tags=new_entry.tags,
            timestamp=new_entry.timestamp
        )