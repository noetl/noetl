from typing import Optional
from sqlmodel import select
from noetl.util import setup_logger
from noetl.appctx.app_context import AppContext
from fastapi import HTTPException
import base64
import yaml
import json
from datetime import datetime, UTC
from sqlmodel.ext.asyncio.session import AsyncSession
from noetl.api.models.resources import Catalog, ResourceType, EventType, Event

logger = setup_logger(__name__, include_location=True)

async def check_resource_type(session: AsyncSession, resource_type: str) -> bool:
    return await session.get(ResourceType, resource_type) is not None


async def create_resource_type(session: AsyncSession, resource_type: str):
    exists = await check_resource_type(session, resource_type)
    if not exists:
        new_resource_type = ResourceType(name=resource_type)
        session.add(new_resource_type)
        await session.commit()
        logger.info(f"Resource type '{resource_type}' created.")
    else:
        logger.info(f"Resource type '{resource_type}' already exists.")

async def check_catalog_entry(
    session: AsyncSession,
    resource_path: str,
    content: str
) -> Optional[Catalog]:
    stmt = select(Catalog).where(Catalog.resource_path == resource_path).order_by(Catalog.resource_version.desc()).limit(1)
    result = await session.exec(stmt)
    logger.debug(f"Catalog entry query result: {result}")
    entry = result.first()
    if entry and entry.content == content:
        logger.info(
            f"Catalog entry for resource_path '{resource_path}' has the same content (version={entry.resource_version})."
        )
        return entry
    return None

async def get_latest_catalog_entry(session: AsyncSession, resource_path: str) -> Optional[Catalog]:
    stmt = select(Catalog).where(Catalog.resource_path == resource_path).order_by(Catalog.resource_version.desc()).limit(
        1)
    result = await session.exec(stmt)
    logger.debug(f"Catalog entry query result: {result}")
    entry = result.first()
    logger.info(
        f"Catalog entry for resource_path '{resource_path}'", extra=entry.dict() if entry else None
    )
    return entry


def increment_version(version: str) -> str:
    version_parts = version.split(".")
    version_parts[-1] = str(int(version_parts[-1]) + 1)
    return ".".join(version_parts)


async def create_catalog_entry(session: AsyncSession, current_content: str, resource_data: dict):
    resource_path = resource_data.get("path")
    resource_type = resource_data.get("kind")
    latest_entry = await get_latest_catalog_entry(session, resource_path)
    if latest_entry and latest_entry.content == current_content:
        logger.info(f"Catalog entry for '{resource_path}' already exists with version {latest_entry.resource_version}.")
        return latest_entry

    new_version = increment_version(latest_entry.resource_version) if latest_entry else "1.0.0"
    new_catalog_entry = Catalog(
        resource_path=resource_path,
        resource_version=new_version,
        resource_type=resource_type,
        content=current_content,
        payload=resource_data,
        meta=resource_data.get("meta", {}),
        source=resource_data.get("source", "inline"),
        resource_location=resource_data.get("location"),
        timestamp=datetime.now(UTC),
    )
    session.add(new_catalog_entry)
    await session.commit()
    logger.info(f"New catalog entry created with version '{new_version}' for path '{resource_path}'.")
    return new_catalog_entry


async def check_event_type(session: AsyncSession, event_type: str) -> bool:
    return await session.get(EventType, event_type) is not None


async def create_event_type(session: AsyncSession, event_type: str):
    exists = await check_event_type(session, event_type)
    if not exists:
        new_event_type = EventType(name=event_type, template="Default event template")
        session.add(new_event_type)
        await session.commit()
        logger.info(f"Event type '{event_type}' created.")
    else:
        logger.info(f"Event type '{event_type}' already exists.")

async def log_event(session: AsyncSession, event_data: dict):
    event_id = event_data.get("event_id")
    existing_event_query = select(Event).where(Event.event_id == event_id)
    existing_event_result = await session.exec(existing_event_query)
    existing_event = existing_event_result.first()

    if existing_event:
        logger.info(f"Event '{event_id}' already exists.")
        return {
            "resource_path": existing_event.resource_path,
            "resource_version": existing_event.resource_version,
            "status": "already_exists",
            "message": f"Event '{event_id}' already exists."
        }
    new_event = Event(
        event_id=event_id,
        event_type=event_data.get("event_type"),
        resource_path=event_data.get("resource_path"),
        resource_version=event_data.get("resource_version"),
        event_message=event_data.get("event_message"),
        content=event_data.get("content"),
        payload=event_data.get("payload"),
        context=event_data.get("context"),
        meta=event_data.get("meta"),
        timestamp=datetime.now(UTC),
    )
    session.add(new_event)
    await session.commit()
    logger.info(
        f"Event '{event_id}' logged for resource '{event_data.get('resource_path')}' (version: {event_data.get('resource_version')})."
    )
    logger.debug(f"Event details: {json.dumps(event_data, indent=2)}")
    return {
        "resource_path": event_data["resource_path"],
        "resource_version": event_data["resource_version"],
        "status": "success",
        "message": f"Event '{event_id}' logged successfully."
    }


class CatalogService:
    @staticmethod
    async def register_entry(content_base64: str, event_type: str, context: AppContext):
        try:
            decoded_yaml = base64.b64decode(content_base64).decode("utf-8")
            resource_data = yaml.safe_load(decoded_yaml)
            for field in ["path", "name", "kind"]:
                if field not in resource_data:
                    raise HTTPException(status_code=400, detail=f"Missing required field: {field}")

            async with context.postgres.get_session() as session:
                await create_resource_type(session, resource_data.get("kind"))
                catalog_entry = await create_catalog_entry(session, decoded_yaml, resource_data)
                if catalog_entry.content == decoded_yaml:
                    return {
                        "status": "already_exists",
                        "message": f"Catalog entry for '{catalog_entry.resource_path}' already exists with version {catalog_entry.resource_version}."
                    }
                await create_event_type(session, event_type)
                event_id = f"{catalog_entry.resource_path}:{event_type}:{catalog_entry.resource_version}"
                event_data = {
                    "event_id": event_id,
                    "event_type": event_type,
                    "resource_path": catalog_entry.resource_path,
                    "resource_version": catalog_entry.resource_version,
                }
                event_result = await log_event(session, event_data)

            return {
                "status": "success",
                "message": f"Catalog entry for '{resource_data['path']}' successfully registered with version {catalog_entry.resource_version}."
            }

        except yaml.YAMLError as e:
            logger.error(f"YAML Parsing Error: {e}")
            raise HTTPException(status_code=400, detail=f"YAML Parsing Error: {e}.")
        except Exception as e:
            logger.error(f"Unexpected Error: {e}")
            raise HTTPException(status_code=500, detail=f"Error registering resource: {e}.")

    @staticmethod
    async def fetch_all_entries(context: AppContext):
        try:
            async with context.postgres.get_session() as session:
                stmt = select(Catalog).order_by(Catalog.timestamp.desc())
                result = await session.exec(stmt)
                entries = result.fetchall()
                logger.info(f"Fetched {len(entries)} catalog entries.")
                return [
                    {
                        "id": entry.resource_path,
                        "name": entry.payload.get("name"),
                        "event_type": entry.payload.get("kind"),
                        "version": entry.resource_version,
                        "timestamp": entry.timestamp,
                    }
                    for entry in entries
                ]
        except Exception as e:
            logger.error(f"Error fetching catalog entries: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to fetch catalog entries: {e}.")

    @staticmethod
    async def fetch_entry_id(context: AppContext, id: str):
        async with context.postgres.get_session() as session:
            stmt = select(Catalog).where(Catalog.resource_path == id)
            result = await session.exec(stmt)
            entry = result.first()
            if entry:
                return {
                    "id": entry.resource_path,
                    "content": entry.content,
                    "payload": entry.payload
                }
            return None


