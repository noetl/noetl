import yaml
import jinja2
import requests
import uuid
import time
from datetime import datetime
from typing import Dict, Any
import sys
import os
from urllib.parse import urlparse
import json
import argparse
from noetl.util import setup_logger
import random

logger = setup_logger(__name__, include_location=True)


def mock_http_response(task: Dict) -> Dict:
    endpoint = task.get('endpoint', '')
    method = task.get('method', 'GET')
    parsed_url = urlparse(endpoint)

    if not hasattr(mock_http_response, "last_above_25"):
        mock_http_response.last_above_25 = False

    if '/forecast' in parsed_url.path:
        if not mock_http_response.last_above_25:
            temps = [round(random.uniform(20, 30), 1) for _ in range(24)]
            temps[random.randint(0, 23)] = round(random.uniform(26, 30), 1)
            mock_http_response.last_above_25 = True
        else:
            temps = [round(random.uniform(20, 24.9), 1) for _ in range(24)]
            mock_http_response.last_above_25 = False
        precip = [random.randint(0, 100) for _ in range(24)]
        wind = [round(random.uniform(5, 25), 1) for _ in range(24)]
        return {
            'status': 'success',
            'status_code': 200,
            'data': {
                'hourly': {
                    'temperature_2m': temps,
                    'precipitation_probability': precip,
                    'windspeed_10m': wind
                }
            }
        }
    elif '/weather-alerts' in parsed_url.path:
        return {
            'status': 'success',
            'status_code': 200,
            'data': {'message': 'Alert processed successfully'}
        }
    elif '/errors' in parsed_url.path:
        return {
            'status': 'success',
            'status_code': 200,
            'data': {'message': 'Error logged successfully'}
        }
    else:
        return {
            'status': 'success',
            'status_code': 200,
            'data': {'message': 'Mock response'}
        }


def deep_merge(a, b):
    result = dict(a)
    for k, v in b.items():
        if (
            k in result and isinstance(result[k], dict) and isinstance(v, dict)
        ):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def execute_python_task(task: Dict, namespace: Dict) -> Any:
    namespace = dict(namespace)
    namespace.update({'__builtins__': __builtins__})
    try:
        exec(task.get('code', ''), namespace)
        main_func = namespace.get('main')
        if not main_func or not callable(main_func):
            raise ValueError("Python task must define a 'main' function")
        import inspect
        sig = inspect.signature(main_func)
        input_data = namespace.get('input', {})
        filtered_input = {k: v for k, v in input_data.items() if k in sig.parameters}
        result = main_func(**filtered_input)
        if isinstance(result, dict) and 'status' in result and 'data' in result:
            return result
        return {'status': 'success', 'data': result}
    except Exception as e:
        logger.error(f"Error executing Python task: {e}", exc_info=True)
        return {'status': 'error', 'error': str(e)}


class PlaybookAgent:
    def __init__(self, playbook_path: str, mock: bool = False):
        self.playbook = self.load_playbook(playbook_path)
        self.context = {}
        self.results = {}
        self.mock_mode = mock
        self.environment = jinja2.Environment(
            undefined=jinja2.StrictUndefined,
            autoescape=False
        )
        self.environment.trim_blocks = True
        self.jinja2_filters = {
            'to_json': json.dumps
        }
        self.jinja2_tests = {
            'sequence': lambda x: isinstance(x, (list, tuple))
        }
        self.environment.filters.update(self.jinja2_filters)
        self.environment.tests.update(self.jinja2_tests)

        initial_context = {
            'job': {
                'uuid': str(uuid.uuid4())
            }
        }
        self.context.update(initial_context)
        workload = self.render_template(self.playbook.get('workload', {}), initial_context)
        self.context = {
            'job': initial_context['job'],
            'workload': workload
        }

    @staticmethod
    def load_playbook(path: str) -> dict:
        with open(path, 'r') as f:
            return yaml.safe_load(f)

    def render_template(self, template, context: Dict = None) -> Any:
        if isinstance(template, dict):
            return {k: self.render_template(v, context) for k, v in template.items()}
        elif isinstance(template, list):
            return [self.render_template(item, context) for item in template]
        elif not isinstance(template, str):
            return template
        vars_dict = {
            **self.context,
            'workload': self.context.get('workload', {}),
            'results': self.results,
            'now': datetime.now,
            **(context or {})
        }

        if not ('{{' in str(template) or '{%' in str(template)):
            return template

        try:
            template_obj = self.environment.from_string(str(template))
            rendered = template_obj.render(**vars_dict)

            try:
                return json.loads(rendered)
            except json.JSONDecodeError:
                try:
                    import ast
                    return ast.literal_eval(rendered)
                except (ValueError, SyntaxError):
                    return rendered
        except Exception as e:
            logger.error(f"Template rendering error for '{template}': {e}")
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
                next_step = self.execute_step(current_step)
                logger.debug(f"Step {current_step} completed. Next step: {next_step}")

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

    def execute_task(self, task_name: str, context: Dict = None) -> Any:
        context = context or {}

        if isinstance(task_name, dict):
            task_def = task_name
        else:
            task_def = self.find_task(task_name)
            if not task_def:
                raise ValueError(f"Task not found: {task_name}")

        if task_def.get('type') == 'loop' or task_def.get('loop'):
            loop_data = self.render_template(task_def.get('in'), context)
            iterator_name = task_def.get('iterator', 'item')
            if not isinstance(iterator_name, str):
                iterator_name = 'item'

            if not isinstance(loop_data, list):
                if isinstance(loop_data, dict):
                    loop_data = [loop_data]
                else:
                    raise ValueError(f"Loop data must be a list or dict, got: {type(loop_data)}")

            results = []
            for item in loop_data:
                iter_context = deep_merge(self.context, context or {})
                iter_context[iterator_name] = item
                iteration_results = {}
                for run_task in task_def.get('run', []):
                    try:
                        run_task_context = deep_merge(iter_context, iteration_results)
                        run_task_context[iterator_name] = item
                        if run_task.get('with'):
                            with_ctx = self.render_template(run_task['with'], run_task_context)
                            run_task_context = deep_merge(run_task_context, with_ctx)
                        if iterator_name not in run_task_context or run_task_context.get(iterator_name) is None:
                            run_task_context[iterator_name] = item
                        task_type = run_task.get('type', 'http')
                        if run_task.get('type') == 'python' and run_task.get('with'):
                            input_data = self.render_template(run_task['with'], run_task_context)
                            namespace = {
                                'context': run_task_context,
                                'results': self.results,
                                'logger': logger,
                                'input': input_data
                            }
                            result = execute_python_task(run_task, namespace)
                        else:
                            result = self.execute_task_instance(run_task, task_type, run_task_context)
                        iteration_results[run_task.get('task')] = result
                        iter_context[run_task.get('task')] = result
                    except Exception as e:
                        if run_task.get('on_error') == 'continue':
                            logger.warning(f"Task error (continuing): {e}")
                            continue
                        raise
                results.append(iteration_results)
            if isinstance(task_name, str):
                self.results[task_name] = results
            return results

        task_type = task_def.get('type', 'unknown')
        try:
            result = self.execute_task_instance(task_def, task_type, context)
            if isinstance(task_name, str):
                self.results[task_name] = result
            return result
        except Exception as e:
            error_result = {'status': 'error', 'error': str(e)}
            if isinstance(task_name, str):
                self.results[task_name] = error_result
            raise

    def find_task(self, task_name: str) -> Dict:
        workbook_tasks = self.playbook.get('workbook', [])
        for task in workbook_tasks:
            if task.get('task') == task_name:
                logger.debug(f"Found task '{task_name}' in workbook: {json.dumps(task, indent=2)}")
                task_def = task.copy()

                if task_def.get('in'):
                    task_def['type'] = 'loop'
                    task_def['loop'] = {
                        'iterator': task_def.get('iterator', 'item'),
                        'in': task_def.get('in')
                    }
                elif not task_def.get('type'):
                    task_def['type'] = 'http'

                logger.debug(f"Processed task definition: {json.dumps(task_def, indent=2)}")
                return task_def

        for step in self.playbook.get('workflow', []):
            if step.get('run'):
                for task in step.get('run'):
                    if task.get('task') == task_name:
                        logger.debug(f"Found task '{task_name}' in workflow: {json.dumps(task, indent=2)}")
                        return task.copy()

        logger.warning(f"Task '{task_name}' not found in workbook / workflow")
        return {}

    def execute_http_task(self, task: Dict, context: Dict = None) -> Dict:
        try:
            method = task.get('method', 'GET').upper()
            endpoint = self.render_template(task.get('endpoint', ''), context)
            params = {
                k: self.render_template(v, context)
                for k, v in task.get('params', {}).items()
            }
            payload = task.get('payload')
            if payload:
                payload = {
                    k: self.render_template(v, context)
                    for k, v in payload.items()
                }

            if self.mock_mode:
                mock_response = mock_http_response(task)
                logger.debug(f"Mock HTTP response for {endpoint}: {mock_response}")
                return mock_response

            retries = task.get('retry', 3)
            retry_delay = task.get('retry_delay', 5)

            response = None
            last_error = None

            for attempt in range(retries + 1):
                try:
                    if method == 'GET':
                        response = requests.get(endpoint, params=params)
                    elif method == 'POST':
                        response = requests.post(endpoint, json=payload, params=params)

                    response.raise_for_status()
                    response_data = response.json()

                    return {
                        'status': 'success',
                        'status_code': response.status_code,
                        'data': response_data
                    }

                except Exception as e:
                    last_error = str(e)
                    if attempt < retries:
                        time.sleep(retry_delay)
                        continue
                    break

            error_msg = f"HTTP request failed after {retries + 1} attempts. Last error: {last_error}"
            if task.get('on_error') == 'continue':
                logger.warning(error_msg)
                return {
                    'status': 'error',
                    'error': error_msg
                }
            raise Exception(error_msg)

        except Exception as e:
            if task.get('on_error') == 'continue':
                logger.warning(f"HTTP task error (continuing): {e}")
                return {
                    'status': 'error',
                    'error': str(e)
                }
            raise

    def execute_task_instance(self, task: Dict, task_type: str, context: Dict = None) -> Any:
        if task_type == 'http':
            result = self.execute_http_task(task, context)
            task_name = task.get('task')
            if task_name:
                context[task_name] = result
            return result

        elif task_type == 'python':
            if task.get('with'):
                input_data = self.render_template(task['with'], context or {})
            else:
                input_data = context or {}

            namespace = {
                'context': context,
                'results': self.results,
                'logger': logger
            }
            namespace.update({'__builtins__': __builtins__})

            try:
                exec(task.get('code', ''), namespace)
                main_func = namespace.get('main')
                if not main_func or not callable(main_func):
                    raise ValueError("Python task must define a 'main' function")

                import inspect
                sig = inspect.signature(main_func)
                filtered_input = {k: v for k, v in input_data.items() if k in sig.parameters}
                result = main_func(**filtered_input)
                task_name = task.get('task')
                if task_name and context is not None:
                    context[task_name] = result
                    if isinstance(result, dict):
                        context[task_name].update(result)

                if isinstance(result, dict) and 'status' in result and 'data' in result:
                    return result
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

        elif task_type == 'loop':
            logger.debug(f"Executing loop task with configuration: {json.dumps(task, indent=2)}")
            loop_data = self.render_template(task.get('in'), context)
            iterator_name = task.get('iterator', 'item')
            if not isinstance(iterator_name, str):
                iterator_name = 'item'

            if not isinstance(loop_data, list):
                if isinstance(loop_data, dict):
                    loop_data = [loop_data]
                else:
                    raise ValueError(f"Loop data is {type(loop_data)} must be a list or dict")

            results = []
            run_tasks = task.get('run', [])
            for item in loop_data:
                iteration_context = {
                    **self.context,
                    str(iterator_name): item,
                    'results': {},
                    **(context or {})
                }

                iteration_results = {}
                for run_task in run_tasks:
                    try:
                        when_condition = run_task.get('when')
                        if when_condition:
                            should_execute = self.render_template(
                                when_condition,
                                {**iteration_context, **iteration_results}
                            )
                            if not should_execute:
                                continue
                        task_type = run_task.get('type', 'http')
                        run_task_context = {**iteration_context, **iteration_results}
                        run_task_context[str(iterator_name)] = item
                        if run_task.get('with'):
                            with_ctx = self.render_template(run_task['with'], run_task_context)
                            run_task_context = deep_merge(run_task_context, with_ctx)
                        if str(iterator_name) not in run_task_context or run_task_context.get(iterator_name) is None:
                            run_task_context[iterator_name] = item
                        if run_task.get('type') == 'python' and run_task.get('with'):
                            input_data = self.render_template(run_task['with'], run_task_context)
                            namespace = {
                                'context': run_task_context,
                                'results': self.results,
                                'logger': logger,
                                'input': input_data
                            }
                            result = execute_python_task(run_task, namespace)
                        else:
                            result = self.execute_task_instance(
                                run_task,
                                task_type,
                                run_task_context
                            )
                        task_name = run_task.get('task')
                        if task_name:
                            iteration_results[task_name] = result
                            iteration_context[task_name] = result
                            iteration_context['results'][task_name] = result

                    except Exception as e:
                        logger.error(f"Error in loop task: {e}")
                        if run_task.get('on_error') != 'continue':
                            raise
                        task_name = run_task.get('task')
                        if task_name:
                            iteration_results[task_name] = {
                                'status': 'error',
                                'error': str(e)
                            }

                results.append(iteration_results)

            return results
        else:
            raise ValueError(f"Unsupported task type: {task_type}")

    def execute_step(self, step_name: str) -> str:
        if not hasattr(self, 'jinja2_filters'):
            self.jinja2_filters = {}
        if not hasattr(self, 'jinja2_tests'):
            self.jinja2_tests = {
                'sequence': lambda x: isinstance(x, (list, tuple)),
            }

        step = next((s for s in self.playbook.get('workflow', []) if s.get('step') == step_name), None)

        if not step:
            logger.error(f"Step not found: {step_name}")
            raise ValueError(f"Step not found: {step_name}")

        logger.info(f"Executing step: {step_name}")
        logger.debug(f"Step configuration: {json.dumps(step, indent=2)}")

        try:
            step_context = {}
            if 'with' in step:
                with_ctx = self.render_template(step.get('with'), self.context)
                step_context = deep_merge(self.context, with_ctx)
            else:
                step_context = dict(self.context)

            if 'input' in step:
                step_context['input'] = self.render_template(step.get('input'), step_context)

            if step.get('run'):
                step_results = {}
                for task in step.get('run', []):
                    task_name = task.get('task')
                    try:
                        task_context = deep_merge(step_context, {})
                        if task.get('with'):
                            with_ctx = self.render_template(task['with'], task_context)
                            task_context = deep_merge(task_context, with_ctx)

                        result = self.execute_task(task_name, context=task_context)
                        step_results[task_name] = result
                        self.context[task_name] = result

                        if task.get('output'):
                            self.context[task.get('output')] = result
                    except Exception as e:
                        if task.get('on_error') == 'continue':
                            logger.warning(f"Task {task_name} failed but continuing: {e}")
                            continue
                        raise
                self.context['output'] = step_results

            # logger.debug(f"Context after step execution: {json.dumps(self.context, indent=2)}")
            if not step.get('next'):
                return 'end'

            for transition in step.get('next', []):
                if transition.get('when'):
                    try:
                        env = jinja2.Environment(undefined=jinja2.StrictUndefined)
                        env.filters.update(self.jinja2_filters)
                        env.tests.update(self.jinja2_tests)
                        template = env.from_string(transition.get('when'))
                        result = template.render(self.context)
                        logger.debug(f"Evaluating condition: {transition.get('when')} -> {result}")
                        if result.lower() in ('true', '1', 'yes'):
                            if 'then' in transition and transition.get('then'):
                                next_step = transition.get('then')[0]
                                if isinstance(next_step, dict):
                                    if next_step.get('with'):
                                        with_params = self.render_template(next_step.get('with'), self.context)
                                        self.context = deep_merge(self.context, with_params)
                                    return next_step.get('step', 'end')
                                return next_step
                    except jinja2.exceptions.UndefinedError as e:
                        logger.debug(f"Variable undefined in condition: {e}")
                        continue
                    except Exception as e:
                        logger.error(f"Error evaluating condition '{transition.get('when')}': {e}")
                        raise
                elif transition.get('else'):
                    next_step = transition.get('else')[0]
                    if isinstance(next_step, dict):
                        if next_step.get('with'):
                            with_params = self.render_template(next_step.get('with'), self.context)
                            self.context = deep_merge(self.context, with_params)
                        return next_step.get('step', 'end')
                    return next_step

            return 'end'

        except Exception as e:
            logger.error(f"Error in step {step_name}: {e}")
            self.context['error'] = str(e)
            self.context['state'] = 'error'
            return 'error_handler'


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description='Execute NoETL playbook')
    parser.add_argument('-m', '--mock', action='store_true', help='Mockup mode')
    parser.add_argument('-f', '--file', required=True, help='Playbook file path')
    parser.add_argument('-v', '--verbose', action='store_true', help='Verbose logging')
    parser.add_argument('-d', '--dry-run', action='store_true', help='Dryrun mode')
    parser.add_argument('-o', '--output', choices=['json', 'yaml', 'plain'], default='plain', help='Output format')
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
        return json.dumps(results, indent=2)
    elif format_type == 'yaml':
        return yaml.dump(results, default_flow_style=False)
    else:
        return str(results)


def main():
    try:
        args = parse_arguments()
        validate_playbook_file(args.file)
        agent = PlaybookAgent(args.file, mock=args.mock)

        if args.dry_run:
            logger.info("Dry run - playbook structure is valid")
            return 0

        logger.info(f"Executing playbook: {args.file}")
        results = agent.execute()
        logger.debug(f"Format: {json.dumps(args.output, indent=2)}")
        logger.debug(f"Result: {format_output(results, args.output)}")
        return 0

    except Exception as e:
        logger.error(f"Error: {e}")
        if args.verbose:
            logger.exception("Detailed error information:")
        return 1


if __name__ == '__main__':
    sys.exit(main())

