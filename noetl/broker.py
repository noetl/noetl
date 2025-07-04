import json
import os
import uuid
import datetime
import tempfile
import httpx
import psycopg
from typing import Dict, List, Any, Tuple, Optional
from noetl.action import execute_task, report_event
from noetl.common import render_template, setup_logger, deep_merge
from noetl.worker import NoETLAgent
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
        self.server_url = server_url or os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082')
        self.event_reporting_enabled = True
        self.validate_server_url()

    def validate_server_url(self):
        """
        Validates the server URL.
        Disables event reporting if the server is not reachable.
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
        Execute a playbook call.

        Args:
            path: The path of the playbook to execute
            version: The version of the playbook to execute (optional, uses latest if not provided)
            input_payload: The input payload to pass to the playbook (optional)
            merge: Whether to merge the input payload with the workload (default: True)

        Returns:
            A dictionary containing the results of the playbook execution
        """
        try:
            from noetl.server import get_catalog_service
            catalog_service = get_catalog_service()

            if not version:
                version = catalog_service.get_latest_version(path)
                logger.info(f"Version not specified for playbook '{path}', using latest version: {version}")

            entry = catalog_service.fetch_entry(path, version)
            if not entry:
                error_msg = f"Playbook '{path}' with version '{version}' not found in catalog."
                logger.error(error_msg)
                return {
                    'status': 'error',
                    'error': error_msg
                }

            with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as temp_file:
                temp_file.write(entry.get("content").encode('utf-8'))
                temp_file_path = temp_file.name

            try:
                pgdb_conn = self.agent.pgdb
                child_agent = NoETLAgent(temp_file_path, mock_mode=self.agent.mock_mode, pgdb=pgdb_conn)
                workload = child_agent.playbook.get('workload', {})
                if input_payload:
                    if merge:
                        logger.info(f"Merge mode: merging input payload with workload for playbook '{path}'")
                        merged_workload = deep_merge(workload, input_payload)
                        for key, value in merged_workload.items():
                            child_agent.update_context(key, value)
                        child_agent.update_context('workload', merged_workload)
                        child_agent.store_workload(merged_workload)
                    else:
                        logger.info(f"Override mode: replacing workload keys with input payload for playbook '{path}'")
                        merged_workload = workload.copy()
                        for key, value in input_payload.items():
                            merged_workload[key] = value
                        for key, value in merged_workload.items():
                            child_agent.update_context(key, value)
                        child_agent.update_context('workload', merged_workload)
                        child_agent.store_workload(merged_workload)
                else:
                    logger.info(f"No input payload provided for playbook '{path}'. Using default workload.")
                    for key, value in workload.items():
                        child_agent.update_context(key, value)
                    child_agent.update_context('workload', workload)
                    child_agent.store_workload(workload)

                child_broker = Broker(child_agent, server_url=self.server_url)
                results = child_broker.run()

                return {
                    'status': 'success',
                    'data': results,
                    'execution_id': child_agent.execution_id
                }
            finally:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)

        except Exception as e:
            error_msg = f"Error executing playbook '{path}': {str(e)}"
            logger.error(error_msg, exc_info=True)
            return {
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
        step_id = str(uuid.uuid4())
        start_time = datetime.datetime.now()

        step_config = self.agent.find_step(step_name)
        if not step_config:
            error_msg = f"Step not found: {step_name}"
            self.agent.save_step_result(
                step_id, step_name, None,
                'error', None, error_msg
            )
            self.agent.log_event(
                'step_error', step_id, step_name, 'step',
                'error', 0, self.agent.get_context(), None,
                {'error': error_msg}, None
            )

            return {
                'id': step_id,
                'status': 'error',
                'error': error_msg
            }

        logger.info(f"Executing step: {step_name}")
        logger.debug(f"Executing step: step_name={step_name}, step_with={step_with}")
        logger.debug(f"Executing step: context before update: {self.agent.context}")
        step_context = self.agent.get_context()
        if step_with:
            rendered_with = render_template(self.agent.jinja_env, step_with, step_context)
            logger.debug(f"Executing step: rendered_with={rendered_with}")
            if rendered_with:
                step_context.update(rendered_with)
                for key, value in rendered_with.items():
                    self.agent.update_context(key, value)

        logger.debug(f"Executing step: context after update: {step_context}")
        step_event = self.agent.log_event(
            'step_start', step_id, step_name, 'step',
            'in_progress', 0, step_context, None,
            {'step_type': 'standard'}, None
        )
        if self.server_url and self.event_reporting_enabled:
            report_event({
                'event_type': 'step_start',
                'execution_id': self.agent.execution_id,
                'step_id': step_id,
                'step_name': step_name,
                'status': 'in_progress',
                'timestamp': datetime.datetime.now().isoformat(),
                'context': {k: v for k, v in step_context.items() if not k.startswith('_')}
            }, self.server_url)

        if 'end_loop' in step_config:
            result = self.end_loop_step(step_config, step_context, step_id)
        elif 'loop' in step_config:
            result = self.execute_loop_step(step_config, step_context, step_id)
        elif 'call' in step_config:
            call_config = step_config['call']
            task_name = call_config.get('name') or call_config.get('task')
            call_type = call_config.get('type', 'workbook')
            task_with = render_template(self.agent.jinja_env, call_config.get('with', {}), step_context)
            task_context = {**step_context, **task_with}

            if call_type == 'workbook':
                task_config = self.agent.find_task(task_name)
                result = execute_task(
                    task_config, 
                    task_name, 
                    task_context, 
                    self.agent.jinja_env,
                    self.agent.secret_manager,
                    self.agent.mock_mode,
                    self.agent.log_event
                )
            elif call_type == 'playbook':
                path = call_config.get('path')
                version = call_config.get('version')

                if not path:
                    error_msg = "Missing 'path' parameter in playbook call."
                    logger.error(error_msg)
                    result = {
                        'id': str(uuid.uuid4()),
                        'status': 'error',
                        'error': error_msg
                    }
                else:
                    playbook_result = self.execute_playbook_call(
                        path=path,
                        version=version,
                        input_payload=task_with,
                        merge=True
                    )

                    result = {
                        'id': str(uuid.uuid4()),
                        'status': playbook_result.get('status', 'error'),
                        'data': playbook_result.get('data'),
                        'error': playbook_result.get('error')
                    }
            elif call_type in ['http', 'python', 'duckdb', 'postgres', 'secrets']:
                task_config = {
                    'type': call_type,
                    'with': call_config.get('with', {})
                }
                fields = ['name', 'params', 'commands', 'return', 'headers', 'url', 'method', 'body', 'code', 'provider', 'secret_name']
                task_config.update({
                    field: call_config.get(field)
                    for field in fields
                    if field in call_config
                })

                result = execute_task(
                    task_config,
                    task_name or f"step_{call_type}_task",
                    task_context,
                    self.agent.jinja_env,
                    self.agent.secret_manager,
                    self.agent.mock_mode,
                    self.agent.log_event
                )
            else:
                error_msg = f"Unsupported call type: {call_type}"
                logger.error(error_msg)
                result = {
                    'id': str(uuid.uuid4()),
                    'status': 'error',
                    'error': error_msg
                }

            self.agent.save_step_result(
                step_id, step_name, None,
                result.get('status', 'success'), result.get('data'), result.get('error')
            )

            self.agent.update_context(step_name, result.get('data'))
            self.agent.update_context(step_name + '.result', result.get('data'))
            self.agent.update_context(step_name + '.status', result.get('status'))
            self.agent.update_context('result', result.get('data'))
        else:
            self.agent.save_step_result(
                step_id, step_name, None,
                'success', {}, None
            )
            result = {
                'id': step_id,
                'status': 'success',
                'data': {}
            }

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        self.agent.log_event(
            'step_complete', step_id, step_name, 'step',
            result['status'], duration, step_context, result.get('data'),
            {'step_type': 'standard'}, step_event
        )

        if self.server_url and self.event_reporting_enabled:
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

        return result

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
            self.agent.log_event(
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
        end_loop_event = self.agent.log_event(
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
            self.agent.log_event(
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
        self.agent.log_event(
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
            self.agent.log_event(
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
            self.agent.log_event(
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
        loop_start_event = self.agent.log_event(
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

            iter_event = self.agent.log_event(
                'loop_iteration', f"{loop_id}_{idx}", f"{loop_name}[{idx}]", 'iteration',
                'in_progress', 0, context, None,
                {'index': idx, 'item': item}, loop_start_event,
                loop_id=loop_id, loop_name=loop_name, iterator=iterator,
                items=items, current_index=idx, current_item=item, results=all_results,
                worker_id=os.environ.get('WORKER_ID', 'local'), distributed_state='processing'
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
                self.agent.log_event(
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
            self.agent.log_event(
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

        self.agent.log_event(
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
        logger.info(f"Starting playbook: {self.agent.playbook.get('name', 'Unnamed')}")
        self.agent.update_context('execution_start', datetime.datetime.now().isoformat())
        execution_start_event = self.agent.log_event(
            'execution_start', self.agent.execution_id, self.agent.playbook.get('name', 'Unnamed'),
            'playbook',
            'in_progress',
            0, self.agent.context,
            None,
            {'playbook_path': self.agent.playbook_path},
            None
        )

        if self.server_url and self.event_reporting_enabled:
            report_event({
                'event_type': 'execution_start',
                'execution_id': self.agent.execution_id,
                'playbook_name': self.agent.playbook.get('name', 'Unnamed'),
                'status': 'in_progress',
                'timestamp': datetime.datetime.now().isoformat(),
                'playbook_path': self.agent.playbook_path
            }, self.server_url)

        current_step = 'start'
        while current_step and current_step != 'end':
            step_config = self.agent.find_step(current_step)
            if not step_config:
                logger.error(f"Step not found: {current_step}")
                self.agent.log_event(
                    'execution_error',
                    f"{self.agent.execution_id}_error", self.agent.playbook.get('name', 'Unnamed'),
                    'playbook',
                    'error', 0, self.agent.context, None,
                    {'error': f"Step not found: {current_step}"}, execution_start_event
                )

                if self.server_url and self.event_reporting_enabled:
                    report_event({
                        'event_type': 'execution_error',
                        'execution_id': self.agent.execution_id,
                        'playbook_name': self.agent.playbook.get('name', 'Unnamed'),
                        'status': 'error',
                        'timestamp': datetime.datetime.now().isoformat(),
                        'error': f"Step not found: {current_step}"
                    }, self.server_url)

                break

            step_result = self.execute_step(current_step, self.agent.next_step_with)
            self.agent.next_step_with = None

            if step_result['status'] != 'success':
                logger.error(f"Step failed: {current_step}, error: {step_result.get('error')}")
                self.agent.log_event(
                    'execution_error',
                    f"{self.agent.execution_id}_error", self.agent.playbook.get('name', 'Unnamed'),
                    'playbook',
                    'error', 0, self.agent.context, None,
                    {'error': f"Step failed: {current_step}", 'step_error': step_result.get('error')},
                    execution_start_event
                )

                if self.server_url and self.event_reporting_enabled:
                    report_event({
                        'event_type': 'execution_error',
                        'execution_id': self.agent.execution_id,
                        'playbook_name': self.agent.playbook.get('name', 'Unnamed'),
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

                    self.agent.log_event(
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

                    self.agent.store_transition(params)
                    self.agent.next_step_with = step_with
                    current_step = next_step
                else:
                    break
            else:
                if 'next_step' in step_result:
                    next_step = step_result['next_step']
                    logger.info(f"Using next_step from step result: {next_step}")

                    self.agent.log_event(
                        'step_transition', f"{self.agent.execution_id}_transition_{next_step}",
                        f"transition_to_{next_step}", 'transition',
                        'success', 0, self.agent.context, None,
                        {'from_step': step_config.get('step'), 'to_step': next_step, 'with': {}, 'condition': 'direct_specification'},
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
                            'with': {}
                        }, self.server_url)

                    params = (
                        self.agent.execution_id,
                        step_config.get('step'),
                        next_step,
                        'direct_specification',
                        '{}'
                    )

                    self.agent.store_transition(params)
                    current_step = next_step
                else:
                    next_steps = self.get_next_steps(step_config, self.agent.context)
                    if not next_steps:
                        logger.info(f"No next steps found for: {current_step}")
                        break

                    current_step, step_with, condition = next_steps[0]

                self.agent.log_event(
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

        self.agent.log_event(
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
