from typing import Optional
from sqlmodel import select
from noetl.util.serialization import encode_version, increment_version
from noetl.connectors.hub import ConnectorHub
from fastapi import HTTPException
import base64
import yaml
from datetime import datetime, timezone
from noetl.api.models.catalog import Catalog
from noetl.api.models.dict_resource import DictResource
from noetl.api.services.event import get_event_service
from noetl.util import setup_logger
logger = setup_logger(__name__, include_location=True)

def get_catalog_service(context: ConnectorHub):
    return CatalogService(context)

class CatalogService:
    def __init__(self, context: ConnectorHub):
        self.app_context = context
        self.event_service = get_event_service(context)

    async def resource_type_exists(self, resource_type: str) -> bool:
        async with self.app_context.postgres.get_session() as session:
            return await session.get(DictResource, resource_type) is not None

    async def create_resource_type(self, resource_type: str):
        exists = await self.resource_type_exists(resource_type)
        if not exists:
            new_resource_type = DictResource(name=resource_type)
            async with self.app_context.postgres.get_session() as session:
                session.add(new_resource_type)
                await session.commit()
            logger.info(f"Resource type '{resource_type}' created.")
        else:
            logger.info(f"Resource type '{resource_type}' already exists.")


    async def get_catalog_entry(self, path: str, version: Optional[str] = None) -> Optional[Catalog]:
        async with self.app_context.postgres.get_session() as session:
            if version:
                stmt = select(Catalog).where(
                    (Catalog.path == path) & (Catalog.version == version)
                )
            else:
                stmt = (
                    select(Catalog)
                    .where(Catalog.path == path)
                    .order_by(Catalog.version.desc())
                    .limit(1)
                )
            result = await session.exec(stmt)
            entry = result.first()
        logger.debug(
            f"Catalog entry for path '{path}'",
            extra=entry.dict() if entry else None
        )
        return entry

    async def catalog_entry_exists(self, path: str, content: str) -> Optional[Catalog]:
        entry = await self.get_catalog_entry(path)
        if entry and entry.content.strip() == content.strip():
            logger.debug(
                f"Catalog entry for path '{path}' version '{entry.version}' has the same content."
            )
            return entry
        return None


    async def create_catalog_entry(self, current_content: str, resource_data: dict, version=None) -> Catalog:
        try:
            path = resource_data.get("path")
            resource_type = resource_data.get("kind")
            if not path or not resource_type:
                raise ValueError("Missing fields: 'path' / 'kind'.")

            latest_entry = await self.get_catalog_entry(path, version)
            meta = {"path": path}
            if latest_entry:
                meta["version"] = latest_entry.version
            event = await self.event_emit(
                event_type="CatalogRegisterRequested",
                state="REQUESTED",
                meta=meta
            )
            if latest_entry and latest_entry.content.strip() == current_content.strip():
                log_message=f"Catalog entry '{path}' version {latest_entry.version} already exists."
                logger.info(log_message)
                event = await self.event_emit(
                    event_type="CatalogRegisterCanceled",
                    state="CANCELED",
                    parent_id=event.get("body", {}).get("event_id"),
                    meta={
                    "path": latest_entry.path,
                    "version": latest_entry.version,
                    "message": log_message
                }
                )
                return latest_entry
            new_version = encode_version(increment_version(latest_entry.version) if latest_entry else "1.0.0")
            new_catalog_entry = Catalog(
                path=path,
                version=new_version,
                resource_type=resource_type,
                content=current_content,
                payload=resource_data,
                meta=resource_data.get("meta", {}),
                source=resource_data.get("source", "inline"),
                resource_location=resource_data.get("location"),
                timestamp=datetime.now(timezone.utc),
            )
            async with self.app_context.postgres.get_session() as session:
                session.add(new_catalog_entry)
                await session.commit()
            logger.info(f"New catalog entry path='{path}', and version='{new_version}' created.")
            event = await self.event_emit(
                event_type="CatalogRegisterRegistered",
                state="REGISTERED",
                parent_id=event.get("body", {}).get("event_id"),
                meta={
                    "path": new_catalog_entry.path,
                    "version": new_catalog_entry.version
                }
            )
            return new_catalog_entry
        except Exception as e:
            logger.error(f"Error creating catalog entry: {e}")
            raise HTTPException(status_code=500, detail=f"Error creating catalog entry: {e}.")

    async def event_emit(self, event_type: str, state: str, meta: dict, parent_id: Optional[str] = None):
        event_data = {
            "event_type": event_type,
            "state": state,
            "component_id": "catalog",
            "meta": meta
        }
        if parent_id:
            event_data["parent_id"] = parent_id
        response = await self.app_context.request.request(
            url=f"{self.app_context.config.noetl_url}/events/emit",
            method="POST",
            json_data=event_data
        )
        if response.get("status_code") != 200:
            logger.error(f"Failed to emit event: {response.get('body')}")
            raise HTTPException(status_code=response.get("status_code"), detail="Failed to emit event.")
        return response

    async def register_entry(self, content_base64: str, state: str):
        try:
            decoded_yaml = base64.b64decode(content_base64).decode("utf-8")
            resource_data = yaml.safe_load(decoded_yaml)
            for field in ["path", "name", "kind"]:
                if field not in resource_data:
                    raise HTTPException(status_code=400, detail=f"Missing field: {field}")

            await self.create_resource_type(resource_data.get("kind"))

            event = await self.event_emit(
                event_type="CatalogRegisterRequested",
                state=state,
                meta={"path": resource_data["path"]}
            )

            existing_entry = await self.catalog_entry_exists(resource_data["path"], decoded_yaml)
            if existing_entry:
                logger.info(
                    f"Catalog entry already exists for path='{resource_data['path']}' with version '{existing_entry.version}'."
                )
                log_message = f"Catalog entry for '{resource_data['path']}' already exists with version {existing_entry.version}."
                event = await self.event_emit(
                    event_type="CatalogRegisterCanceled",
                    state="CANCELED",
                    parent_id=event.get("body", {}).get("event_id"),
                    meta={
                    "path": existing_entry.path,
                    "version": existing_entry.version,
                    "message": log_message
                }
                )
                return {
                    "status": "already_exists",
                    "message": log_message
                }
            catalog_entry = await self.create_catalog_entry(decoded_yaml, resource_data)
            if not catalog_entry:
                raise HTTPException(status_code=400, detail="Failed to create catalog entry.")

            event = await self.event_emit(
                event_type="CatalogRegisterRegistered",
                state="REGISTERED",
                parent_id=event.get("body", {}).get("event_id"),
                meta={
                    "path": catalog_entry.path,
                    "version": catalog_entry.version
                }
            )

            if event.get("status_code") != 200:
                logger.error(f"Failed to emit event: {event.get('body')}")
                raise HTTPException(status_code=event.get("status_code"), detail="Failed to emit event.")

            return {
                "status": "success",
                "message": f"Catalog entry for {resource_data.get('path')} successfully registered with version {catalog_entry.version}."
            }

        except yaml.YAMLError as e:
            logger.error(f"YAML Parsing Error: {e}")
            raise HTTPException(status_code=400, detail=f"YAML Parsing Error: {e}.")
        except Exception as e:
            logger.exception(f"Unexpected Error: {e}")
            raise HTTPException(status_code=500, detail=f"Error registering resource: {e}.")


    async def fetch_all_entries(self):
        try:
            async with self.app_context.postgres.get_session() as session:
                stmt = select(Catalog).order_by(Catalog.timestamp.desc())
                result = await session.exec(stmt)
                entries = result.fetchall()
                logger.info(f"Fetched {len(entries)} catalog entries.")
                return [
                    {
                        "path": entry.path,
                        "name": entry.payload.get("name"),
                        "resource_type": entry.payload.get("kind"),
                        "version": entry.version,
                        "timestamp": entry.timestamp,
                    }
                    for entry in entries
                ]
        except Exception as e:
            logger.error(f"Error fetching catalog entries: {e}.")
            raise HTTPException(status_code=500, detail=f"Failed to fetch catalog entries: {e}.")

    async def fetch_entry(self, path: str, version: str) -> Optional[Catalog]:
        entry = await self.get_catalog_entry(path, version)
        if entry:
            logger.info(
                f"Fetched catalog entry: path='{path}', version='{version}'"
            )
            return {
                "path": entry.path,
                "version": entry.version,
                "content": entry.content,
                "payload": entry.payload
            }
        else:
            logger.warning(
                f"Catalog entry is missing for path='{path}' and version='{version}'"
            )
            return None
