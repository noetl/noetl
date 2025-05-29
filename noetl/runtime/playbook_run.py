import yaml
import jinja2
import requests
import uuid
from datetime import datetime
from typing import Dict, Any, List, Union
import sys
import os
from urllib.parse import urlparse
import json
import textwrap
import argparse
from noetl.util import setup_logger

logger = setup_logger(__name__, include_location=True)

def mock_http_response(task: Dict) -> Dict:
    endpoint = task.get('endpoint', '')
    method = task.get('method', 'GET')
    parsed_url = urlparse(endpoint)


    if 'open-meteo.com' in parsed_url.netloc:
        return {
            'status': 'success',
            'status_code': 200,
            'data': {
                'hourly': {
                    'temperature_2m': [20.5, 21.0, 22.5, 23.0, 24.5],
                    'precipitation_probability': [0, 10, 20, 30, 40],
                    'windspeed_10m': [5, 8, 12, 15, 18]
                }
            }
        }
    elif 'alerts.noetl.io' in parsed_url.netloc:
        return {
            'status': 'success',
            'status_code': 200,
            'data': {'message': 'Alert processed'}
        }
    elif 'db.noetl.io' in parsed_url.netloc:
        return {
            'status': 'success',
            'status_code': 200,
            'data': {'message': 'Data stored successfully'}
        }
    else:
        return {
            'status': 'success',
            'status_code': 200,
            'data': {'message': 'Mock response'}
        }


class PlaybookRunner:
    def __init__(self, playbook_path: str, mock: bool = False):
        self.playbook = self.load_playbook(playbook_path)
        self.context = self.playbook.get('context', {})
        self.results = {}
        self.mock_mode = mock
        self.environment = jinja2.Environment(
            undefined=jinja2.StrictUndefined,
            autoescape=False
        )
        self.environment.filters['to_json'] = json.dumps

        if '{{ job.uuid }}' in str(self.context):
            self.context['job'] = {'uuid': str(uuid.uuid4())}

    @staticmethod
    def load_playbook(path: str) -> dict:
        with open(path, 'r') as f:
            return yaml.safe_load(f)

    def render_template(self, template_str: str, extra_vars: Dict = None) -> Any:
        if not isinstance(template_str, str):
            return template_str

        vars_dict = {
            'context': self.context,
            'results': self.results,
            'now': datetime.now
        }
        if extra_vars:
            vars_dict.update(extra_vars)

        if not ('{{' in template_str and '}}' in template_str):
            return template_str

        try:
            template = self.environment.from_string(str(template_str))
            rendered = template.render(vars_dict)

            try:
                import ast
                return ast.literal_eval(rendered)
            except (ValueError, SyntaxError):
                if rendered.strip().startswith('{') or rendered.strip().startswith('['):
                    try:
                        return json.loads(rendered)
                    except json.JSONDecodeError:
                        pass
            return rendered
        except Exception as e:
            logger.error(f"Template rendering error for '{template_str}': {e}")
            raise

    def execute(self):
        current_step = 'start'
        visited_steps = set()

        while current_step != 'end':
            try:
                if current_step in visited_steps:
                    logger.error(f"Circular dependency detected. Step {current_step} has already been visited.")
                    break

                visited_steps.add(current_step)

                logger.debug(f"Executing step: {current_step}")
                # logger.debug(f"Current context: {json.dumps(self.context, indent=2, default=str)}")

                next_step = self.execute_step(current_step)

                logger.debug(f"Step {current_step} completed. Next step: {next_step}")
                # logger.debug(f"Updated context: {json.dumps(self.context, indent=2, default=str)}")

                if next_step:
                    current_step = next_step
                else:
                    current_step = 'end'

            except Exception as e:
                logger.error(f"Error in step {current_step}: {e}", exc_info=True)
                if current_step == 'error_handler':
                    logger.error("Error in error handler, stopping execution")
                    break
                self.context['state'] = 'error'
                self.context['error'] = str(e)
                current_step = 'error_handler'

        logger.info("Workflow completed")
        return self.results


    def execute_step(self, step_name: str) -> str | dict:
        logger.debug(f"Looking for step: {step_name}")
        step = next((s for s in self.playbook.get('workflow', []) if s.get('step') == step_name), None)

        if not step:
            logger.error(f"Step not found: {step_name}")
            raise ValueError(f"Step not found: {step_name}")

        logger.info(f"Executing step: {step_name}")
        logger.debug(f"Step configuration: {json.dumps(step, indent=2)}")

        try:
            if step.get('run'):
                for task in step.get('run', []):
                    task_name = self.render_template(task.get('task'))
                    logger.debug(f"Executing task: {task_name}")
                    try:
                        self.execute_task(task_name)
                    except Exception as e:
                        logger.error(f"Error executing task {task_name} in step {step_name}: {e}")
                        raise

            if not step.get('next'):
                logger.debug(f"No next steps defined for {step_name}, returning 'end'")
                return 'end'

            for transition in step.get('next', []):
                next_step = None
                next_context = {}

                if transition.get('when'):
                    condition = self.render_template(transition.get('when'))
                    logger.debug(f"Evaluating condition: {condition}")
                    try:
                        if eval(str(condition), {"__builtins__": {}},
                                {'context': self.context, 'results': self.results}):
                            then_steps = transition.get('then', [])
                            if then_steps:
                                next_step_def = then_steps[0]
                                if isinstance(next_step_def, dict):
                                    next_step = next_step_def.get('step')
                                    context_data = {k: v for k, v in next_step_def.items() if k != 'step'}
                                    for key, value in context_data.items():
                                        rendered_value = self.render_template(value)
                                        next_context[key] = rendered_value
                                else:
                                    next_step = next_step_def
                    except Exception as e:
                        logger.error(f"Error evaluating condition '{condition}': {e}")
                        raise
                elif transition.get('else'):
                    else_steps = transition.get('else', [])
                    if else_steps:
                        next_step_def = else_steps[0]
                        if isinstance(next_step_def, dict):
                            next_step = next_step_def.get('step')
                            context_data = {k: v for k, v in next_step_def.items() if k != 'step'}
                            for key, value in context_data.items():
                                rendered_value = self.render_template(value)
                                next_context[key] = rendered_value
                        else:
                            next_step = next_step_def

                if next_step:
                    if next_context:
                        logger.debug(f"Updating context for step {next_step} with: {next_context}")
                        self.context.update(next_context)
                    return next_step

            logger.debug(f"No matching transitions for {step_name}, returning 'end'")
            return 'end'

        except Exception as e:
            logger.error(f"Error in step {step_name}: {e}")
            self.context['state'] = 'error'
            self.context['error'] = str(e)
            return 'error_handler'



    def find_task(self, task_name: str) -> Dict:
        for task in self.playbook.get('workbook', []):
            if task.get('task') == task_name:
                return task
            if task.get('run'):
                nested_task = next((t for t in task.get('run', []) if t.get('task') == task_name), None)
                if nested_task:
                    return nested_task

        for step in self.playbook.get('workflow', []):
            if step.get('run'):
                task = next((t for t in step.get('run', []) if t.get('task') == task_name), None)
                if task:
                    return task
        return {}

    def execute_task(self, task_name: str, context: Dict = None, parent_result: Any = None) -> Any:
        context = context or {}

        def execute_recursive(task: Union[str, Dict], current_context: Dict, parent_result: Any = None) -> Any:
            if isinstance(task, str):
                task_def = self.find_task(task)
                if not task_def:
                    raise ValueError(f"Task not found: {task}")
            else:
                task_def = task

            logger.debug(f"Executing task: {task_def.get('task')} with parent result: {parent_result}")

            task_context = {
                **current_context,
                'results': parent_result
            }

            if 'loop' in task_def:
                return execute_loop(task_def, task_context)

            current_result = execute_single(task_def, task_context)

            if 'run' in task_def:
                for nested_task in task_def['run']:
                    nested_context = {**task_context}
                    rendered_task = render_task_templates(nested_task, nested_context)
                    current_result = execute_recursive(rendered_task, nested_context, current_result)

            return current_result

        def execute_loop(task: Dict, context: Dict) -> List:
            loop_spec = task['loop']
            iterator_name = loop_spec.get('iterator')
            loop_data = render_value(loop_spec.get('in'), context)

            if isinstance(loop_data, str):
                import ast
                try:
                    loop_data = ast.literal_eval(loop_data)
                except (ValueError, SyntaxError) as e:
                    raise ValueError(f"Failed to parse loop data: {e}")

            if not isinstance(loop_data, list):
                raise ValueError(f"Loop data must be a list, got: {type(loop_data)}")

            results = []
            for idx, item in enumerate(loop_data):
                logger.info(f"Processing loop item {idx + 1}/{len(loop_data)}")
                iteration_context = {**context, iterator_name: item}
                task_without_loop = task.copy()
                task_without_loop.pop('loop')
                result = execute_recursive(task_without_loop, iteration_context)
                results.append(result)
                logger.info(f"Completed loop item {idx + 1}", extra={'results': result})

            return results

        def execute_single(task: Dict, context: Dict) -> Any:
            task_type = task.get('type', 'unknown')
            rendered_task = render_task_templates(task, context)
            try:
                return self.execute_task_instance(rendered_task, task_type, context)
            except Exception as e:
                logger.error(f"Error executing task {task.get('task')}: {str(e)}")
                raise

        def render_task_templates(task: Dict, context: Dict) -> Dict:
            rendered = {}
            for key, value in task.items():
                if isinstance(value, str):
                    rendered[key] = render_value(value, context)
                elif isinstance(value, dict):
                    rendered[key] = render_task_templates(value, context)
                elif isinstance(value, list):
                    rendered[key] = [
                        render_task_templates(item, context) if isinstance(item, dict)
                        else render_value(item, context) if isinstance(item, str)
                        else item
                        for item in value
                    ]
                else:
                    rendered[key] = value
            return rendered

        def render_value(value: Any, context: Dict) -> Any:
            if isinstance(value, str) and ('{{' in value or '{%' in value):
                return self.render_template(value, context)
            return value

        try:
            result = execute_recursive(task_name, context, parent_result)
            # task_id = task_name if isinstance(task_name, str) else task.get('task')
            self.results[task_name] = result
            return result
        except Exception as e:
            error_result = {'status': 'error', 'error': str(e)}
            if isinstance(task_name, str):
                self.results[task_name] = error_result
            raise

    def execute_task_instance(self, task: Dict, task_type: str, vars_dict: Dict = None) -> Any:
        if task_type == 'http':
            return self.execute_http_task(task, vars_dict)
        elif task_type == 'python':
            return self.execute_python_task(task, vars_dict)
        elif task_type == 'runner':
            return self.execute_runner_task(task, vars_dict)
        else:
            raise ValueError(f"Unsupported task type: {task_type}")

    def execute_http_task(self, task: Dict, extra_vars: Dict = None) -> Dict:
        method = task.get('method', 'GET')
        endpoint = self.render_template(task.get('endpoint'), extra_vars)

        logger.debug(f"Executing HTTP {method} request to {endpoint}")

        if self.mock_mode:
            logger.debug("Using mock response")
            return mock_http_response(task)

        params = {}
        if task.get('params'):
            params = {k: self.render_template(v, extra_vars)
                      for k, v in task.get('params', {}).items()}

        payload = None
        if task.get('payload'):
            payload = self.render_template(task.get('payload'), extra_vars)

        try:
            logger.debug(f"HTTP request params: {params}")
            logger.debug(f"HTTP request payload: {payload}")

            response = requests.request(
                method=method,
                url=endpoint,
                params=params,
                json=payload,
                timeout=10
            )

            result = {
                'status': 'success' if response.ok else 'error',
                'status_code': response.status_code,
                'data': response.json() if response.ok else None
            }

            logger.debug(f"HTTP response: {json.dumps(result, indent=2)}")
            return result

        except requests.exceptions.RequestException as e:
            logger.error(f"HTTP request failed: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }

    def execute_python_task(self, task: Dict, extra_vars: Dict = None) -> Dict:
        code = task.get('code', '')
        namespace = {
            'context': self.context,
            'results': self.results,
            'logger': logger
        }
        if extra_vars:
            namespace.update(extra_vars)

        try:
            logger.debug(f"Executing Python code:\n{code}")
            exec(code, namespace)

            main_func = namespace.get('main')
            if not main_func or not callable(main_func):
                raise ValueError("Python task must define a 'main(context, results)' function")

            result = main_func(namespace.get('context', {}), namespace.get('results', {}))

            # logger.debug(f"Python task {task.get('task')} result: {result}")

            return {
                'status': 'success',
                'data': result
            }

        except Exception as e:
            logger.error(f"Error executing Python task: {e}", exc_info=True)
            return {
                'status': 'error',
                'error': str(e)
            }

    def execute_runner_task(self, task: Dict, extra_vars: Dict = None) -> Any:
        try:
            if extra_vars:
                iterator_name = task.get('loop', {}).get('iterator')
                if iterator_name and iterator_name in extra_vars:
                    return {iterator_name: extra_vars[iterator_name]}
            return extra_vars or {}
        except Exception as e:
            logger.error(f"Error in runner task: {e}", exc_info=True)
            raise


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Execute NoETL playbook')

    parser.add_argument(
        '--mock',
        action='store_true',
        help='Run in mock mode (simulate HTTP requests)'
    )

    parser.add_argument(
        '-f', '--file',
        required=True,
        help='Path to the playbook YAML file'
    )

    parser.add_argument(
        '-v', '--verbose',
        action='store_true',
        help='Enable verbose logging'
    )

    parser.add_argument(
        '--dry-run',
        action='store_true',
        help='Validate playbook without executing it'
    )

    parser.add_argument(
        '--output',
        choices=['json', 'yaml', 'plain'],
        default='plain',
        help='Output format for results (default: plain)'
    )

    return parser.parse_args()


def validate_playbook_file(file_path: str) -> None:
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Playbook file not found: {file_path}")

    if not os.path.isfile(file_path):
        raise ValueError(f"Path is not a file: {file_path}")

    if not os.access(file_path, os.R_OK):
        raise PermissionError(f"Cannot read playbook file: {file_path}")

def format_output(results: Dict, format_type: str) -> str:
    if format_type == 'json':
        import json
        return json.dumps(results, indent=2)
    elif format_type == 'yaml':
        return yaml.dump(results, default_flow_style=False)
    else:
        return str(results)


def main():
    try:
        args = parse_arguments()
        validate_playbook_file(args.file)
        executor = PlaybookRunner(args.file)
        if args.dry_run:
            logger.info("Dry run - validating playbook structure.")
            logger.info("Playbook structure is valid")
            return 0

        logger.info(f"Executing playbook: {args.file}")
        results = executor.execute()
        output = format_output(results, args.output)
        logger.debug(output)

        return 0

    except FileNotFoundError as e:
        logger.error(f"File error: {e}")
        return 1
    except yaml.YAMLError as e:
        logger.error(f"YAML parsing error: {e}")
        return 1
    except Exception as e:
        logger.error(f"Error executing playbook: {e}")
        if args.verbose:
            logger.exception("Detailed error information:")
        return 1


if __name__ == '__main__':
    sys.exit(main())
