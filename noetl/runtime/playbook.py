import yaml
import jinja2
import requests
import uuid
from datetime import datetime
from typing import Dict, Any, List
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


class PlaybookExecutor:
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

            if rendered.strip().startswith('{') or rendered.strip().startswith('['):
                try:
                    return json.loads(rendered)
                except json.JSONDecodeError:
                    pass

            return rendered
        except Exception as e:
            logger.error(f"Template rendering error for '{template_str}': {e}")
            raise

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


    def execute_http_task(self, task: Dict, extra_vars: Dict = None) -> Dict:
        method = task.get('method', 'GET')
        endpoint = self.render_template(task.get('endpoint'), extra_vars)

        if self.mock_mode:
            return mock_http_response(task)

        params = {}
        if task.get('params'):
            params = {k: self.render_template(v, extra_vars)
                     for k, v in task.get('params', {}).items()}

        payload = None
        if task.get('payload'):
            payload = self.render_template(task.get('payload'), extra_vars)

        try:
            response = requests.request(
                method=method,
                url=endpoint,
                params=params,
                json=payload,
                timeout=10
            )

            return {
                'status': 'success' if response.ok else 'error',
                'status_code': response.status_code,
                'data': response.json() if response.ok else None
            }
        except requests.exceptions.RequestException as e:
            return {
                'status': 'error',
                'error': str(e)
            }

    def execute_runner_task(self, task: Dict, extra_vars: Dict = None) -> List:
        def process_task(current_task: Dict, vars_dict: Dict = None) -> Any:
            task_copy = current_task.copy()
            for key, value in task_copy.items():
                if isinstance(value, str):
                    task_copy[key] = self.render_template(value, vars_dict)
                elif isinstance(value, dict):
                    for subkey, subvalue in value.items():
                        if isinstance(subvalue, str):
                            task_copy[key][subkey] = self.render_template(subvalue, vars_dict)
            task_name = task_copy.get('task', 'unnamed')
            task_type = task_copy.get('type', 'runner')
            logger.info(f"Processing task: {task_name} (type: {task_type})")
            logger.debug(f"Task details: {task_copy}")
            match task_type:
                case 'http':
                    result = self.execute_http_task(task_copy, vars_dict)
                case 'python':
                    result = self.execute_python_task(task_copy, vars_dict)
                case _:
                    raise ValueError(f"Unsupported task type: {task_type}")

            nested_results = []
            if task_copy.get('run'):
                for nested_task in task_copy.get('run', []):
                    nested_result = process_task(nested_task, vars_dict)
                    nested_results.append(nested_result)

            return [result] + nested_results if nested_results else result

        try:
            if task.get('loop'):
                logger.info(f"Executing runner task with loop. Task: {task.get('task', 'unnamed')}")
                loop_data = self.render_template(task.get('loop', {}).get('in'), extra_vars)
                iterator_name = task.get('loop', {}).get('iterator')
                if isinstance(loop_data, str):
                    import ast
                    try:
                        logger.debug("Converting string loop data to Python object")
                        loop_data = ast.literal_eval(loop_data)
                    except (ValueError, SyntaxError) as e:
                        logger.error(f"Failed to parse loop data: {e}")
                        raise

                if not isinstance(loop_data, list):
                    raise ValueError(f"Loop data must be a list, got: {type(loop_data)}")

                results = []
                for idx, item in enumerate(loop_data):
                    logger.info(f"Processing loop item {idx + 1}/{len(loop_data)}")
                    loop_vars = {iterator_name: item}
                    if extra_vars:
                        loop_vars.update(extra_vars)

                    iteration_results = []
                    for subtask in task.get('run', []):
                        result = process_task(subtask, loop_vars)
                        iteration_results.append(result)

                    results.append(iteration_results)
                    logger.info(f"Completed loop item {idx + 1} {item}", extra={'results': iteration_results})
                return results
            logger.info("No loop found, executing tasks directly")
            return [process_task(subtask, extra_vars)
                    for subtask in task.get('run', [])]

        except Exception as e:
            logger.error(f"Error in runner task: {e}", exc_info=True)
            raise


    def execute_python_task(self, task: Dict, extra_vars: Dict = None) -> Dict:
        code = task.get('code', '')
        local_vars = {
            'context': self.context,
            'results': self.results,
            'result': None
        }
        if extra_vars:
            local_vars.update(extra_vars)


        try:
            code = textwrap.dedent(code)
            code_lines = code.split('\n')
            modified_code = []
            for line in code_lines:
                if 'return' in line:
                    modified_code.append(line.replace('return', 'result ='))
                else:
                    modified_code.append(line)

            final_code = '\n'.join(modified_code)
            exec(final_code, globals(), local_vars)
            result = local_vars.get('result')
            if result is not None:
                if isinstance(result, dict):
                    result['status'] = 'success'
                else:
                    result = {
                        'status': 'success',
                        'data': result
                    }
                return result

            return {
                'status': 'success',
                'data': None
            }
        except Exception as e:
            logger.error(f"Error executing Python task: {e}")
            return {
                'status': 'error',
                'error': str(e)
            }

    def execute_task(self, task_name: str, extra_vars: Dict = None) -> Any:
        task = self.find_task(task_name)

        if not task:
            raise ValueError(f"Task not found: {task_name}")

        task_type = task.get('type', 'unknown')
        logger.info(f"Executing task: {task_name} (type: {task_type})")

        try:
            match task_type:
                case 'http':
                    result = self.execute_http_task(task, extra_vars)
                case 'python':
                    result = self.execute_python_task(task, extra_vars)
                case 'runner':
                    result = self.execute_runner_task(task, extra_vars)
                case 'unknown':
                    raise ValueError(f"Task type is unknown for task: {task_name}")
                case _:
                    raise ValueError(f"Unsupported task type: {task_type}")

            self.results[task_name] = result
            return result
        except Exception as e:
            logger.error(f"Error executing task {task_name}: {str(e)}")
            self.results[task_name] = {
                'status': 'error',
                'error': str(e)
            }
            raise


    def execute_step(self, step_name: str) -> str:
        step = next((s for s in self.playbook.get('workflow', [])
                    if s.get('step') == step_name), None)

        if not step:
            raise ValueError(f"Step not found: {step_name}")

        logger.info(f"Executing step: {step_name}")

        try:
            if step.get('run'):
                for task in step.get('run', []):
                    task_name = self.render_template(task.get('task'))
                    try:
                        self.execute_task(task_name)
                    except Exception as e:
                        logger.error(f"Error executing task {task_name} in step {step_name}: {e}")
                        raise

            if not step.get('next'):
                return 'end'

            for transition in step.get('next', []):
                if transition.get('when'):
                    condition = self.render_template(transition.get('when'))
                    if eval(str(condition)):
                        return transition.get('then', ['end'])[0]
                elif transition.get('else'):
                    return transition.get('else', ['end'])[0]

            return 'end'

        except Exception as e:
            logger.error(f"Error in step {step_name}: {e}")
            self.context['state'] = 'error'
            self.context['error'] = str(e)
            return 'error_handler'


    def execute(self):
        current_step = 'start'
        visited_steps = set()

        while current_step != 'end':
            try:
                if current_step in visited_steps:
                    logger.error(f"Circular dependency detected! Step {current_step} has already been visited")
                    break

                visited_steps.add(current_step)
                current_step = self.execute_step(current_step)

            except Exception as e:
                logger.error(f"Error in step {current_step}: {e}")
                if current_step == 'error_handler':
                    logger.error("Error in error handler, stopping execution")
                    break
                self.context['state'] = 'error'
                self.context['error'] = str(e)
                current_step = 'error_handler'

        logger.info("Workflow completed")
        return self.results


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
        executor = PlaybookExecutor(args.file)
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
