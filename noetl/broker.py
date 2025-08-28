import json
import os
import uuid
import datetime
import tempfile
import httpx
import traceback
from typing import Dict, List, Any, Tuple, Optional
from noetl.job import report_event
from noetl.render import render_template
from noetl.common import deep_merge, get_bool
from noetl.logger import setup_logger, log_error
logger = setup_logger(__name__, include_location=True)

class Broker:

    def __init__(self, agent, server_url=None):
        """
        Initialize the Broker.

        Args:
            agent: The NoETLAgent instance
            server_url: The URL of the server to report events
        """
        self.agent = agent
        # Normalize server URL to point to API base (ensure trailing /api)
        base_url = server_url or os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082')
        if base_url and not base_url.rstrip('/').endswith('/api'):
            base_url = base_url.rstrip('/') + '/api'
        self.server_url = base_url
        self.event_reporting_enabled = True
        self.validate_server_url()

    def has_log_event(self):
        """
        Check if the agent has a log_event method.

        Returns:
            bool: True if the agent has a log_event method, False otherwise
        """
        return hasattr(self.agent, 'log_event') and callable(getattr(self.agent, 'log_event'))

    def write_event_log(self, event_type, node_id, node_name, node_type, status, duration,
                        input_context, output_result, metadata=None, parent_event_id=None, **kwargs):
        """
        The call of log_event on the agent if it exists.

        Args:
            event_type: The type of event
            node_id: The ID of the node
            node_name: The name of the node
            node_type: The type of node
            status: The status of the event
            duration: The duration of the event
            input_context: The input context
            output_result: The output result
            metadata: metadata
            parent_event_id: The ID of the parent event
            **kwargs: keyword arguments to log_event

        Returns:
            The event ID if log_event exists, None otherwise
        """
        if self.has_log_event():
            return self.agent.log_event(
                event_type, node_id, node_name, node_type, status, duration,
                input_context, output_result, metadata, parent_event_id, **kwargs
            )
        else:
            logger.warning(f"Agent does not have log_event method. Event type: {event_type}, Node: {node_name}")
            return None

    def validate_server_url(self):
        """
        Validate the server URL and disable event reporting if the server is not reachable.
        """
        if not self.server_url:
            logger.warning("No server URL provided, disabling event reporting")
            self.event_reporting_enabled = False
            return

        try:
            with httpx.Client(timeout=2.0) as client:
                try:
                    response = client.get(f"{self.server_url}/health", timeout=2.0)
                    response.raise_for_status()
                    logger.info(f"Server at {self.server_url} is reachable")
                except httpx.HTTPStatusError:
                    response = client.get(self.server_url, timeout=2.0)
                    response.raise_for_status()
                    logger.info(f"Server at {self.server_url} is reachable (no health endpoint)")
        except Exception as e:
            logger.warning(f"Server at {self.server_url} is not reachable: {e}")
            logger.warning("Disabling event reporting to prevent hanging")
            self.event_reporting_enabled = False

    def execute_playbook_call(self, path: str, version: str = None, input_payload: Dict = None, merge: bool = True) -> Dict:
        """
        Execute a playbooks call.

        Args:
            path: The path of the playbooks to execute
            version: The version of the playbooks to execute (optional, uses latest if not provided)
            input_payload: The input payload to pass to the playbooks (optional)
            merge: Whether to merge the input payload with the workload (default: True)

        Returns:
            A dictionary containing the results of the playbooks execution
        """
        try:
            from noetl.server import get_catalog_service
            catalog_service = get_catalog_service()

            if not version:
                version = catalog_service.get_latest_version(path)
                logger.info(f"Version not specified for playbooks '{path}', using latest version: {version}")

            entry = catalog_service.fetch_entry(path, version)
            if not entry:
                error_msg = f"Playbook '{path}' with version '{version}' not found in catalog."
                logger.error(error_msg)
                return {
                    'status': 'error',
                    'error': error_msg
                }

            try:
                api_url = f"{self.server_url}/agent/execute"
                payload = {
                    "path": path,
                    "version": version,
                    "input_payload": input_payload or {},
                    "sync_to_postgres": True,
                    "merge": bool(merge),
                }
                with httpx.Client(timeout=30.0) as client:
                    resp = client.post(api_url, json=payload)
                    resp.raise_for_status()
                    result = resp.json()
                return {
                    'status': result.get('status', 'success'),
                    'data': result.get('result'),
                    'execution_id': result.get('execution_id')
                }
            except httpx.HTTPError as he:
                error_msg = f"HTTP error executing playbook '{path}': {he}"
                logger.error(error_msg)
                return { 'status': 'error', 'error': error_msg }
            except Exception as e:
                error_msg = f"Error delegating playbook '{path}' execution: {e}"
                logger.error(error_msg, exc_info=True)
                return { 'status': 'error', 'error': error_msg }

        except Exception as e:
            error_msg = f"Error executing playbooks '{path}': {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {
                'status': 'error',
                'error': error_msg
            }

    def delegate_task_execution(self, task_config: Dict[str, Any], task_name: str, context: Dict[str, Any], 
                               jinja_env, secret_manager, log_event_callback=None) -> Dict[str, Any]:
        """
        Delegate task execution to a worker via HTTP API.
        
        Args:
            task_config: The task configuration
            task_name: The name of the task
            context: The execution context
            jinja_env: The Jinja2 environment
            secret_manager: The secret manager
            log_event_callback: Optional callback for logging events
            
        Returns:
            A dictionary of the task result
            
        Raises:
            RuntimeError: If NOETL_WORKER_BASE_URL is not configured
        """
        logger.debug("=== BROKER.DELEGATE_TASK_EXECUTION: Function entry ===")
        logger.debug(f"BROKER.DELEGATE_TASK_EXECUTION: Parameters - task_config={task_config}, task_name={task_name}")
        
        # Check if we have a worker URL to delegate to
        worker_base_url = os.environ.get('NOETL_WORKER_BASE_URL')
        
        if not worker_base_url:
            error_msg = f"No worker pool configured. Set NOETL_WORKER_BASE_URL to delegate task '{task_name}' execution."
            logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        logger.debug(f"BROKER.DELEGATE_TASK_EXECUTION: Delegating to worker at {worker_base_url}")
        
        try:
            # Prepare the request payload for the worker
            payload = {
                "execution_id": getattr(self.agent, 'execution_id', 'unknown'),
                "parent_event_id": None,  # Could be passed in if needed
                "node_id": f"step.{task_name}",
                "node_name": task_name,
                "node_type": "task",
                "context": context,
                "mock_mode": False,
                "task": task_config
            }
            
            worker_api_url = f"{worker_base_url}/worker/action"
            logger.debug(f"BROKER.DELEGATE_TASK_EXECUTION: Calling worker API at {worker_api_url}")
            
            with httpx.Client(timeout=300.0) as client:  # 5 minute timeout for task execution
                resp = client.post(worker_api_url, json=payload)
                resp.raise_for_status()
                result = resp.json()
                
            logger.debug(f"BROKER.DELEGATE_TASK_EXECUTION: Worker returned result={result}")
            return result
            
        except httpx.HTTPError as he:
            error_msg = f"HTTP error delegating task '{task_name}' to worker: {he}"
            logger.error(error_msg)
            return {
                'id': str(uuid.uuid4()),
                'status': 'error', 
                'error': error_msg
            }
        except Exception as e:
            error_msg = f"Error delegating task '{task_name}' to worker: {e}"
            logger.error(error_msg, exc_info=True)
            return {
                'id': str(uuid.uuid4()),
                'status': 'error',
                'error': error_msg
            }

    def execute_step(self, step_name: str, step_with: Dict = None) -> Dict:
        """
        Execute a step in the workflow.

        Args:
            step_name: The name of the step
            step_with: Parameters for the step

        Returns:
            A dictionary of the step result
        """
        logger.debug("=== BROKER.EXECUTE_STEP: Function entry ===")
        logger.debug(f"BROKER.EXECUTE_STEP: Parameters - step_name={step_name}, step_with={step_with}")
        
        step_id = str(uuid.uuid4())
        logger.debug(f"BROKER.EXECUTE_STEP: Generated step_id={step_id}")
        
        start_time = datetime.datetime.now()
        logger.debug(f"BROKER.EXECUTE_STEP: Start time={start_time.isoformat()}")

        logger.debug(f"BROKER.EXECUTE_STEP: Finding step configuration for step_name={step_name}")
        step_config = self.agent.find_step(step_name)
        logger.debug(f"BROKER.EXECUTE_STEP: Step configuration: {step_config}")
        
        if not step_config:
            error_msg = f"Step not found: {step_name}"
            logger.error(f"BROKER.EXECUTE_STEP: {error_msg}")
            
            logger.debug(f"BROKER.EXECUTE_STEP: Saving step result with error")
            self.agent.save_step_result(
                step_id, step_name, None,
                'error', None, error_msg
            )
            
            logger.debug(f"BROKER.EXECUTE_STEP: Writing step_error event log")
            self.write_event_log(
                'step_error', step_id, step_name, 'step',
                'error', 0, self.agent.get_context(), None,
                {'error': error_msg}, None
            )

            result = {
                'id': step_id,
                'status': 'error',
                'error': error_msg
            }
            logger.debug(f"BROKER.EXECUTE_STEP: Returning error result={result}")
            logger.debug("=== BROKER.EXECUTE_STEP: Function exit with error (step not found) ===")
            return result

        logger.debug(f"BROKER.EXECUTE_STEP: Checking if step has pass flag")
        pass_value = step_config.get("pass", False)
        logger.debug(f"BROKER.EXECUTE_STEP: Raw pass value: {pass_value}")
        
        if isinstance(pass_value, str):
            logger.debug(f"BROKER.EXECUTE_STEP: Pass value is a string, rendering template")
            pass_value = render_template(self.agent.jinja_env, pass_value, self.agent.get_context(), strict_keys=True)
            logger.debug(f"BROKER.EXECUTE_STEP: Rendered pass value: {pass_value}")
            
        pass_flag = get_bool(pass_value)
        logger.debug(f"BROKER.EXECUTE_STEP: Final pass flag: {pass_flag}")
        
        if pass_flag:
            logger.info(f"BROKER.EXECUTE_STEP: Step '{step_name}' is marked as pass/skip. Skipping execution.")
            result = {
                'id': step_id,
                'status': 'success',
                'data': {'message': f"Step '{step_name}' was skipped (pass=True)."}
            }
            logger.debug(f"BROKER.EXECUTE_STEP: Created pass result: {result}")
            
            logger.debug(f"BROKER.EXECUTE_STEP: Saving step result for passed step")
            self.agent.save_step_result(
                step_id, step_name, None,
                result.get('status', 'success'), result.get('data'), result.get('error')
            )
            
            logger.debug(f"BROKER.EXECUTE_STEP: Updating context with step results")
            self.agent.update_context(step_name, result.get('data'))
            self.agent.update_context(step_name + '.result', result.get('data'))
            self.agent.update_context(step_name + '.status', result.get('status'))
            self.agent.update_context('result', result.get('data'))

            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()
            logger.debug(f"BROKER.EXECUTE_STEP: Step duration: {duration} seconds")
            
            logger.debug(f"BROKER.EXECUTE_STEP: Writing step_complete event log for passed step")
            self.write_event_log(
                'step_complete', step_id, step_name, 'step',
                result['status'], duration, self.agent.get_context(), result.get('data'),
                {'step_type': 'pass'}, None
            )

            if self.server_url and self.event_reporting_enabled:
                logger.debug(f"BROKER.EXECUTE_STEP: Reporting step_complete event to server for passed step")
                report_event({
                    'event_type': 'step_complete',
                    'execution_id': self.agent.execution_id,
                    'step_id': step_id,
                    'step_name': step_name,
                    'status': result['status'],
                    'duration': duration,
                    'timestamp': datetime.datetime.now().isoformat(),
                    'result': result.get('data'),
                    'error': result.get('error')
                }, self.server_url)

            logger.debug(f"BROKER.EXECUTE_STEP: Checking for next step in passed step")
            next_step = step_config.get("next")
            logger.debug(f"BROKER.EXECUTE_STEP: Next step: {next_step}")
            
            if next_step:
                final_result = {
                    **result,
                    'next_step': next_step
                }
                logger.debug(f"BROKER.EXECUTE_STEP: Returning result with next_step: {final_result}")
                logger.debug("=== BROKER.EXECUTE_STEP: Function exit (pass with next step) ===")
                return final_result
                
            logger.debug(f"BROKER.EXECUTE_STEP: Returning result without next_step: {result}")
            logger.debug("=== BROKER.EXECUTE_STEP: Function exit (pass without next step) ===")
            return result

        logger.info(f"BROKER.EXECUTE_STEP: Executing step: {step_name}")
        logger.debug(f"BROKER.EXECUTE_STEP: Step details - step_name={step_name}, step_with={step_with}")
        logger.debug(f"BROKER.EXECUTE_STEP: Context before update: {self.agent.context}")
        
        step_context = self.agent.get_context()
        logger.debug(f"BROKER.EXECUTE_STEP: Got step context")
        
        if step_with:
            logger.debug(f"BROKER.EXECUTE_STEP: Rendering step_with template: {step_with}")
            rendered_with = render_template(self.agent.jinja_env, step_with, step_context)
            logger.debug(f"BROKER.EXECUTE_STEP: Rendered step_with: {rendered_with}")
            
            if rendered_with:
                logger.debug(f"BROKER.EXECUTE_STEP: Updating context with rendered_with")
                step_context.update(rendered_with)
                for key, value in rendered_with.items():
                    logger.debug(f"BROKER.EXECUTE_STEP: Updating context key={key}, value={value}")
                    self.agent.update_context(key, value)

        logger.debug(f"BROKER.EXECUTE_STEP: Context after update: {step_context}")
        
        logger.debug(f"BROKER.EXECUTE_STEP: Writing step_start event log")
        step_event = self.write_event_log(
            'step_start', step_id, step_name, 'step',
            'in_progress', 0, step_context, None,
            {'step_type': 'standard'}, None
        )
        logger.debug(f"BROKER.EXECUTE_STEP: Step start event: {step_event}")
        
        if self.server_url and self.event_reporting_enabled:
            logger.debug(f"BROKER.EXECUTE_STEP: Reporting step_start event to server: {self.server_url}")
            filtered_context = {k: v for k, v in step_context.items() if not k.startswith('_')}
            logger.debug(f"BROKER.EXECUTE_STEP: Filtered context for reporting: {filtered_context}")
            report_event({
                'event_type': 'step_start',
                'execution_id': self.agent.execution_id,
                'step_id': step_id,
                'step_name': step_name,
                'status': 'in_progress',
                'timestamp': datetime.datetime.now().isoformat(),
                'context': filtered_context
            }, self.server_url)

        logger.debug(f"BROKER.EXECUTE_STEP: Determining step type for step_name={step_name}")
        
        if 'end_loop' in step_config:
            logger.debug(f"BROKER.EXECUTE_STEP: Step is an end_loop step")
            logger.debug(f"BROKER.EXECUTE_STEP: Calling self.end_loop_step with step_config={step_config}")
            result = self.end_loop_step(step_config, step_context, step_id)
            logger.debug(f"BROKER.EXECUTE_STEP: end_loop_step returned result={result}")
            
        elif 'loop' in step_config:
            logger.debug(f"BROKER.EXECUTE_STEP: Step is a loop step")
            logger.debug(f"BROKER.EXECUTE_STEP: Calling self.execute_loop_step with step_config={step_config}")
            result = self.execute_loop_step(step_config, step_context, step_id)
            logger.debug(f"BROKER.EXECUTE_STEP: execute_loop_step returned result={result}")
            
        elif 'transform' in step_config:
            logger.debug(f"BROKER.EXECUTE_STEP: Step is a transform step")
            logger.debug(f"BROKER.EXECUTE_STEP: Calling self.execute_transform_step with step_config={step_config}")
            result = self.execute_transform_step(step_config, step_context, step_id)
            logger.debug(f"BROKER.EXECUTE_STEP: execute_transform_step returned result={result}")
            
        else:
            logger.debug(f"BROKER.EXECUTE_STEP: Step is a standard step")
            
            if 'call' in step_config:
                logger.debug(f"BROKER.EXECUTE_STEP: Step has a 'call' attribute")
                call_config = step_config['call'].copy()
                logger.debug(f"BROKER.EXECUTE_STEP: Using 'call' attribute with type: {call_config.get('type', 'workbook')}")
                
                merged_fields = []
                for key, value in step_config.items():
                    if key != 'call' and key not in call_config:
                        logger.debug(f"BROKER.EXECUTE_STEP: Merging field {key} from step into call")
                        call_config[key] = value
                        merged_fields.append(key)

                if merged_fields:
                    logger.debug(f"BROKER.EXECUTE_STEP: Merged fields from step into call: {', '.join(merged_fields)}")

                task_name = call_config.get('name') or call_config.get('task')
                logger.debug(f"BROKER.EXECUTE_STEP: Task name from call config: {task_name}")
                
                call_type = call_config.get('type', 'workbook')
                logger.debug(f"BROKER.EXECUTE_STEP: Call type: {call_type}")
                
                logger.debug(f"BROKER.EXECUTE_STEP: Rendering task_with template from call_config.with: {call_config.get('with', {})}")
                task_with = render_template(self.agent.jinja_env, call_config.get('with', {}), step_context, strict_keys=False)
                logger.debug(f"BROKER.EXECUTE_STEP: Rendered task_with: {task_with}")
                
                task_context = {**step_context, **task_with}
                logger.debug(f"BROKER.EXECUTE_STEP: Created task_context by merging step_context and task_with")
                
            else:
                logger.debug(f"BROKER.EXECUTE_STEP: Step does not have a 'call' attribute")
                call_type = step_config.get('type', 'workbook')
                logger.debug(f"BROKER.EXECUTE_STEP: Using direct 'type' attribute: {call_type}")

                task_name = step_config.get('name') or step_config.get('task')
                logger.debug(f"BROKER.EXECUTE_STEP: Extracted task_name: '{task_name}' from step_config: {step_config}")

                if not task_name and 'next' in step_config and call_type == 'workbook':
                    logger.debug(f"BROKER.EXECUTE_STEP: Step '{step_name}' appears to be a routing step with no task - treating as no-op")
                    result = {
                        'id': step_id,
                        'status': 'success',
                        'data': {'message': f'Routing step {step_name} completed'}
                    }
                    logger.debug(f"BROKER.EXECUTE_STEP: Created routing step result: {result}")
                    
                    logger.debug(f"BROKER.EXECUTE_STEP: Saving routing step result")
                    self.agent.save_step_result(
                        step_id, step_name, None,
                        result.get('status', 'success'), result.get('data'), result.get('error')
                    )

                    logger.debug(f"BROKER.EXECUTE_STEP: Updating context with routing step results")
                    self.agent.update_context(step_name, result.get('data'))
                    self.agent.update_context(step_name + '.result', result.get('data'))
                    self.agent.update_context(step_name + '.status', result.get('status'))
                    self.agent.update_context('result', result.get('data'))

                    end_time = datetime.datetime.now()
                    duration = (end_time - start_time).total_seconds()
                    logger.debug(f"BROKER.EXECUTE_STEP: Routing step duration: {duration} seconds")
                    
                    logger.debug(f"BROKER.EXECUTE_STEP: Writing step_complete event log for routing step")
                    self.write_event_log(
                        'step_complete', step_id, step_name, 'step',
                        result['status'], duration, step_context, result.get('data'),
                        {'step_type': 'routing'}, step_event
                    )

                    if self.server_url and self.event_reporting_enabled:
                        logger.debug(f"BROKER.EXECUTE_STEP: Reporting step_complete event to server for routing step")
                        report_event({
                            'event_type': 'step_complete',
                            'execution_id': self.agent.execution_id,
                            'step_id': step_id,
                            'step_name': step_name,
                            'status': result['status'],
                            'duration': duration,
                            'timestamp': datetime.datetime.now().isoformat(),
                            'result': result.get('data'),
                            'error': result.get('error')
                        }, self.server_url)

                    logger.debug(f"BROKER.EXECUTE_STEP: Returning routing step result: {result}")
                    logger.debug("=== BROKER.EXECUTE_STEP: Function exit (routing step) ===")
                    return result

                logger.debug(f"BROKER.EXECUTE_STEP: Rendering task_with template from step_config.with: {step_config.get('with', {})}")
                task_with = render_template(self.agent.jinja_env, step_config.get('with', {}), step_context, strict_keys=False)
                logger.debug(f"BROKER.EXECUTE_STEP: Rendered task_with: {task_with}")
                
                task_context = {**step_context, **task_with}
                logger.debug(f"BROKER.EXECUTE_STEP: Created task_context by merging step_context and task_with")
                
                call_config = step_config
                logger.debug(f"BROKER.EXECUTE_STEP: Using step_config as call_config")

            if call_type == 'workbook':
                logger.debug(f"BROKER.EXECUTE_STEP: Executing workbook task: {task_name}")
                logger.info(f"BROKER.EXECUTE_STEP: EXECUTING workbook task: {task_name}")
                logger.debug(f"BROKER.EXECUTE_STEP: Finding task configuration for task_name={task_name}")
                task_config = self.agent.find_task(task_name)
                logger.debug(f"BROKER.EXECUTE_STEP: Found task_config for '{task_name}': {task_config}")

                if task_config:
                    logger.debug(f"BROKER.EXECUTE_STEP: Task config found, preparing for execution")
                    execution_task_config = task_config.copy()
                    logger.debug(f"BROKER.EXECUTE_STEP: Copied task_config to execution_task_config")
                    
                    merged_with = task_config.get('with', {}).copy()
                    logger.debug(f"BROKER.EXECUTE_STEP: Got task 'with' parameters: {merged_with}")
                    
                    step_with_params = step_config.get('with', {})
                    logger.debug(f"BROKER.EXECUTE_STEP: Got step 'with' parameters: {step_with_params}")
                    
                    merged_with.update(step_with_params)
                    logger.debug(f"BROKER.EXECUTE_STEP: Merged 'with' parameters: {merged_with}")
                    
                    execution_task_config['with'] = merged_with
                    logger.debug(f"BROKER.EXECUTE_STEP: Task config for execution: {execution_task_config}")
                    logger.debug(f"BROKER.EXECUTE_STEP: Merged with parameters: step_with={step_with_params}, task_with={task_config.get('with', {})}, merged={merged_with}")
                else:
                    logger.error(f"BROKER.EXECUTE_STEP: No task config found for task_name: '{task_name}'")
                    execution_task_config = {}
                    logger.debug(f"BROKER.EXECUTE_STEP: Using empty execution_task_config")

                logger.debug(f"BROKER.EXECUTE_STEP: Delegating task execution with execution_task_config={execution_task_config}, task_name={task_name}")
                merged_context = {**step_context}
                if 'with' in execution_task_config:
                    task_with = render_template(self.agent.jinja_env, execution_task_config.get('with', {}), step_context, strict_keys=False)
                    merged_context.update(task_with)
                    logger.debug(f"BROKER.EXECUTE_STEP: Created merged_context by combining step_context and rendered task_with: {task_with}")
                
                try:
                    result = self.delegate_task_execution(
                        execution_task_config,
                        task_name,
                        merged_context,
                        self.agent.jinja_env,
                        self.agent.secret_manager,
                        self.write_event_log if self.has_log_event() else None
                    )
                    logger.debug(f"BROKER.EXECUTE_STEP: execute_task returned result={result}")
                    logger.info(f"BROKER.EXECUTE_STEP: EXECUTED workbook task: {task_name} with status: {result.get('status', 'unknown')}")
                except RuntimeError as re:
                    error_msg = str(re)
                    logger.error(f"BROKER.EXECUTE_STEP: {error_msg}")
                    result = {
                        'id': str(uuid.uuid4()),
                        'status': 'error',
                        'error': error_msg
                    }
                
            elif call_type == 'Playbook':
                logger.debug(f"BROKER.EXECUTE_STEP: Executing playbooks task")
                logger.info(f"BROKER.EXECUTE_STEP: EXECUTING playbooks task")
                path = call_config.get('path')
                logger.debug(f"BROKER.EXECUTE_STEP: Playbooks path: {path}")
                
                version = call_config.get('version')
                logger.debug(f"BROKER.EXECUTE_STEP: Playbooks version: {version}")

                if not path:
                    error_msg = "Missing 'path' parameter in playbooks call."
                    logger.error(f"BROKER.EXECUTE_STEP: {error_msg}")
                    result = {
                        'id': str(uuid.uuid4()),
                        'status': 'error',
                        'error': error_msg
                    }
                    logger.debug(f"BROKER.EXECUTE_STEP: Created error result for missing path: {result}")
                else:
                    logger.debug(f"BROKER.EXECUTE_STEP: Executing playbook call with path={path}, version={version}, input_payload={task_with}")
                    playbook_result = self.execute_playbook_call(
                        path=path,
                        version=version,
                        input_payload=task_with,
                        merge=True
                    )
                    logger.debug(f"BROKER.EXECUTE_STEP: execute_playbook_call returned result={playbook_result}")
                    logger.info(f"BROKER.EXECUTE_STEP: EXECUTED playbooks task with path: {path} and status: {playbook_result.get('status', 'unknown')}")

                    result_id = str(uuid.uuid4())
                    logger.debug(f"BROKER.EXECUTE_STEP: Generated result_id={result_id}")
                    result = {
                        'id': result_id,
                        'status': playbook_result.get('status', 'error'),
                        'data': playbook_result.get('data'),
                        'error': playbook_result.get('error')
                    }
                    logger.debug(f"BROKER.EXECUTE_STEP: Created result from playbook_result: {result}")
                    
            elif call_type in ['http', 'python', 'duckdb', 'postgres', 'secrets']:
                logger.debug(f"BROKER.EXECUTE_STEP: Executing {call_type} task")
                logger.info(f"BROKER.EXECUTE_STEP: EXECUTING {call_type} task")
                
                logger.debug(f"BROKER.EXECUTE_STEP: Creating task_config for {call_type} task")
                task_config = {
                    'type': call_type,
                    'with': call_config.get('with', {})
                }
                logger.debug(f"BROKER.EXECUTE_STEP: Initial task_config: {task_config}")
                
                fields = ['name', 'pass', 'params','param', 'commands','command','run', 'return', 'headers', 'url', 'endpoint', 'method', 'body', 'code', 'provider', 'secret_name', 'project_id', 'region', 'version']
                logger.debug(f"BROKER.EXECUTE_STEP: Fields to copy from call_config: {fields}")
                
                task_config.update({
                    field: call_config.get(field)
                    for field in fields
                    if field in call_config
                })
                logger.debug(f"BROKER.EXECUTE_STEP: Final task_config: {task_config}")

                task_name_to_use = task_name or f"step_{call_type}_task"
                logger.debug(f"BROKER.EXECUTE_STEP: Using task_name: {task_name_to_use}")
                
                logger.debug(f"BROKER.EXECUTE_STEP: Delegating task execution with task_config={task_config}, task_name={task_name_to_use}")
                try:
                    result = self.delegate_task_execution(
                        task_config,
                        task_name_to_use,
                        task_context,
                        self.agent.jinja_env,
                        self.agent.secret_manager,
                        self.write_event_log if self.has_log_event() else None
                    )
                    logger.debug(f"BROKER.EXECUTE_STEP: execute_task returned result={result}")
                    logger.info(f"BROKER.EXECUTE_STEP: EXECUTED {call_type} task: {task_name_to_use} with status: {result.get('status', 'unknown')}")
                except RuntimeError as re:
                    error_msg = str(re)
                    logger.error(f"BROKER.EXECUTE_STEP: {error_msg}")
                    result = {
                        'id': str(uuid.uuid4()),
                        'status': 'error',
                        'error': error_msg
                    }
                
            else:
                error_msg = f"Unsupported call type: {call_type}"
                logger.error(f"BROKER.EXECUTE_STEP: {error_msg}")
                
                result_id = str(uuid.uuid4())
                logger.debug(f"BROKER.EXECUTE_STEP: Generated result_id={result_id}")
                
                result = {
                    'id': result_id,
                    'status': 'error',
                    'error': error_msg
                }
                logger.debug(f"BROKER.EXECUTE_STEP: Created error result for unsupported call type: {result}")

            logger.info(f"BROKER.EXECUTE_STEP: Step '{step_name}' completed with result: {result}")
            
            if result.get('status') == 'success':
                if result.get('data') is None or (isinstance(result.get('data'), dict) and not result.get('data')):
                    logger.warning(f"BROKER.EXECUTE_STEP: Step '{step_name}' returned empty data: {result.get('data')}")
                else:
                    logger.info(f"BROKER.EXECUTE_STEP: Step '{step_name}' returned data: {result.get('data')}")
            else:
                error_message = result.get('error')
                logger.warning(f"BROKER.EXECUTE_STEP: Step '{step_name}' failed with error: {error_message}")
                
                try:
                    log_error(
                        error=Exception(error_message),
                        error_type="step_execution",
                        template_string=str(step_config),
                        context_data=step_context,
                        input_data=task_with,
                        execution_id=self.agent.execution_id,
                        step_id=step_id,
                        step_name=step_name
                    )
                except Exception as e:
                    logger.error(f"BROKER.EXECUTE_STEP: Failed to log error to database: {e}")
            
            logger.debug(f"BROKER.EXECUTE_STEP: Saving step result to database")
            self.agent.save_step_result(
                step_id, step_name, None,
                result.get('status', 'success'), result.get('data'), result.get('error')
            )
            logger.debug(f"BROKER.EXECUTE_STEP: Saved step result to database - status: {result.get('status', 'success')}, data: {result.get('data')}, error: {result.get('error')}")
            
            logger.debug(f"BROKER.EXECUTE_STEP: Updating context with step results")
            self.agent.update_context(step_name, result.get('data'))
            logger.debug(f"BROKER.EXECUTE_STEP: Updated context key={step_name}, value={result.get('data')}")
            
            self.agent.update_context(step_name + '.result', result.get('data'))
            logger.debug(f"BROKER.EXECUTE_STEP: Updated context key={step_name}.result, value={result.get('data')}")
            
            self.agent.update_context(step_name + '.status', result.get('status'))
            logger.debug(f"BROKER.EXECUTE_STEP: Updated context key={step_name}.status, value={result.get('status')}")
            
            self.agent.update_context(step_name + '.data', result.get('data'))
            logger.debug(f"BROKER.EXECUTE_STEP: Updated context key={step_name}.data, value={result.get('data')}")
            
            self.agent.update_context('result', result.get('data'))
            logger.debug(f"BROKER.EXECUTE_STEP: Updated context key=result, value={result.get('data')}")

            if call_type == 'secrets' and result.get('status') == 'success':
                logger.debug(f"BROKER.EXECUTE_STEP: Processing successful secrets step")
                secret_data = result.get('data', {})
                logger.debug(f"BROKER.EXECUTE_STEP: Secret data: {secret_data}")
                
                if isinstance(secret_data, dict) and 'secret_value' in secret_data:
                    logger.debug(f"BROKER.EXECUTE_STEP: Secret data contains secret_value, creating step_result_obj")
                    step_result_obj = {
                        'secret_value': secret_data['secret_value'],
                        **secret_data
                    }
                    logger.debug(f"BROKER.EXECUTE_STEP: Created step_result_obj: {step_result_obj}")
                    
                    logger.debug(f"BROKER.EXECUTE_STEP: Updating context with step_result_obj")
                    self.agent.update_context(step_name, step_result_obj)

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        logger.debug(f"BROKER.EXECUTE_STEP: Step duration: {duration} seconds")
        
        logger.debug(f"BROKER.EXECUTE_STEP: Writing step_complete event log")
        self.write_event_log(
            'step_complete', step_id, step_name, 'step',
            result['status'], duration, step_context, result.get('data'),
            {'step_type': 'standard'}, step_event
        )

        if self.server_url and self.event_reporting_enabled:
            logger.debug(f"BROKER.EXECUTE_STEP: Reporting step_complete event to server")
            report_event({
                'event_type': 'step_complete',
                'execution_id': self.agent.execution_id,
                'step_id': step_id,
                'step_name': step_name,
                'status': result['status'],
                'duration': duration,
                'timestamp': datetime.datetime.now().isoformat(),
                'result': result.get('data'),
                'error': result.get('error')
            }, self.server_url)

        logger.debug(f"BROKER.EXECUTE_STEP: Returning result: {result}")
        logger.info(f"BROKER.EXECUTE_STEP: Step '{step_name}' completed with status: {result.get('status', 'unknown')}")
        logger.debug("=== BROKER.EXECUTE_STEP: Function exit ===")
        return result

    def execute_transform_step(self, step_config: Dict, context: Dict, step_id: str) -> Dict:
        """
        Execute a transform step that applies transformations to data.

        Args:
            step_config: The step configuration
            context: The context to render templates
            step_id: The ID of the step

        Returns:
            A dictionary of the step result
        """
        start_time = datetime.datetime.now()
        
        transform_config = step_config.get('transform', {})
        if not transform_config:
            error_msg = "Missing transform configuration"
            self.agent.save_step_result(
                step_id, step_config.get('step', 'transform'), None,
                'error', None, error_msg
            )
            return {
                'id': step_id,
                'status': 'error',
                'error': error_msg
            }

        logger.info(f"Processing transform step: {step_config.get('step')}")
        
        transform_event = self.write_event_log(
            'transform_start', step_id, step_config.get('step', 'transform'), 'step.transform',
            'in_progress', 0, context, None,
            {'transform_config': transform_config}, None
        )

        try:
            transformed_data = {}
            
            if 'template' in transform_config:
                template = transform_config['template']
                transformed_data = render_template(self.agent.jinja_env, template, context)
            elif 'mapping' in transform_config:
                mapping = transform_config['mapping']
                for target_field, source_template in mapping.items():
                    transformed_data[target_field] = render_template(self.agent.jinja_env, source_template, context)
            elif 'script' in transform_config:
                script = transform_config['script']
                exec_globals = {'__builtins__': __builtins__, 'context': context}
                exec_locals = {}
                exec(script, exec_globals, exec_locals)
                if 'transform' in exec_locals:
                    transformed_data = exec_locals['transform'](context)
                else:
                    transformed_data = exec_locals.get('result', {})
            else:
                error_msg = "Transform configuration must include 'template', 'mapping', or 'script'"
                raise ValueError(error_msg)

            step_name = step_config.get('step')
            self.agent.update_context(step_name, transformed_data)
            
            self.agent.save_step_result(
                step_id, step_name, None, 'success', transformed_data, None
            )

            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            self.write_event_log(
                'transform_complete', step_id, step_name, 'step.transform',
                'success', duration, context, transformed_data,
                {'transform_config': transform_config}, transform_event
            )

            if self.server_url and self.event_reporting_enabled:
                report_event({
                    'event_type': 'transform_complete',
                    'execution_id': self.agent.execution_id,
                    'step_id': step_id,
                    'step_name': step_name,
                    'status': 'success',
                    'duration': duration,
                    'timestamp': datetime.datetime.now().isoformat(),
                    'result': transformed_data
                }, self.server_url)

            return {
                'id': step_id,
                'status': 'success',
                'data': transformed_data
            }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Transform step error: {error_msg}", exc_info=True)
            
            self.agent.save_step_result(
                step_id, step_config.get('step', 'transform'), None,
                'error', None, error_msg
            )

            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()
            
            self.write_event_log(
                'transform_error', step_id, step_config.get('step', 'transform'), 'step.transform',
                'error', duration, context, None,
                {'error': error_msg, 'transform_config': transform_config}, transform_event
            )

            return {
                'id': step_id,
                'status': 'error',
                'error': error_msg
            }

    def end_loop_step(self, step_config: Dict, context: Dict, step_id: str) -> Dict:
        """
        Execute an end_loop step.

        Args:
            step_config: The step configuration
            context: The context for rendering templates
            step_id: The ID of the step

        Returns:
            A dictionary of step result's
        """
        start_time = datetime.datetime.now()
        loop_name = step_config.get('end_loop')
        if not loop_name:
            error_msg = "Missing loop name in end_loop step."
            self.agent.save_step_result(
                step_id, step_config.get('step', 'end_loop'), None,
                'error', None, error_msg
            )
            self.write_event_log(
                'step_error', step_id, step_config.get('step', 'end_loop'), 'step.end_loop',
                'error', 0, context, None,
                {'error': error_msg}, None
            )

            return {
                'id': step_id,
                'status': 'error',
                'error': error_msg
            }

        logger.info(f"Processing end_loop for: {loop_name}")
        end_loop_event = self.write_event_log(
            'end_loop_start', step_id, step_config.get('step', 'end_loop'), 'step.end_loop',
            'in_progress', 0, context, None,
            {'loop_name': loop_name}, None
        )
        if self.server_url and self.event_reporting_enabled:
            report_event({
                'event_type': 'end_loop_start',
                'execution_id': self.agent.execution_id,
                'step_id': step_id,
                'step_name': step_config.get('step', 'end_loop'),
                'loop_name': loop_name,
                'status': 'in_progress',
                'timestamp': datetime.datetime.now().isoformat()
            }, self.server_url)

        loop_info = self.agent.find_loop(loop_name, include_completed=True)
        if not loop_info:
            error_msg = f"Loop context not found: {loop_name}"
            self.agent.save_step_result(
                step_id, step_config.get('step', 'end_loop'), None,
                'error', None, error_msg
            )
            self.write_event_log(
                'end_loop_error', step_id, step_config.get('step', 'end_loop'), 'step.end_loop',
                'error', 0, context, None,
                {'error': error_msg, 'loop_name': loop_name}, end_loop_event
            )

            return {
                'id': step_id,
                'status': 'error',
                'error': error_msg
            }

        loop_results = loop_info.get('results', [])
        loop_results_var = f"{loop_name}_results"
        self.agent.update_context(loop_results_var, loop_results)
        result_config = step_config.get('result', {})
        aggregated_results = {}

        for key, template in result_config.items():
            aggregated_value = render_template(self.agent.jinja_env, template, context)
            aggregated_results[key] = aggregated_value
            self.agent.update_context(key, aggregated_value)
        self.agent.complete_loop(loop_info.get('id'))
        self.agent.save_step_result(
            step_id, step_config.get('step', 'end_loop'), loop_info.get('id'),
            'success', aggregated_results, None
        )
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        self.write_event_log(
            'end_loop_complete', step_id, step_config.get('step', 'end_loop'), 'step.end_loop',
            'success', duration, context, aggregated_results,
            {'loop_name': loop_name}, end_loop_event
        )

        if self.server_url and self.event_reporting_enabled:
            report_event({
                'event_type': 'end_loop_complete',
                'execution_id': self.agent.execution_id,
                'step_id': step_id,
                'step_name': step_config.get('step', 'end_loop'),
                'loop_name': loop_name,
                'status': 'success',
                'duration': duration,
                'timestamp': datetime.datetime.now().isoformat(),
                'result': aggregated_results
            }, self.server_url)

        return {
            'id': step_id,
            'status': 'success',
            'data': aggregated_results
        }

    def execute_loop_step(self, step_config: Dict, context: Dict, step_id: str) -> Dict:
        """
        Execute a loop step.

        Args:
            step_config: The step configuration
            context: The context to render templates
            step_id: The ID of the step

        Returns:
            A dictionary of the step result
        """
        start_time = datetime.datetime.now()
        loop_config = step_config.get('loop')
        if not loop_config:
            error_msg = "Missing loop configuration"
            self.agent.save_step_result(
                step_id, step_config.get('step', 'loop'), None,
                'error', None, error_msg
            )
            self.write_event_log(
                'step_error', step_id, step_config.get('step', 'loop'), 'step.loop',
                'error', 0, context, None,
                {'error': error_msg}, None
            )
            return {
                'id': step_id,
                'status': 'error',
                'error': error_msg
            }

        iterator = loop_config.get('iterator', 'item')
        items = render_template(self.agent.jinja_env, loop_config.get('in', []), context)
        filter_expr = loop_config.get('filter')
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = [items]
        if not isinstance(items, list):
            error_msg = f"Loop items must be a list, got: {type(items)}"
            self.agent.save_step_result(
                step_id, step_config.get('step', 'loop'), None,
                'error', None, error_msg
            )
            self.write_event_log(
                'loop_error', step_id, step_config.get('step', 'loop'), 'step.loop',
                'error', 0, context, None,
                {'error': error_msg}, None
            )
            return {
                'id': step_id,
                'status': 'error',
                'error': error_msg
            }

        def validate_dict(item):
            if isinstance(item, dict):
                return item
            if isinstance(item, str):
                try:
                    parsed = json.loads(item)
                    if isinstance(parsed, dict):
                        return parsed
                    else:
                        return {"value": parsed}
                except Exception:
                    return {"value": item}
            return {"value": item}

        logger.info(f"Starting loop step with {len(items)} items")
        logger.debug(f"Loop step iterator={iterator}, items={items}")
        loop_name = step_config.get('step', 'unnamed_loop')
        loop_id = str(uuid.uuid4())
        loop_start_event = self.write_event_log(
            'loop_start', loop_id, loop_name, 'step.loop',
            'in_progress', 0, context, None,
            {'item_count': len(items), 'iterator': iterator}, None,
            loop_id=loop_id, loop_name=loop_name, iterator=iterator,
            items=items, current_index=-1, current_item=None, results=[],
            worker_id=os.environ.get('WORKER_ID', 'local'), distributed_state='created'
        )

        if self.server_url and self.event_reporting_enabled:
            report_event({
                'event_type': 'loop_start',
                'execution_id': self.agent.execution_id,
                'step_id': step_id,
                'loop_id': loop_id,
                'loop_name': loop_name,
                'iterator': iterator,
                'item_count': len(items),
                'status': 'in_progress',
                'timestamp': datetime.datetime.now().isoformat()
            }, self.server_url)

        all_results = []

        for idx, item in enumerate(items):
            iter_context = dict(context)
            iter_context[iterator] = validate_dict(item)

            iter_event = self.write_event_log(
                'loop_iteration', f"{loop_id}_{idx}", f"{loop_name}[{idx}]", 'iteration',
                'in_progress', 0, context, None,
                {'index': idx, 'item': item}, loop_start_event
            )

            if self.server_url and self.event_reporting_enabled:
                report_event({
                    'event_type': 'loop_iteration',
                    'execution_id': self.agent.execution_id,
                    'loop_id': loop_id,
                    'loop_name': loop_name,
                    'iteration_index': idx,
                    'status': 'in_progress',
                    'timestamp': datetime.datetime.now().isoformat(),
                    'item': item
                }, self.server_url)

            skip_item = False
            if filter_expr:
                filter_result = render_template(self.agent.jinja_env, filter_expr, iter_context)
                if isinstance(filter_result, str) and filter_result.strip() == "":
                    skip_item = False
                elif not filter_result:
                    skip_item = True

            if skip_item:
                logger.info(f"Filtering out item {idx}")
                self.write_event_log(
                    'loop_iteration_filtered', f"{loop_id}_{idx}", f"{loop_name}[{idx}]", 'iteration',
                    'filtered', 0, iter_context, None,
                    {'index': idx, 'filter': filter_expr}, iter_event
                )

                if self.server_url and self.event_reporting_enabled:
                    report_event({
                        'event_type': 'loop_iteration_filtered',
                        'execution_id': self.agent.execution_id,
                        'loop_id': loop_id,
                        'loop_name': loop_name,
                        'iteration_index': idx,
                        'status': 'filtered',
                        'timestamp': datetime.datetime.now().isoformat(),
                        'item': item,
                        'filter': filter_expr
                    }, self.server_url)

                continue

            next_steps = step_config.get('next', [])
            if not isinstance(next_steps, list):
                next_steps = [next_steps]

            iter_results = {}
            for next_step in next_steps:
                if isinstance(next_step, dict):
                    next_step_name = next_step.get('step')
                    next_step_with = next_step.get('with', {})
                else:
                    next_step_name = next_step
                    next_step_with = {}

                rules = {iterator: iter_context.get(iterator)}
                logger.debug(f"Loop next step: {next_step_name}, next_step_with={next_step_with}, rules={rules}")

                step_with = render_template(self.agent.jinja_env, next_step_with, iter_context, rules)
                logger.debug(f"Loop step rendered with: {step_with}")

                if not next_step_name:
                    continue
                step_result = self.execute_step(next_step_name, step_with)
                iter_results[next_step_name] = step_result.get('data') if step_result.get(
                    'status') == 'success' else None

            all_results.append(iter_results)
            self.write_event_log(
                'loop_iteration_complete', f"{loop_id}_{idx}", f"{loop_name}[{idx}]", 'iteration',
                'success', 0, iter_context, iter_results,
                {'index': idx, 'item': item}, iter_event,
                loop_id=loop_id, loop_name=loop_name, iterator=iterator,
                items=items, current_index=idx, current_item=item, results=all_results,
                worker_id=os.environ.get('WORKER_ID', 'local'), distributed_state='iteration_complete'
            )

            if self.server_url and self.event_reporting_enabled:
                report_event({
                    'event_type': 'loop_iteration_complete',
                    'execution_id': self.agent.execution_id,
                    'loop_id': loop_id,
                    'loop_name': loop_name,
                    'iteration_index': idx,
                    'status': 'success',
                    'timestamp': datetime.datetime.now().isoformat(),
                    'item': item,
                    'result': iter_results
                }, self.server_url)

        self.agent.update_context(f"{loop_name}_results", all_results)
        self.agent.save_step_result(
            step_id, step_config.get('step', 'loop'), None,
            'success', all_results, None
        )
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        self.write_event_log(
            'loop_complete', loop_id, loop_name, 'step.loop',
            'success', duration, context, all_results,
            {'item_count': len(items), 'processed_count': len(all_results)}, loop_start_event,
            loop_id=loop_id, loop_name=loop_name, iterator=iterator,
            items=items, current_index=len(items), current_item=None, results=all_results,
            worker_id=os.environ.get('WORKER_ID', 'local'), distributed_state='completed'
        )

        if self.server_url and self.event_reporting_enabled:
            report_event({
                'event_type': 'loop_complete',
                'execution_id': self.agent.execution_id,
                'loop_id': loop_id,
                'loop_name': loop_name,
                'status': 'success',
                'duration': duration,
                'timestamp': datetime.datetime.now().isoformat(),
                'item_count': len(items),
                'processed_count': len(all_results),
                'results': all_results
            }, self.server_url)

        loop_name = step_config.get('step')
        for step in self.agent.playbook.get('workflow', []):
            if 'end_loop' in step and step.get('end_loop') == loop_name:
                logger.info(f"Found end_loop step for {loop_name}: {step.get('step')}")
                self.agent.next_step_with = step.get('with', {})
                return {
                    'id': step_id,
                    'status': 'success',
                    'data': all_results,
                    'next_step': step.get('step')
                }

        return {
            'id': step_id,
            'status': 'success',
            'data': all_results
        }

    def get_next_steps(self, step_config: Dict, context: Dict) -> List[Tuple[str, Dict, str]]:
        """
        Get the next steps from the step configuration and context.

        Args:
            step_config: The step configuration
            context: The context to render template

        Returns:
            A list of tuples for the next step name, parameters, and condition
        """
        next_steps = step_config.get('next', [])
        if not next_steps:
            return []

        if not isinstance(next_steps, list):
            next_steps = [next_steps]

        result_steps = []
        for next_step in next_steps:
            if isinstance(next_step, dict) and 'when' in next_step:
                condition_text = next_step.get('when')
                condition = render_template(self.agent.jinja_env, condition_text, context)
                if condition:
                    then_steps = next_step.get('then', [])
                    if not isinstance(then_steps, list):
                        then_steps = [then_steps]

                    for then_step in then_steps:
                        if isinstance(then_step, dict):
                            step_name = then_step.get('step')
                            step_with = then_step.get('with', {})
                        else:
                            step_name = then_step
                            step_with = {}

                        result_steps.append((step_name, step_with, f"when: {condition_text} (true)"))
                else:
                    else_steps = next_step.get('else', [])
                    if not isinstance(else_steps, list):
                        else_steps = [else_steps]

                    for else_step in else_steps:
                        if isinstance(else_step, dict):
                            step_name = else_step.get('step')
                            step_with = else_step.get('with', {})
                        else:
                            step_name = else_step
                            step_with = {}

                        result_steps.append((step_name, step_with, f"when: {condition_text} (false)"))
            elif isinstance(next_step, dict):
                step_name = next_step.get('step')
                step_with = next_step.get('with', {})
                result_steps.append((step_name, step_with, ""))
            else:
                result_steps.append((next_step, {}, ""))

        return result_steps

    def run(self, mlflow: bool = False) -> Dict[str, Any]:
        """
        Args:
            mlflow: Whether to use ML flow for workflow control

        Returns:
            A dictionary of workflow results
        """
        logger.debug("=== BROKER.RUN: Function entry ===")
        logger.debug(f"BROKER.RUN: Parameters - mlflow={mlflow}")

        playbook_name = self.agent.playbook.get('name', 'Unnamed')
        logger.info(f"BROKER.RUN: Starting playbook: {playbook_name}")
        logger.debug(f"BROKER.RUN: Execution ID: {self.agent.execution_id}")
        logger.debug(f"BROKER.RUN: Playbook path: {self.agent.playbook_path}")
        
        logger.info("=== ENVIRONMENT VARIABLES AT PLAYBOOK EXECUTION ===")
        for key, value in sorted(os.environ.items()):
            logger.info(f"ENV: {key}={value}")
        logger.info("=== END ENVIRONMENT VARIABLES ===")
        
        execution_start_time = datetime.datetime.now().isoformat()
        logger.debug(f"BROKER.RUN: Execution start time: {execution_start_time}")
        self.agent.update_context('execution_start', execution_start_time)
        
        logger.debug("BROKER.RUN: Writing execution_start event log")
        execution_start_event = self.write_event_log(
            'execution_start', self.agent.execution_id, playbook_name,
            'playbook',
            'in_progress',
            0, self.agent.context,
            None,
            {'playbook_path': self.agent.playbook_path},
            None
        )
        logger.debug(f"BROKER.RUN: Execution start event: {execution_start_event}")
        
        steps_override = self.agent.get_context().get('workload', {}).get('steps_override')
        logger.debug(f"BROKER.RUN: Steps override: {steps_override}")
        
        if steps_override and isinstance(steps_override, list):
            logger.info(f"BROKER.RUN: Using steps_override: {steps_override}")
            for step_name in steps_override:
                logger.debug(f"BROKER.RUN: Executing override step: {step_name}")
                step_result = self.execute_step(step_name, {})
                logger.debug(f"BROKER.RUN: Override step {step_name} result: {step_result}")
                if step_result['status'] != 'success':
                    logger.error(f"BROKER.RUN: Override step {step_name} failed with status: {step_result['status']}")
                    break
            logger.debug("BROKER.RUN: Returning step results after steps_override execution")
            results = self.agent.get_step_results()
            logger.debug(f"BROKER.RUN: Step results: {results}")
            logger.debug("=== BROKER.RUN: Function exit (steps_override path) ===")
            return results
            
        if self.server_url and self.event_reporting_enabled:
            logger.debug(f"BROKER.RUN: Reporting execution_start event to server: {self.server_url}")
            report_event({
                'event_type': 'execution_start',
                'execution_id': self.agent.execution_id,
                'playbook_name': playbook_name,
                'status': 'in_progress',
                'timestamp': datetime.datetime.now().isoformat(),
                'playbook_path': self.agent.playbook_path
            }, self.server_url)

        current_step = 'start'
        logger.debug(f"BROKER.RUN: Starting execution with step: {current_step}")
        
        while current_step and current_step != 'end':
            logger.debug(f"BROKER.RUN: Current step: {current_step}")
            step_config = self.agent.find_step(current_step)
            
            if not step_config:
                logger.error(f"BROKER.RUN: Step not found: {current_step}")
                logger.debug("BROKER.RUN: Writing execution_error event log")
                self.write_event_log(
                    'execution_error',
                    f"{self.agent.execution_id}_error", playbook_name,
                    'playbook',
                    'error', 0, self.agent.context, None,
                    {'error': f"Step not found: {current_step}"}, execution_start_event
                )

                if self.server_url and self.event_reporting_enabled:
                    logger.debug(f"BROKER.RUN: Reporting execution_error event to server: {self.server_url}")
                    report_event({
                        'event_type': 'execution_error',
                        'execution_id': self.agent.execution_id,
                        'playbook_name': playbook_name,
                        'status': 'error',
                        'timestamp': datetime.datetime.now().isoformat(),
                        'error': f"Step not found: {current_step}"
                    }, self.server_url)

                break

            logger.debug(f"BROKER.RUN: Executing step: {current_step} with params: {self.agent.next_step_with}")
            step_result = self.execute_step(current_step, self.agent.next_step_with)
            logger.debug(f"BROKER.RUN: Step {current_step} result: {step_result}")
            self.agent.next_step_with = None

            if step_result['status'] != 'success':
                logger.error(f"BROKER.RUN: Step failed: {current_step}, error: {step_result.get('error')}")
                logger.debug("BROKER.RUN: Writing execution_error event log")
                self.write_event_log(
                    'execution_error',
                    f"{self.agent.execution_id}_error", playbook_name,
                    'playbook',
                    'error', 0, self.agent.context, None,
                    {'error': f"Step failed: {current_step}", 'step_error': step_result.get('error')},
                    execution_start_event
                )

                if self.server_url and self.event_reporting_enabled:
                    logger.debug(f"BROKER.RUN: Reporting execution_error event to server: {self.server_url}")
                    report_event({
                        'event_type': 'execution_error',
                        'execution_id': self.agent.execution_id,
                        'playbook_name': playbook_name,
                        'status': 'error',
                        'timestamp': datetime.datetime.now().isoformat(),
                        'error': f"Step failed: {current_step}",
                        'step_error': step_result.get('error')
                    }, self.server_url)

                break

            if mlflow:
                next_step = self.agent.ml_recommendation(current_step, self.agent.context)
                if next_step:
                    step_config = self.agent.find_step(current_step)
                    next_steps = self.get_next_steps(step_config, self.agent.context)
                    step_with = {}
                    condition = "ml_recommendation"

                    for ns in next_steps:
                        if ns[0] == next_step:
                            step_with = ns[1]
                            condition = f"{ns[2]} (ml_selected)"
                            break

                    self.write_event_log(
                        'step_transition', f"{self.agent.execution_id}_transition_{next_step}",
                        f"transition_to_{next_step}", 'transition',
                        'success', 0, self.agent.context, None,
                        {'from_step': step_config.get('step'), 'to_step': next_step, 'with': step_with, 'condition': condition},
                        execution_start_event
                    )

                    if self.server_url and self.event_reporting_enabled:
                        report_event({
                            'event_type': 'step_transition',
                            'execution_id': self.agent.execution_id,
                            'from_step': step_config.get('step'),
                            'to_step': next_step,
                            'condition': condition,
                            'status': 'success',
                            'timestamp': datetime.datetime.now().isoformat(),
                            'with': step_with
                        }, self.server_url)

                    params = (
                        self.agent.execution_id,
                        step_config.get('step'),
                        next_step,
                        condition,
                        json.dumps(step_with) if step_with else '{}'
                    )

                    logger.debug(f"EXECUTION TRACKING: Step transition from {step_config.get('step')} to {next_step} with condition: {condition}")
                    logger.debug(f"EXECUTION TRACKING: Step parameters: {step_with}")

                    self.agent.store_transition(params)
                    self.agent.next_step_with = step_with
                    current_step = next_step
                else:
                    break
            else:
                if 'next_step' in step_result:
                    next_step = step_result['next_step']
                    logger.info(f"Using next_step from step result: {next_step}")

                    logger.debug(f"STEP RESULT DEBUG: Full step_result object: {step_result}")

                    if isinstance(next_step, list) and len(next_step) > 0 and isinstance(next_step[0], dict):
                        step_name = next_step[0].get('step', 'unknown')
                    elif isinstance(next_step, dict):
                        step_name = next_step.get('step', 'unknown')
                    else:
                        step_name = str(next_step)

                    step_with = {}
                    if 'params' in step_result:
                        step_with = step_result['params']
                        logger.debug(f"EXECUTION DEBUG: Using params from step_result: {step_with}")
                    elif 'data' in step_result and isinstance(step_result['data'], dict):
                        step_with = step_result['data']
                        logger.debug(f"EXECUTION DEBUG: Using data from step_result as params: {step_with}")
                    else:
                        logger.debug(f"EXECUTION DEBUG: No params or usable data in step_result, using empty dict")

                    self.write_event_log(
                        'step_transition', f"{self.agent.execution_id}_transition_{step_name}",
                        f"transition_to_{step_name}", 'transition',
                        'success', 0, self.agent.context, None,
                        {'from_step': step_config.get('step'), 'to_step': next_step, 'with': step_with, 'condition': 'direct_specification'},
                        execution_start_event
                    )

                    if self.server_url and self.event_reporting_enabled:
                        report_event({
                            'event_type': 'step_transition',
                            'execution_id': self.agent.execution_id,
                            'from_step': step_config.get('step'),
                            'to_step': next_step,
                            'condition': 'direct_specification',
                            'status': 'success',
                            'timestamp': datetime.datetime.now().isoformat(),
                            'with': step_with
                        }, self.server_url)

                    params = (
                        self.agent.execution_id,
                        step_config.get('step'),
                        step_name,
                        'direct_specification',
                        json.dumps(step_with)
                    )
                    self.agent.store_transition(params)
                    self.agent.next_step_with = step_with

                    current_step = step_name
                else:
                    next_steps = self.get_next_steps(step_config, self.agent.context)
                    if not next_steps:
                        logger.info(f"No next steps found for: {current_step}")
                        break

                    current_step, step_with, condition = next_steps[0]

                    if isinstance(current_step, list) and len(current_step) > 0 and isinstance(current_step[0], dict):
                        extracted_step_name = current_step[0].get('step', 'unknown')
                    elif isinstance(current_step, dict):
                        extracted_step_name = current_step.get('step', 'unknown')
                    else:
                        extracted_step_name = str(current_step)

                    current_step = extracted_step_name

                self.write_event_log(
                    'step_transition', f"{self.agent.execution_id}_transition_{current_step}",
                    f"transition_to_{current_step}", 'transition',
                    'success', 0, self.agent.context, None,
                    {'from_step': step_config.get('step'), 'to_step': current_step, 'with': step_with, 'condition': condition},
                    execution_start_event
                )

                if self.server_url and self.event_reporting_enabled:
                    report_event({
                        'event_type': 'step_transition',
                        'execution_id': self.agent.execution_id,
                        'from_step': step_config.get('step'),
                        'to_step': current_step,
                        'condition': condition,
                        'status': 'success',
                        'timestamp': datetime.datetime.now().isoformat(),
                        'with': step_with
                    }, self.server_url)

                params = (
                    self.agent.execution_id,
                    step_config.get('step'),
                    current_step,
                    condition,
                    json.dumps(step_with) if step_with else '{}'
                )

                self.agent.store_transition(params)
                self.agent.next_step_with = step_with

        logger.info(f"Playbook execution completed.")

        execution_duration = (datetime.datetime.now() - datetime.datetime.fromisoformat(
            self.agent.context.get('execution_start'))).total_seconds()

        self.write_event_log(
            'execution_complete',
            f"{self.agent.execution_id}_complete", self.agent.playbook.get('name', 'Unnamed'),
            'playbook',
            'success', execution_duration, self.agent.context, None,
            {'playbook_path': self.agent.playbook_path}, execution_start_event
        )

        if self.server_url and self.event_reporting_enabled:
            report_event({
                'event_type': 'execution_complete',
                'execution_id': self.agent.execution_id,
                'playbook_name': self.agent.playbook.get('name', 'Unnamed'),
                'status': 'success',
                'duration': execution_duration,
                'timestamp': datetime.datetime.now().isoformat(),
                'playbook_path': self.agent.playbook_path
            }, self.server_url)

        step_result = self.agent.get_step_results()
        return step_result



def execute_playbook_via_broker(
    playbook_content: str,
    playbook_path: str,
    playbook_version: str,
    input_payload: Optional[Dict[str, Any]] = None,
    sync_to_postgres: bool = True,
    merge: bool = False
) -> Dict[str, Any]:
    """
    Event-sourced kickoff of a playbook execution without directly using Worker.
    - Generates an execution_id.
    - Prepares merged workload context (playbook workload +/- input_payload).
    - Emits an execution_start event to the server API.
    - Returns immediately with the execution_id; further step evaluation is
      handled by the event-driven broker path.
    """
    logger.debug("=== BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Function entry ===")
    logger.debug(
        f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Parameters - playbook_path={playbook_path}, playbook_version={playbook_version}, input_payload={input_payload}, sync_to_postgres={sync_to_postgres}, merge={merge}"
    )

    try:
        # Create execution ID (prefer snowflake if available)
        try:
            from noetl.common import get_snowflake_id_str as _snow_id  # type: ignore
            execution_id = _snow_id()
        except Exception:
            try:
                from noetl.common import get_snowflake_id as _snow
                execution_id = str(_snow())
            except Exception:
                execution_id = str(uuid.uuid4())

        # Load workload from playbook content (best-effort)
        try:
            import yaml
            pb = yaml.safe_load(playbook_content) or {}
            base_workload = pb.get('workload', {}) if isinstance(pb, dict) else {}
        except Exception:
            base_workload = {}

        if input_payload:
            if merge:
                merged_workload = deep_merge(base_workload, input_payload)
            else:
                merged_workload = {**base_workload, **input_payload}
        else:
            merged_workload = base_workload

        # Emit execution_start directly via EventService to avoid HTTP loop/timeout
        try:
            ctx = {
                "path": playbook_path,
                "version": playbook_version,
                "workload": merged_workload,
            }
            try:
                from noetl.api.event import get_event_service
                es = get_event_service()
                import asyncio as _asyncio
                if _asyncio.get_event_loop().is_running():
                    # within async server context
                    _asyncio.create_task(es.emit({
                        'event_type': 'execution_start',
                        'execution_id': execution_id,
                        'status': 'in_progress',
                        'timestamp': datetime.datetime.now().isoformat(),
                        'node_type': 'playbook',
                        'node_name': playbook_path.split('/')[-1] if playbook_path else 'playbook',
                        'context': ctx,
                        'meta': {'playbook_path': playbook_path, 'resource_path': playbook_path, 'resource_version': playbook_version},
                    }))
                else:
                    # best-effort synchronous run
                    _asyncio.run(es.emit({
                        'event_type': 'execution_start',
                        'execution_id': execution_id,
                        'status': 'in_progress',
                        'timestamp': datetime.datetime.now().isoformat(),
                        'node_type': 'playbook',
                        'node_name': playbook_path.split('/')[-1] if playbook_path else 'playbook',
                        'context': ctx,
                        'meta': {'playbook_path': playbook_path, 'resource_path': playbook_path, 'resource_version': playbook_version},
                    }))
            except Exception:
                # Fallback to HTTP if direct emit fails
                server_url = os.environ.get("NOETL_SERVER_URL", "http://localhost:8082").rstrip('/')
                if not server_url.endswith('/api'):
                    server_url = server_url + '/api'
                report_event({
                    'event_type': 'execution_start',
                    'execution_id': execution_id,
                    'status': 'in_progress',
                    'timestamp': datetime.datetime.now().isoformat(),
                    'node_type': 'playbook',
                    'node_name': playbook_path.split('/')[-1] if playbook_path else 'playbook',
                    'context': ctx,
                    'meta': {'playbook_path': playbook_path, 'resource_path': playbook_path, 'resource_version': playbook_version},
                }, server_url)
        except Exception as e_evt:
            logger.warning(f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Failed to persist execution_start event: {e_evt}")

        result = {
            "status": "success",
            "message": f"Execution accepted for playbooks '{playbook_path}' version '{playbook_version}'.",
            "result": {"status": "queued"},
            "execution_id": execution_id,
            "export_path": None,
        }
        # Kick off broker evaluation for this execution id
        try:
            from noetl.api.event import evaluate_broker_for_execution
            import asyncio as _asyncio
            if _asyncio.get_event_loop().is_running():
                _asyncio.create_task(evaluate_broker_for_execution(execution_id))
            else:
                _asyncio.run(evaluate_broker_for_execution(execution_id))
        except Exception as _ev:
            logger.warning(f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Failed to start broker evaluation: {_ev}")
        logger.debug(
            f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Returning accepted result for execution_id={execution_id}"
        )
        logger.debug("=== BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Function exit ===")
        return result
    except Exception as e:
        logger.exception(
            f"BROKER.EXECUTE_PLAYBOOK_VIA_BROKER: Error preparing execution for playbooks '{playbook_path}' version '{playbook_version}': {e}."
        )
        return {
            "status": "error",
            "message": f"Error executing agent for playbooks '{playbook_path}' version '{playbook_version}': {e}.",
            "error": str(e),
        }
