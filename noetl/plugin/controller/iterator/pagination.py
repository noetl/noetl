"""
Pagination executor for HTTP actions within loops.

Handles automatic pagination of REST APIs with result merging and retry support.
"""

from typing import Dict, Any, List, Optional
import asyncio
from jinja2 import Environment

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger
from noetl.plugin.tools.http.executor import execute_http_task

logger = setup_logger(__name__, include_location=True)


def merge_response(
    accumulated: Any,
    response: Any,
    merge_strategy: str,
    merge_path: Optional[str]
) -> Any:
    """
    Merge response into accumulated results based on strategy.
    
    Args:
        accumulated: Previously accumulated data
        response: Current HTTP response (wrapped as {id, status, data: <api_response>})
        merge_strategy: Strategy (append|extend|replace|collect|sink_only)
        merge_path: JSONPath to data array in response (e.g., "data.data" for HTTP responses)
        
    Returns:
        Updated accumulated data
    """
    # Extract data from response using merge_path
    data_to_merge = response
    
    if merge_path:
        try:
            # Simple dot-notation path traversal
            # For HTTP responses with merge_path="data.data":
            #   First "data" extracts from wrapper: response.data (API response)
            #   Second "data" extracts items array: response.data.data (items)
            parts = merge_path.split('.')
            for part in parts:
                if isinstance(data_to_merge, dict):
                    data_to_merge = data_to_merge.get(part)
                    if data_to_merge is None:
                        logger.warning(f"PAGINATION.MERGE: Path part '{part}' not found, stopping traversal")
                        break
                else:
                    logger.warning(f"PAGINATION.MERGE: Cannot traverse '{part}' on non-dict type {type(data_to_merge)}")
                    break
            logger.debug(f"PAGINATION.MERGE: Extracted data using path '{merge_path}': {type(data_to_merge)}")
        except Exception as e:
            logger.warning(f"Failed to extract merge_path '{merge_path}': {e}")
            data_to_merge = response
    
    # Apply merge strategy
    if merge_strategy == 'append':
        # Append array elements
        if accumulated is None:
            accumulated = []
        
        if isinstance(data_to_merge, list):
            accumulated.extend(data_to_merge)
        else:
            accumulated.append(data_to_merge)
        
        return accumulated
    
    elif merge_strategy == 'extend':
        # Flatten nested arrays
        if accumulated is None:
            accumulated = []
        
        if isinstance(data_to_merge, list):
            for item in data_to_merge:
                if isinstance(item, list):
                    accumulated.extend(item)
                else:
                    accumulated.append(item)
        else:
            accumulated.append(data_to_merge)
        
        return accumulated
    
    elif merge_strategy == 'replace':
        # Keep only last response
        return response
    
    elif merge_strategy == 'collect':
        # Store all responses as array
        if accumulated is None:
            accumulated = []
        accumulated.append(response)
        return accumulated
    
    elif merge_strategy == 'sink_only':
        # Don't accumulate in memory - data is saved via sink mechanism
        # Return metadata about current page only
        if accumulated is None:
            accumulated = {'pages_fetched': 0, 'items_fetched': 0}
        
        accumulated['pages_fetched'] = accumulated.get('pages_fetched', 0) + 1
        if isinstance(data_to_merge, list):
            accumulated['items_fetched'] = accumulated.get('items_fetched', 0) + len(data_to_merge)
        
        return accumulated
    
    else:
        raise ValueError(f"Unknown merge_strategy: {merge_strategy}")


async def execute_with_retry_async(
    http_config: Dict[str, Any],
    context: Dict[str, Any],
    retry_config: Dict[str, Any],
    jinja_env: Environment,
    iteration: int
) -> Any:
    """
    Execute HTTP request with retry logic (async).
    
    Args:
        http_config: HTTP action configuration
        context: Execution context
        retry_config: Retry configuration
        jinja_env: Jinja2 environment
        iteration: Current iteration number
        
    Returns:
        HTTP response
        
    Raises:
        Exception: If all retry attempts fail
    """
    max_attempts = retry_config.get('max_attempts', 1)
    backoff = retry_config.get('backoff', 'fixed')
    initial_delay = retry_config.get('initial_delay', 1)
    max_delay = retry_config.get('max_delay', 60)
    
    last_error = None
    
    for attempt in range(max_attempts):
        try:
            # Execute HTTP action (async)
            result = await execute_http_task(http_config, context, jinja_env, {}, None)
            
            logger.info(f"PAGINATION: Raw HTTP result type={type(result)}, keys={result.keys() if isinstance(result, dict) else 'N/A'}")
            
            # Extract response data
            response = result.get('data') if isinstance(result, dict) else result
            
            logger.info(f"PAGINATION: Extracted response type={type(response)}, value={response if not isinstance(response, list) or len(str(response)) < 200 else f'list[{len(response)}]'}")
            logger.info(f"PAGINATION: Iteration {iteration}, attempt {attempt + 1} succeeded")
            return response
            
        except Exception as e:
            last_error = e
            logger.warning(f"PAGINATION: Iteration {iteration}, attempt {attempt + 1} failed: {e}")
            
            # Retry only if not last attempt
            if attempt < max_attempts - 1:
                # Calculate backoff delay
                if backoff == 'exponential':
                    delay = min(initial_delay * (2 ** attempt), max_delay)
                else:
                    delay = initial_delay
                
                logger.info(f"PAGINATION: Retrying in {delay}s...")
                await asyncio.sleep(delay)
    
    # All attempts failed
    raise last_error


async def execute_paginated_http_async(
    task_config: Dict[str, Any],
    pagination_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    sink_callback: Optional[callable] = None
) -> Any:
    """
    Execute paginated HTTP requests with automatic continuation (async).
    
    Args:
        task_config: HTTP action configuration
        pagination_config: Pagination configuration
        context: Execution context
        jinja_env: Jinja2 environment
        sink_callback: Optional callback to save data after each page (for sink support)
        
    Returns:
        Accumulated results (or metadata if using sink_only strategy)
        
    Raises:
        Exception: If execution fails
    """
    logger.info(f"PAGINATION: Starting paginated execution with strategy={pagination_config['merge_strategy']}")
    
    # Extract pagination config
    continue_while = pagination_config['continue_while']
    next_page = pagination_config['next_page']
    merge_strategy = pagination_config['merge_strategy']
    merge_path = pagination_config.get('merge_path')
    max_iterations = pagination_config.get('max_iterations', 1000)
    retry_config = pagination_config.get('retry', {})
    sink_config = pagination_config.get('sink')  # Per-page sink configuration
    
    # Initialize accumulated results
    accumulated = None
    iteration = 0
    
    # Build initial HTTP config
    http_config = dict(task_config)
    
    while iteration < max_iterations:
        # Build pagination context
        pag_context = dict(context)
        pag_context['iteration'] = iteration
        pag_context['accumulated'] = accumulated
        
        # Render HTTP config with current context
        rendered_config = {}
        for key, value in http_config.items():
            if isinstance(value, str):
                rendered_config[key] = render_template(jinja_env, value, pag_context)
            elif isinstance(value, dict):
                rendered_config[key] = render_dict(value, jinja_env, pag_context)
            else:
                rendered_config[key] = value
        
        # Execute HTTP request with retry (async)
        try:
            response = await execute_with_retry_async(
                rendered_config,
                pag_context,
                retry_config,
                jinja_env,
                iteration
            )
        except Exception as e:
            logger.error(f"PAGINATION: Failed at iteration {iteration}: {e}")
            raise
        
        # Merge response
        accumulated = merge_response(accumulated, response, merge_strategy, merge_path)
        
        logger.info(f"PAGINATION: Iteration {iteration} complete, merged results")
        
        # Execute sink for this page if configured
        if sink_config and sink_callback:
            try:
                # Extract the page data for sinking
                page_data = response
                if merge_path:
                    # Apply merge_path to extract specific data
                    parts = merge_path.split('.')
                    for part in parts:
                        if isinstance(page_data, dict):
                            page_data = page_data.get(part)
                        else:
                            break
                
                # Create page context for sink rendering
                page_context = dict(pag_context)
                page_context['page'] = {'data': page_data}
                page_context['page_number'] = iteration
                
                # Call sink callback with page data and context
                await sink_callback(sink_config, page_context, iteration)
                logger.info(f"PAGINATION: Saved page {iteration} via sink")
            except Exception as e:
                logger.error(f"PAGINATION: Failed to sink page {iteration}: {e}")
                # Continue pagination even if sink fails (can make this configurable)
        
        # Check continuation condition
        check_context = dict(pag_context)
        check_context['response'] = response
        
        try:
            should_continue = render_template(jinja_env, continue_while, check_context)
            # Convert to boolean
            if isinstance(should_continue, str):
                should_continue = should_continue.lower() in ('true', '1', 'yes')
            else:
                should_continue = bool(should_continue)
        except Exception as e:
            logger.warning(f"PAGINATION: Failed to evaluate continue_while: {e}")
            should_continue = False
        
        if not should_continue:
            logger.info(f"PAGINATION: Stopping - continue_while evaluated to False at iteration {iteration}")
            break
        
        # Update config for next page
        if 'params' in next_page:
            # Update query parameters
            if 'params' not in http_config:
                http_config['params'] = {}
            
            for param_key, param_expr in next_page['params'].items():
                # Render expression with response context
                update_context = dict(check_context)
                try:
                    new_value = render_template(jinja_env, str(param_expr), update_context)
                    http_config['params'][param_key] = new_value
                except Exception as e:
                    logger.warning(f"PAGINATION: Failed to update param '{param_key}': {e}")
        
        if 'body' in next_page:
            # Update request body
            http_config['body'] = render_dict(next_page['body'], jinja_env, check_context)
        
        if 'headers' in next_page:
            # Update headers
            if 'headers' not in http_config:
                http_config['headers'] = {}
            
            for header_key, header_expr in next_page['headers'].items():
                try:
                    new_value = render_template(jinja_env, str(header_expr), check_context)
                    http_config['headers'][header_key] = new_value
                except Exception as e:
                    logger.warning(f"PAGINATION: Failed to update header '{header_key}': {e}")
        
        iteration += 1
    
    if iteration >= max_iterations:
        logger.warning(f"PAGINATION: Reached max_iterations ({max_iterations}), stopping")
    
    logger.info(f"PAGINATION: Completed {iteration + 1} iterations, returning accumulated results")
    
    return accumulated


def execute_paginated_http(
    task_config: Dict[str, Any],
    pagination_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    sink_callback: Optional[callable] = None
) -> Any:
    """
    Execute paginated HTTP requests (sync wrapper).
    
    This is a synchronous wrapper that runs the async pagination executor.
    Safe to call from worker threads.
    
    Args:
        task_config: HTTP action configuration
        pagination_config: Pagination configuration
        context: Execution context
        jinja_env: Jinja2 environment
        sink_callback: Optional callback to save data after each page
        
    Returns:
        Accumulated results (or metadata if using sink_only strategy)
        
    Raises:
        Exception: If execution fails
    """
    try:
        # Create new event loop for thread safety
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(
                execute_paginated_http_async(
                    task_config,
                    pagination_config,
                    context,
                    jinja_env,
                    sink_callback
                )
            )
            return result
        finally:
            loop.close()
    except Exception as e:
        logger.error(f"PAGINATION: Execution failed: {e}")
        raise


def render_dict(d: Dict[str, Any], jinja_env: Environment, context: Dict[str, Any]) -> Dict[str, Any]:
    """
    Recursively render dictionary values with Jinja2.
    
    Args:
        d: Dictionary to render
        jinja_env: Jinja2 environment
        context: Rendering context
        
    Returns:
        Rendered dictionary
    """
    result = {}
    for key, value in d.items():
        if isinstance(value, str):
            result[key] = render_template(jinja_env, value, context)
        elif isinstance(value, dict):
            result[key] = render_dict(value, jinja_env, context)
        elif isinstance(value, list):
            result[key] = [
                render_template(jinja_env, item, context) if isinstance(item, str) else item
                for item in value
            ]
        else:
            result[key] = value
    return result
