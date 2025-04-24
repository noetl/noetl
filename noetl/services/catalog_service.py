from noetl.shared import setup_logger, AppContext
from fastapi import HTTPException
import base64
import yaml
import json

logger = setup_logger(__name__, include_location=True)


class CatalogService:
    @staticmethod
    async def register_entry(content_base64: str, context: AppContext):
        try:

            decoded_yaml = base64.b64decode(content_base64).decode("utf-8")
            logger.info(f"Decoded YAML.")

            resource_data = yaml.safe_load(decoded_yaml)
            logger.info(f"Parsed YAML.")

            required_keys = ["path", "name", "kind"]
            for key in required_keys:
                if key not in resource_data:
                    error_message = f"Missing required field in resource: {key}."
                    logger.error(error_message)
                    raise HTTPException(status_code=400, detail=error_message)

            resource_path = resource_data.get("path")
            resource_version = resource_data.get("version", "1.0.0")
            resource_type = resource_data.get("kind")
            source = resource_data.get("source", "noetl")
            content = decoded_yaml
            resource_location = resource_data.get("location")
            meta = resource_data.get("meta", {})
            payload = resource_data
            validate_resource_type_query = """
                                           SELECT EXISTS (SELECT 1 FROM resource_type WHERE name = %s); \
                                           """
            resource_type_exists = await context.postgres.execute_query(
                validate_resource_type_query,
                (resource_type,)
            )

            if not resource_type_exists[0]["exists"]:
                logger.warning(f"Resource type '{resource_type}' not found in database. Trying to create it.")
                insert_resource_type_query = """
                                             INSERT INTO resource_type (name) \
                                             VALUES (%s) ON CONFLICT (name) DO NOTHING; \
                                             """
                await context.postgres.execute_query(insert_resource_type_query, (resource_type,))

            insert_query = """
                           INSERT INTO catalog (resource_path, resource_version, resource_type, source, \
                                                resource_location, content, payload, meta, timestamp) \
                           VALUES (%s, %s, %s, %s, %s,%s, %s::jsonb, %s::jsonb, \
                                   now()) ON CONFLICT (resource_path, resource_version) DO NOTHING; \
                           """
            await context.postgres.execute_query(
                insert_query,
                (
                    resource_path, resource_version, resource_type, source,
                    resource_location, content, json.dumps(payload), json.dumps(meta)
                )
            )

            message = f"Resource registered: {resource_path}"
            logger.info(message)
            return {
                "status": "success",
                "message": message
            }

        except yaml.YAMLError as e:
            error_message = f"YAML Parsing Error: {e}"
            logger.error(error_message)
            return HTTPException(status_code=400, detail=error_message)

        except Exception as e:
            error_message = f"Error registering resource: {e}"
            logger.error(error_message)
            return HTTPException(status_code=500, detail=error_message)


