from noetl.api.schemas.event import EventSchema
from noetl.api.services.event import EventService
from noetl.ctx.app_context import AppContext
from noetl.api.models.registry import Registry
from noetl.util import setup_logger

logger = setup_logger(__name__, include_location=True)

from noetl.api.schemas.registry import RegistryRequest
from noetl.api.schemas.event import EmitEventRequest


async def dispatch_event(event: EventSchema, event_service: EventService):
    try:
        logger.info(f"Dispatching event: {event.state}", extra=event.model_dump())
        if event.event_type == "JobRegistryRequested":
            logger.info(f"Event type '{event.event_type} detected. Creating a registry entry.")
            await dispatch_registry_event(event, event_service)
    except Exception as e:
        logger.error(f"Failed to dispatch event: {str(e)}", extra=event.model_dump())
        raise



async def dispatch_registry_event(event: EventSchema, event_service: EventService):
    try:
        logger.info(f"Dispatching registry event: {event.state}", extra=event.model_dump())
        app_context: AppContext = event_service.context

        if event.event_type == "JobRegistryRequested":
            logger.debug(f"Event type '{event.event_type}' detected.")

            registry_data = RegistryRequest(
                event_id=event.event_id,
                resource_path=event.meta.get("resource_path"),
                resource_version=event.meta.get("resource_version"),
                namespace={"namespace": event.meta.get("namespace", event.meta.get("resource_path"))},
                status=event.status,
                payload=event.payload,
                meta=event.meta,
                labels=event.labels,
                tags=event.tags,
            )
            registry_data_dict = registry_data.model_dump()
            logger.debug(f"Registry data: {registry_data_dict}")
            response = await app_context.request.request(
                url=f"{app_context.config.noetl_url}/registry/register",
                method="POST",
                json_data= registry_data.model_dump()
            )

            if response.get("status_code") != 201:
                raise Exception(f"Failed to register registry entry: {response.get('body')}")

            logger.info(f"Registry entry created: {response.get('body')}")

    except Exception as e:
        logger.error(f"Failed to dispatch registry event: {str(e)}", extra=event.model_dump())
        raise