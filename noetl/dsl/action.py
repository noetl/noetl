import asyncio
import httpx
import json
from noetl.runtime.interp import render_template
from noetl.logger.custom_setup import setup_logger
logger = setup_logger(__name__, include_location=True)

def get_retries(context):
    context_retries = context.get("retry", 0)
    try:
        context_retries = int(context_retries)
    except (ValueError, TypeError):
        context_retries = 0
    finally:
        return context_retries

class Action:
    def __init__(self, context, state, action_id = 1):
        self.action_id = action_id
        self.context = context
        self.state = state
        self.action_config = context.get("actionConfig", {})
        self.loop_config = self.action_config.get("loop", {})
        self.loop_items = self.loop_config.get("items", [])
        self.loop_iterator = self.loop_config.get("iterator", "item")
        self.timeout = self.action_config.get("timeout", 60.0)
        if not isinstance(self.loop_items, list):
            raise ValueError("'loop.items' should be a list.")
        self.break_on_error = self.action_config.get("break", True)

        logger.info(
            f"Initialized Action with timeout={self.timeout}s and break_on_error={self.break_on_error}.",
            extra=self.context.scope.get_id()
        )

    async def execute(self):
        if self.loop_items:
            logger.info(
                f"Executing Action with a loop. Total iterations: {len(self.loop_items)}.",
                extra=self.context.scope.get_id())
            results = []
            for idx, item in enumerate(self.loop_items):
                try:
                    loop_context = self.context.new_item_context({self.loop_iterator: item}, item)
                    result = await self.evaluate_command(loop_context)
                    results.append({"status": "success", "output": result, "item": item})
                except Exception as e:
                    if self.break_on_error:
                        logger.info(f"Breaking loop due to failure.", extra=self.context.scope.get_id())
                        raise e
                    logger.error(f"Error during execution: {e}", extra=self.context.scope.get_id())
                    results.append({"status": "failed", "error": str(e), "item": item})


            return results
        else:
            try:
                result = await self.evaluate_command(self.context)
                return {"status": "success", "output": result}
            except Exception as e:
                if self.context.break_on_failure:
                    raise e
                logger.error(f"Error during execution: {e}", extra=self.context.scope.get_id())

    async def evaluate_command(self, context):
        action_type = self.action_config.get("action", self.action_config.get("type", "")).lower()
        if action_type == "http":
            if not self.validate_http_config(self.action_config):
                raise ValueError("Invalid HTTP configuration.")
            return await self.http_call(context)
        else:
            logger.error(f"Unsupported action type: {action_type}", extra=self.context.scope.get_id())
            raise NotImplementedError(f"Unsupported action type: {action_type}")

    def validate_http_config(self, config):
        if not config.get("endpoint"):
            logger.error("HTTP configuration is missing the 'endpoint' field.", extra=self.context.scope.get_id())
            return False
        if not config.get("method"):
            logger.error("HTTP configuration is missing the 'method' field.", extra=self.context.scope.get_id())
            return False
        if config.get("method").upper() not in ["GET", "POST", "PUT", "DELETE", "PATCH"]:
            logger.error(f"Invalid HTTP method: {config.get('method')}.", extra=self.context.scope.get_id())
            return False
        return True

    async def http_call(self, context):
        response_data = "No response."
        retries = get_retries(context)
        retry_delay = 3
        method = self.action_config.get("method", "GET").upper()
        url = self.action_config.get("endpoint", "")
        params = json.loads(render_template(self.action_config.get("params", {}).copy(), context))
        logger.info(f"Sending {method} request to {url}", extra=context.scope.get_id() | {"params": params})
        if method in ["POST", "PUT", "PATCH"] and not params:
            logger.error(f"Request body is empty for {method} request.", extra=context.scope.get_id())
            raise ValueError(f"Request body must exists for {method} request.")

        for attempt in range(retries + 1):
            try:
                async with httpx.AsyncClient(timeout=self.timeout) as client:
                    response = await client.request(method, url, json=params)

                    if not response:
                        response_data = "No response."
                        logger.warning(response_data, extra=context.scope.get_id())
                        raise RuntimeError(response_data)

                    try:
                        response_data = response.json()
                    except json.JSONDecodeError:
                        response_data = response.text
                        logger.warning(
                            f"Response is not JSON. Falling back to raw text.",
                            extra=context.scope.get_id()
                        )
                        raise RuntimeError("Failed to parse JSON response.")

                    if response.status_code == 200:
                        logger.success(response_data.get('message'), extra=context.scope.get_id())
                        return response_data

                    logger.error(
                        f"Error: Unexpected status code {response.status_code} from {url} {response.text}",
                        extra=context.scope.get_id()
                    )
                    response.raise_for_status()

            except httpx.ReadTimeout as e:
                logger.error(
                    f"Request timeout after {self.timeout} seconds to {url}.",
                    extra=context.scope.get_id() | {"params": params, "error": str(e)}
                )

            except httpx.ConnectTimeout as e:
                logger.error(
                    f"Connection timeout after {self.timeout} seconds to {url}.",
                    extra=context.scope.get_id() | {"params": params, "error": str(e)}
                )

            except httpx.RequestError as e:
                logger.error(
                    f"HTTP request failed at the network level: {e}",
                    extra=context.scope.get_id() | {"params": params, "url": url}
                )

            except json.JSONDecodeError as e:
                logger.error(
                    f"Response is not valid JSON: {e}",
                    extra=context.scope.get_id() | {"response_body": response.text if response else "No response"}
                )

            except Exception as e:
                logger.error(
                    f"Error occurred during HTTP call: {e}",
                    extra=context.scope.get_id() | {"params": params, "url": url}
                )

                if attempt < retries:
                    logger.warning(
                        f"Retrying after failure: {e}. Attempt {attempt + 1}/{retries}.",
                        extra=context.scope.get_id() | {"params": params}
                    )
                    await asyncio.sleep(retry_delay)
                else:
                    logger.error(
                        f"HTTP call failed after {retries} retries: {e}",
                        extra=context.scope.get_id() | {"params": params}
                    )
                    if context.break_on_failure:
                        raise RuntimeError(f"Error in action execution: {e}")
                    return {"status": "failed", "error": str(e)}
