from typing import Optional
from sqlalchemy.future import select
from noetl.api.schemas.workload import WorkloadResponse, WorkloadRequest
from noetl.connectors.hub import ConnectorHub
from noetl.api.models.workload import Workload
from noetl.util import setup_logger

logger = setup_logger(__name__, include_location=True)


def get_registry_service(context: ConnectorHub):
    return WorkloadService(context)


class WorkloadService:
    def __init__(self, context: ConnectorHub) -> None:
        self.context = context

    async def check_workload_entry(self, resource_path: str, resource_version: str,
                                   event_id: Optional[str] = None) -> bool:
        logger.debug(
            f"Checking if registry exists for path={resource_path}, version={resource_version}, event_id={event_id}")

        async with self.context.postgres.get_session() as session:
            query = select(Workload).where(
                Workload.resource_path == resource_path,
                Workload.resource_version == resource_version,
            )
            if event_id:
                query = query.where(Workload.event_id == event_id)

            result = await session.execute(query)
            workload_entry = result.scalars().first()
            return workload_entry

    async def save_workload_entry(self, workload_data: Workload) -> (

            Workload):
        logger.info(f"Saving workload: path={workload_data.resource_path}, version={workload_data.resource_version}")

        async with self.context.postgres.get_session() as session:
            session.add(workload_data)
            await session.commit()
            await session.refresh(workload_data)
        return workload_data

    async def register(self, workload_data: WorkloadRequest) -> WorkloadResponse:
        logger.info(f"Attempting to register new entry: path={workload_data.resource_path}, version={workload_data.resource_version}")

        exists = await self.check_workload_entry(workload_data.resource_path, workload_data.resource_version, workload_data.event_id)
        if exists:
            logger.warning(
                f"Workload already exists for: path={workload_data.resource_path}, version={workload_data.resource_version}"
            )
            raise ValueError(
                f"Workload entry for resource_path '{workload_data.resource_path}' and version '{workload_data.resource_version}' already exists."
            )

        registry = Workload(
            event_id=workload_data.event_id,
            resource_path=workload_data.resource_path,
            resource_version=workload_data.resource_version,
            namespace=workload_data.namespace,
            status=workload_data.status,
            payload=workload_data.payload,
            meta=workload_data.meta,
            labels=workload_data.labels,
            tags=workload_data.tags
        )
        new_entry = await self.save_workload_entry(registry)

        event_data = {
            "workload_id": new_entry.workload_id,
            "parent_id": new_entry.event_id,
            "event_type": "WorkloadEntryCreated",
            "state": "REGISTERED",
            "meta": {
                "workload_id": new_entry.workload_id,
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

        logger.info(f"workload entry registered. Event emitted for: {new_entry.workload_id}")
        return WorkloadResponse(
            workload_id=new_entry.workload_id,
            event_id=new_entry.event_id,
            namespace=new_entry.namespace,
            status=new_entry.status,
            payload=new_entry.payload,
            meta=new_entry.meta,
            labels=new_entry.labels,
            tags=new_entry.tags,
            timestamp=new_entry.timestamp
        )
