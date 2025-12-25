"""
Playbook task executor.

Executes sub-playbooks by delegating to the broker orchestration engine.
"""

import uuid
import datetime
from typing import Dict, Any, Optional, Callable
from jinja2 import Environment

from noetl.core.logger import setup_logger
from .loader import load_playbook_content, render_playbook_content
from .context import (
    build_nested_context, 
    extract_parent_identifiers,
    validate_loop_configuration
)

logger = setup_logger(__name__, include_location=True)


def log_task_event(
    log_event_callback: Optional[Callable],
    event_type: str,
    task_id: str,
    task_name: str,
    status: str,
    duration: float,
    context: Dict[str, Any],
    result: Optional[Dict[str, Any]],
    task_with: Dict[str, Any],
    error: Optional[str] = None
) -> None:
    """
    Log task event if callback provided.
    
    Args:
        log_event_callback: Optional event logging callback
        event_type: Event type (task_end, task_error)
        task_id: Task ID
        task_name: Task name
        status: Task status (success, error)
        duration: Task duration in seconds
        context: Execution context
        result: Task result (if success)
        task_with: Task with-parameters
        error: Error message (if error)
    """
    if not log_event_callback:
        return
    
    logger.debug(f"PLAYBOOK: Writing {event_type} event log")
    
    event_id = str(uuid.uuid4())
    metadata = {'with_params': task_with}
    
    if error:
        metadata['error'] = error
    
    log_event_callback(
        event_type, task_id, task_name, 'playbook',
        status, duration, context, result,
        metadata, event_id
    )


def execute_playbook_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Dict[str, Any],
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a playbook task.
    
    This executor:
    1. Loads playbook content (from path or inline)
    2. Renders playbook templates
    3. Builds nested execution context
    4. Validates configuration (no deprecated loop blocks)
    5. Delegates to broker for orchestration
    6. Returns execution result
    
    Args:
        task_config: The task configuration
        context: The context to use for rendering templates
        jinja_env: The Jinja2 environment for template rendering
        task_with: The rendered 'with' parameters dictionary
        log_event_callback: A callback function to log events
        
    Returns:
        A dictionary of the task result with keys:
        - id: Task ID
        - status: 'success' or 'error'
        - data: Broker execution result (if success)
        - execution_id: Nested execution ID (if success)
        - duration: Task duration in seconds
        - error: Error message (if error)
        
    Raises:
        ValueError: If deprecated loop configuration detected
    """
    logger.debug(f"PLAYBOOK.EXECUTE_PLAYBOOK_TASK: Entry - task_config={task_config}, task_with={task_with}")
    
    task_id = str(uuid.uuid4())
    task_name = task_config.get('task', 'playbook_task')
    start_time = datetime.datetime.now()
    
    logger.debug(f"PLAYBOOK: task_id={task_id} | name={task_name} | start={start_time.isoformat()}")
    
    try:
        # Step 1: Load playbook content
        playbook_path, playbook_content, error = load_playbook_content(
            task_config, task_id
        )
        
        if error:
            return {
                'id': task_id,
                'status': 'error',
                'error': error
            }
        
        # Step 2: Render playbook content
        rendered_content, error = render_playbook_content(
            playbook_content, context, jinja_env, task_id
        )
        
        if error:
            return {
                'id': task_id,
                'status': 'error',
                'error': error
            }
        
        # Step 3: Build nested execution context
        nested_context = build_nested_context(context, task_with)
        
        # Step 4: Get playbook version
        playbook_version = task_config.get('version', 'latest')
        
        # Step 5: Extract parent identifiers
        parent_execution_id, parent_event_id, parent_step = \
            extract_parent_identifiers(context, task_name)
        
        logger.info(
            f"PLAYBOOK: Executing nested playbook - path={playbook_path}, "
            f"version={playbook_version}, parent_execution_id={parent_execution_id}"
        )
        
        # Step 6: Validate configuration (no deprecated loop blocks)
        validate_loop_configuration(task_config)
        
        # Step 7: Execute via server API to ensure proper catalog registration
        try:
            # Make HTTP request to server's /api/run/playbook endpoint
            import os
            import requests
            
            server_url = os.environ.get("NOETL_SERVER_URL", "http://localhost:8083").rstrip('/')
            if not server_url.endswith('/api'):
                server_url = server_url + '/api'
            execute_url = f"{server_url}/run/playbook"
            
            logger.info(
                f"PLAYBOOK: Calling {execute_url} for nested playbook execution "
                f"with parent_execution_id={parent_execution_id}"
            )
            
            # Extract iterator metadata from context if present
            iterator_meta = {}
            try:
                if '_loop' in context and isinstance(context['_loop'], dict):
                    iterator_meta = {
                        'iterator_index': context['_loop'].get('current_index'),
                        'iterator_count': context['_loop'].get('count'),
                        'iterator_item': context['_loop'].get('item')
                    }
                    logger.debug(f"PLAYBOOK: Extracted iterator metadata: {iterator_meta}")
            except Exception as e:
                logger.debug(f"PLAYBOOK: No iterator metadata found: {e}")
            
            # Build execution request payload
            request_payload = {
                "path": playbook_path or f"nested/{task_name}",
                "version": playbook_version,
                "type": "playbook",
                "parameters": nested_context,
                "merge": True,
                "sync_to_postgres": True,
                "context": {
                    "parent_execution_id": str(parent_execution_id) if parent_execution_id else None,
                    "parent_event_id": str(parent_event_id) if parent_event_id else None,
                    "parent_step": parent_step
                },
                "metadata": iterator_meta if iterator_meta else None
            }
            
            # Make synchronous HTTP POST request
            response = requests.post(
                execute_url,
                json=request_payload,
                timeout=30
            )
            
            if response.status_code != 200:
                error_detail = response.json().get('detail', response.text) if response.text else 'Unknown error'
                raise Exception(f"Server returned status {response.status_code}: {error_detail}")
            
            result = response.json()
            
            logger.info(
                f"PLAYBOOK: Server execution accepted with "
                f"status={result.get('status')}, "
                f"execution_id={result.get('execution_id')}"
            )
            
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            logger.info(f"PLAYBOOK: Nested playbook execution completed | duration={duration}s")
            
            # Log success event
            log_task_event(
                log_event_callback, 'task_end', task_id, task_name,
                'success', duration, context, result, task_with
            )
            
            # Return success result
            success_result = {
                'id': task_id,
                'status': 'success',
                'data': result,
                'execution_id': result.get('execution_id'),
                'duration': duration
            }
            
            logger.debug(f"PLAYBOOK: Exit (success) - result={success_result}")
            return success_result
            
        except Exception as e:
            error_msg = f"Playbook execution failed: {str(e)}"
            logger.error(f"PLAYBOOK: {error_msg}", exc_info=True)
            
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            # Log error event
            log_task_event(
                log_event_callback, 'task_error', task_id, task_name,
                'error', duration, context, None, task_with, error_msg
            )
            
            return {
                'id': task_id,
                'status': 'error',
                'error': error_msg,
                'duration': duration
            }
            
    except Exception as e:
        error_msg = f"Unexpected error in playbook task: {str(e)}"
        logger.error(f"PLAYBOOK: {error_msg}", exc_info=True)
        
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.debug(f"PLAYBOOK: Task duration={duration} seconds (error path)")
        
        # Log error event
        log_task_event(
            log_event_callback, 'task_error', task_id, task_name,
            'error', duration, context, None, task_with, error_msg
        )
        
        result = {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }
        logger.debug(f"PLAYBOOK: Exit (error) - result={result}")
        return result
