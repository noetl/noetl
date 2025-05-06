from noetl.api.models.event import Event
from noetl.api.services.event import EventService
from noetl.ctx.app_context import AppContext
from noetl.api.models.registry import Registry
from noetl.util import setup_logger

logger = setup_logger(__name__, include_location=True)

from noetl.api.schemas.registry import RegistryRequest
from noetl.api.schemas.event import EmitEventRequest


async def dispatch_event(event: Event, event_service: EventService):
    try:
        logger.info(f"Dispatching event: {event.state}", extra=event.model_dump())
        if event.event_type == "JobExecutionRequested":
            logger.info("Event type '{event.event_type} detected. Creating a registry entry.")
            await dispatch_registry_event(event, event_service)
    except Exception as e:
        logger.error(f"Failed to dispatch event: {str(e)}", extra=event.model_dump())
        raise



async def dispatch_registry_event(event: Event, event_service: EventService):
    try:
        logger.info(f"Dispatching registry event: {event.state}", extra=event.model_dump())
        app_context: AppContext = event_service.context

        if event.event_type == "RegistryEntryCreated":
            logger.info("Event type 'RegistryEntryCreated' detected. Creating a registry entry.")

            resource_path = event.meta.get("resource_path")
            resource_version = event.meta.get("resource_version")

            registry_data = RegistryRequest(
                event_id=event.event_id,
                resource_path=event.meta.get("resource_path"),
                resource_version=event.meta.get("resource_version"),
                namespace={"namespace": event.meta.get("namespace", resource_path)},
                status=event.status,
                payload=event.payload,
                meta=event.meta,
                labels=event.labels,
                tags=event.tags,
            )

            response = await app_context.request.request(
                url=f"{app_context.config.noetl_url}/registry/register",
                method="POST",
                json_data=registry_data
            )

            if response.get("status_code") != 201:
                raise Exception(f"Failed to register registry entry: {response.get('body')}")

            logger.info(f"Registry entry created successfully: {response.get('body')}")

    except Exception as e:
        logger.error(f"Failed to dispatch registry event: {str(e)}", extra=event.model_dump())
        raise