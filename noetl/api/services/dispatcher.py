from noetl.api.schemas.event import EventSchema
from noetl.api.services.event import EventService
from noetl.connectors.hub import ConnectorHub
from noetl.util import setup_logger

logger = setup_logger(__name__, include_location=True)

from noetl.api.schemas.workload import WorkloadRequest


async def dispatch_event(event: EventSchema, event_service: EventService):
    try:
        logger.info(f"Dispatching event: {event.state}", extra=event.model_dump())
        if event.event_type == "JobWorkloadRequested":
            logger.info(f"Event type '{event.event_type} detected. Creating a registry entry.")
            await dispatch_workload_event(event, event_service)
    except Exception as e:
        logger.error(f"Failed to dispatch event: {str(e)}", extra=event.model_dump())
        raise



async def dispatch_workload_event(event: EventSchema, event_service: EventService):
    try:
        logger.info(f"Dispatching workload event: {event.state}", extra=event.model_dump())
        app_context: ConnectorHub = event_service.context

        if event.event_type == "JobWorkloadRequested":
            logger.debug(f"Event type '{event.event_type}' detected.")

            workload_data = WorkloadRequest(
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
            workload_data_dict = workload_data.model_dump()
            logger.debug(f"Registry data: {workload_data_dict}")
            response = await app_context.request.request(
                url=f"{app_context.config.noetl_url}/workload/register",
                method="POST",
                json_data= workload_data.model_dump()
            )

            if response.get("status_code") != 201:
                raise Exception(f"Failed to register registry entry: {response.get('body')}")

            logger.info(f"Workload entry created: {response.get('body')}")

    except Exception as e:
        logger.error(f"Failed to dispatch workload event: {str(e)}", extra=event.model_dump())
        raise
