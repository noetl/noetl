#!/usr/bin/env python3
"""
NoETL agent with DuckDB persistence for tracking execution flow, and AI/ML control of execution through data analysis.
"""

import yaml
import json
import logging
import os
import uuid
import datetime
from typing import Dict, List, Any, Optional, Tuple
from jinja2 import Environment, StrictUndefined, BaseLoader
import duckdb
import polars as pl
import httpx

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def render_template(env: Environment, template: Any, context: Dict, rules: Dict = None) -> Any:

    if isinstance(template, str) and '{{' in template and '}}' in template:
        logger.debug(f"RENDER_TEMPLATE: Rendering template: {template}")
        logger.debug(f"RENDER_TEMPLATE: Context keys: {list(context.keys())}")
        if 'city' in context:
            logger.debug(f"RENDER_TEMPLATE: City value: {context['city']}, Type: {type(context['city'])}")
        if rules:
            logger.debug(f"RENDER_TEMPLATE: Rules: {rules}")

    render_ctx = dict(context)
    if rules:
        render_ctx.update(rules)

    if isinstance(template, str) and '{{' in template and '}}' in template:
        try:
            expr = template.strip()
            if expr == '{{}}':
                return ""
            if expr.startswith('{{') and expr.endswith('}}'):
                var_path = expr[2:-2].strip()
                if not any(op in var_path for op in ['==', '!=', '<', '>', '+', '-', '*', '/', '|', ' if ', ' else ']):
                    if '.' not in var_path and var_path.strip() in render_ctx:
                        return render_ctx.get(var_path.strip())
                    elif '.' in var_path:
                        parts = var_path.split('.')
                        value = render_ctx
                        valid_path = True
                        for part in parts:
                            part = part.strip()
                            if isinstance(value, dict) and part in value:
                                value = value.get(part)
                            else:
                                valid_path = False
                                break
                        if valid_path:
                            return value

            template_obj = env.from_string(template)
            try:
                rendered = template_obj.render(**render_ctx)
            except Exception as e:
                logger.error(f"Template rendering error: {e}, template: {template}")
                return None

            if (rendered.startswith('[') and rendered.endswith(']')) or \
                    (rendered.startswith('{') and rendered.endswith('}')):
                try:
                    return json.loads(rendered)
                except json.JSONDecodeError:
                    pass

            if rendered.strip() == "":
                return ""

            return rendered
        except Exception as e:
            logger.error(f"Template rendering error: {e}, template: {template}")
            return ""
    elif isinstance(template, dict):
        if not template:
            return template
        return {k: render_template(env, v, render_ctx, rules) for k, v in template.items()}
    elif isinstance(template, list):
        return [render_template(env, item, render_ctx, rules) for item in template]
    return template


class NoETLAgent:
    """NoETLAgent to run playbooks with persistent execution tracking"""

    def __init__(self, playbook_path: str, mock_mode: bool = True, db_path: str = None):
        self.playbook_path = playbook_path
        self.mock_mode = mock_mode
        self.execution_id = str(uuid.uuid4())
        self.playbook = self.load_playbook()
        self.context = {}
        self.context.update(self.playbook.get('workload', {}))
        self.jinja_env = Environment(loader=BaseLoader(), undefined=StrictUndefined)
        self.jinja_env.filters['to_json'] = lambda obj: json.dumps(obj)
        self.jinja_env.globals['now'] = lambda: datetime.datetime.now().isoformat()
        self.next_step_with = None

        if db_path is None or db_path == ":memory:":
            db_path = os.path.join(os.path.dirname(__file__), "agent007.duckdb")
            logger.info(f"Using DuckDB file: {db_path}")
        else:
            logger.info(f"Using DuckDB file: {db_path}")

        self.db_path = db_path
        self.conn = duckdb.connect(db_path)
        self.init_database()
        self.parse_playbook()

    def init_database(self):
        # Context table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS context (
                execution_id VARCHAR,
                timestamp TIMESTAMP,
                key VARCHAR,
                value VARCHAR,
                PRIMARY KEY (execution_id, key)
            )
        """)

        # Task results table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS task_result (
                execution_id VARCHAR,
                task_id VARCHAR,
                task_name VARCHAR,
                task_type VARCHAR,
                parent_id VARCHAR,
                timestamp TIMESTAMP,
                status VARCHAR,
                data VARCHAR,
                error VARCHAR,
                PRIMARY KEY (execution_id, task_id)
            )
        """)

        # Step results table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS step_result (
                execution_id VARCHAR,
                step_id VARCHAR,
                step_name VARCHAR,
                parent_id VARCHAR,
                timestamp TIMESTAMP,
                status VARCHAR,
                data VARCHAR,
                error VARCHAR,
                PRIMARY KEY (execution_id, step_id)
            )
        """)

        # Loop state table
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS loop_state (
                execution_id VARCHAR,
                loop_id VARCHAR,
                loop_name VARCHAR,
                parent_id VARCHAR,
                iterator VARCHAR,
                items VARCHAR,
                current_index INTEGER,
                current_item VARCHAR,
                results VARCHAR,
                timestamp TIMESTAMP,
                status VARCHAR,
                PRIMARY KEY (execution_id, loop_id)
            )
        """)

        # Event log table for event-base
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS event_log (
                execution_id VARCHAR,
                event_id VARCHAR,
                parent_event_id VARCHAR,
                timestamp TIMESTAMP,
                event_type VARCHAR,
                node_id VARCHAR,
                node_name VARCHAR,
                node_type VARCHAR,
                status VARCHAR,
                duration DOUBLE,
                input_context VARCHAR,
                output_result VARCHAR,
                metadata VARCHAR,
                PRIMARY KEY (execution_id, event_id)
            )
        """)

        # Workflow table (steps from playbook)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS workflow (
                execution_id VARCHAR,
                step_id VARCHAR,
                step_name VARCHAR,
                step_type VARCHAR,
                description VARCHAR,
                raw_config VARCHAR,
                PRIMARY KEY (execution_id, step_id)
            )
        """)

        # Workbook table (tasks from playbook)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS workbook (
                execution_id VARCHAR,
                task_id VARCHAR,
                task_name VARCHAR,
                task_type VARCHAR,
                raw_config VARCHAR,
                PRIMARY KEY (execution_id, task_id)
            )
        """)

        # transition table for workflow control flow
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS transition (
                execution_id VARCHAR,
                from_step VARCHAR,
                to_step VARCHAR,
                condition VARCHAR,
                with_params VARCHAR,
                PRIMARY KEY (execution_id, from_step, to_step, condition)
            )
        """)

    def load_playbook(self) -> Dict:
        if not os.path.exists(self.playbook_path):
            raise FileNotFoundError(f"Playbook not found: {self.playbook_path}")

        with open(self.playbook_path, 'r') as f:
            return yaml.safe_load(f)

    def parse_playbook(self):
        for step in self.playbook.get('workflow', []):
            step_id = str(uuid.uuid4())
            step_name = step.get('step')
            step_type = 'standard'
            if 'loop' in step:
                step_type = 'loop'
            elif 'end_loop' in step:
                step_type = 'end_loop'
            elif 'call' in step:
                step_type = 'call'

            self.conn.execute("""
                              INSERT INTO workflow
                              VALUES (?, ?, ?, ?, ?, ?)
                              """, (
                                  self.execution_id,
                                  step_id,
                                  step_name,
                                  step_type,
                                  step.get('desc', ''),
                                  json.dumps(step)
                              ))

            # Load transition
            next_steps = step.get('next', [])
            if not isinstance(next_steps, list):
                next_steps = [next_steps]

            for next_step in next_steps:
                if isinstance(next_step, dict):
                    if 'when' in next_step and 'then' in next_step:
                        condition = next_step.get('when')
                        then_steps = next_step.get('then', [])
                        if not isinstance(then_steps, list):
                            then_steps = [then_steps]

                        for then_step in then_steps:
                            if isinstance(then_step, dict):
                                to_step = then_step.get('step')
                                with_params = json.dumps(then_step.get('with', {}))
                            else:
                                to_step = then_step
                                with_params = '{}'

                            self.conn.execute("""
                                              INSERT INTO transition
                                              VALUES (?, ?, ?, ?, ?)
                                              """, (
                                                  self.execution_id,
                                                  step_name,
                                                  to_step,
                                                  condition,
                                                  with_params
                                              ))
                    elif 'else' in next_step:
                        else_steps = next_step.get('else', [])
                        if not isinstance(else_steps, list):
                            else_steps = [else_steps]

                        for else_step in else_steps:
                            if isinstance(else_step, dict):
                                to_step = else_step.get('step')
                                with_params = json.dumps(else_step.get('with', {}))
                            else:
                                to_step = else_step
                                with_params = '{}'

                            self.conn.execute("""
                                              INSERT INTO transition
                                              VALUES (?, ?, ?, ?, ?)
                                              """, (
                                                  self.execution_id,
                                                  step_name,
                                                  to_step,
                                                  'else',
                                                  with_params
                                              ))
                elif isinstance(next_step, str):
                    self.conn.execute("""
                                      INSERT INTO transition
                                      VALUES (?, ?, ?, ?, ?)
                                      """, (
                                          self.execution_id,
                                          step_name,
                                          next_step,
                                          '',
                                          '{}'
                                      ))
                else:
                    to_step = next_step.get('step')
                    with_params = json.dumps(next_step.get('with', {}))
                    self.conn.execute("""
                                      INSERT INTO transition
                                      VALUES (?, ?, ?, ?, ?)
                                      """, (
                                          self.execution_id,
                                          step_name,
                                          to_step,
                                          '',
                                          with_params
                                      ))

        for task in self.playbook.get('workbook', []):
            task_id = str(uuid.uuid4())
            task_name = task.get('task')
            task_type = task.get('type', 'http')

            self.conn.execute("""
                              INSERT INTO workbook
                              VALUES (?, ?, ?, ?, ?)
                              """, (
                                  self.execution_id,
                                  task_id,
                                  task_name,
                                  task_type,
                                  json.dumps(task)
                              ))

    def update_context(self, key: str, value: Any):
        self.context[key] = value

        serialized_value = json.dumps(value) if not isinstance(value, (str, int, float, bool)) else str(value)

        self.conn.execute("""
            INSERT OR REPLACE INTO context (execution_id, timestamp, key, value)
            VALUES (?, ?, ?, ?)
        """, (self.execution_id, datetime.datetime.now(), key, serialized_value))

    def get_context(self, include_locals: Dict = None) -> Dict:
        if include_locals:
            return {**self.context, **include_locals}
        return self.context

    def log_event(self, event_type: str, node_id: str, node_name: str, node_type: str,
                  status: str, duration: float, input_context: Dict, output_result: Any,
                  metadata: Dict = None, parent_event_id: str = None):
        event_id = str(uuid.uuid4())

        input_context_serial = json.dumps({k: v for k, v in input_context.items() if not k.startswith('_')})
        output_result_serial = json.dumps(output_result) if output_result is not None else None
        metadata_serial = json.dumps(metadata) if metadata is not None else None

        self.conn.execute("""
                          INSERT INTO event_log
                          (execution_id, event_id, parent_event_id, timestamp, event_type,
                           node_id, node_name, node_type, status, duration,
                           input_context, output_result, metadata)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                          """, (
                              self.execution_id, event_id, parent_event_id, datetime.datetime.now(), event_type,
                              node_id, node_name, node_type, status, duration,
                              input_context_serial, output_result_serial, metadata_serial
                          ))

        return event_id

    def save_task_result(self, task_id: str, task_name: str, task_type: str,
                         parent_id: str, status: str, data: Any = None, error: str = None):
        serialized_data = json.dumps(data) if data is not None else None

        self.conn.execute("""
                          INSERT INTO task_result
                          (execution_id, task_id, task_name, task_type, parent_id, timestamp, status, data, error)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                          """, (
                              self.execution_id, task_id, task_name, task_type, parent_id,
                              datetime.datetime.now(), status, serialized_data, error
                          ))

        return task_id

    def save_step_result(self, step_id: str, step_name: str, parent_id: str,
                         status: str, data: Any = None, error: str = None):
        serialized_data = json.dumps(data) if data is not None else None

        self.conn.execute("""
                          INSERT INTO step_result
                          (execution_id, step_id, step_name, parent_id, timestamp, status, data, error)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                          """, (
                              self.execution_id, step_id, step_name, parent_id,
                              datetime.datetime.now(), status, serialized_data, error
                          ))

        return step_id

    def create_loop_state(self, loop_name: str, iterator: str, items: List[Any], parent_id: str = None):
        loop_id = str(uuid.uuid4())
        serialized_items = json.dumps(items)

        self.conn.execute("""
                          INSERT INTO loop_state
                          (execution_id, loop_id, loop_name, parent_id, iterator, items, current_index, current_item,
                           results, timestamp, status)
                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                          """, (
                              self.execution_id, loop_id, loop_name, parent_id, iterator,
                              serialized_items, -1, None, json.dumps([]), datetime.datetime.now(), 'created'
                          ))

        return loop_id

    def update_loop_state(self, loop_id: str, current_index: int, current_item: Any, status: str):
        serialized_item = json.dumps(current_item)

        self.conn.execute("""
                          UPDATE loop_state
                          SET current_index = ?,
                              current_item  = ?,
                              timestamp     = ?,
                              status        = ?
                          WHERE execution_id = ?
                            AND loop_id = ?
                          """, (
                              current_index, serialized_item, datetime.datetime.now(), status,
                              self.execution_id, loop_id
                          ))

    def add_loop_result(self, loop_id: str, result: Any):
        result_row = self.conn.execute("""
                                       SELECT results
                                       FROM loop_state
                                       WHERE execution_id = ?
                                         AND loop_id = ?
                                       """, (self.execution_id, loop_id)).fetchone()

        if result_row:
            current_results = json.loads(result_row[0])
            current_results.append(result)
            self.conn.execute("""
                              UPDATE loop_state
                              SET results   = ?,
                                  timestamp = ?
                              WHERE execution_id = ?
                                AND loop_id = ?
                              """, (
                                  json.dumps(current_results), datetime.datetime.now(),
                                  self.execution_id, loop_id
                              ))

    def get_loop_results(self, loop_id: str) -> List[Any]:
        result_row = self.conn.execute("""
                                       SELECT results
                                       FROM loop_state
                                       WHERE execution_id = ?
                                         AND loop_id = ?
                                       """, (self.execution_id, loop_id)).fetchone()

        if result_row:
            return json.loads(result_row[0])
        return []

    def get_active_loops(self) -> List[Dict]:
        rows = self.conn.execute("""
                                 SELECT loop_id, loop_name, iterator, items, current_index, current_item, results
                                 FROM loop_state
                                 WHERE execution_id = ?
                                   AND status != 'completed'
                                 ORDER BY timestamp ASC
                                 """, (self.execution_id,)).fetchall()

        loops = []
        for row in rows:
            loops.append({
                'id': row[0],
                'name': row[1],
                'iterator': row[2],
                'items': json.loads(row[3]),
                'index': row[4],
                'current_item': json.loads(row[5]) if row[5] else None,
                'results': json.loads(row[6])
            })

        return loops

    def find_loop(self, loop_name: str, include_completed: bool = False) -> Optional[Dict]:
        """Find loop
        Args:
            loop_name: Name of the loop
            include_completed: includes loops that are marked as completed, if true
        """
        logger.debug(f"Finding loop by name: {loop_name}, include_completed: {include_completed}")

        # for debug anly
        all_loops = self.conn.execute("""
                                     SELECT loop_id, loop_name, status
                                     FROM loop_state
                                     WHERE execution_id = ?
                                     """, (self.execution_id,)).fetchall()
        logger.debug(f"All loops in database: {all_loops}")

        if include_completed:
            query = """
                   SELECT loop_id, iterator, items, current_index, current_item, results
                   FROM loop_state
                   WHERE execution_id = ?
                     AND loop_name = ?
                   ORDER BY timestamp DESC
                       LIMIT 1
                   """
        else:
            query = """
                   SELECT loop_id, iterator, items, current_index, current_item, results
                   FROM loop_state
                   WHERE execution_id = ?
                     AND loop_name = ?
                     AND status != 'completed'
                   ORDER BY timestamp DESC
                       LIMIT 1
                   """

        row = self.conn.execute(query, (self.execution_id, loop_name)).fetchone()

        if row:
            return {
                'id': row[0],
                'iterator': row[1],
                'items': json.loads(row[2]),
                'index': row[3],
                'current_item': json.loads(row[4]) if row[4] else None,
                'results': json.loads(row[5])
            }
        return None

    def complete_loop(self, loop_id: str):
        #Mark loop completed
        self.conn.execute("""
                          UPDATE loop_state
                          SET status    = 'completed',
                              timestamp = ?
                          WHERE execution_id = ?
                            AND loop_id = ?
                          """, (datetime.datetime.now(), self.execution_id, loop_id))

    def execute_http_task(self, task_config: Dict, context: Dict, parent_id: str = None) -> Dict:
        task_id = str(uuid.uuid4())
        task_name = task_config.get('task', 'http_task')
        start_time = datetime.datetime.now()

        try:
            method = task_config.get('method', 'GET').upper()
            endpoint = render_template(self.jinja_env, task_config.get('endpoint', ''), context)
            params = render_template(self.jinja_env, task_config.get('params', {}), context)
            payload = render_template(self.jinja_env, task_config.get('payload', {}), context)

            logger.info(f"HTTP {method} request to {endpoint}")

            event_id = self.log_event(
                'task_start', task_id, task_name, 'http',
                'in_progress', 0, context, None,
                {'method': method, 'endpoint': endpoint}, parent_id
            )

            if self.mock_mode:
                # Mock HTTP response
                response_data = {"data": "mocked_response", "status": "success"}

                if 'forecast' in endpoint:
                    temp_data = [20, 22, 25, 28, 30, 26, 24]
                    max_temp = max(temp_data)
                    temp_threshold = context.get('temperature_threshold', 25)
                    alert = max_temp > temp_threshold

                    response_data = {
                        "data": {
                            "hourly": {
                                "temperature_2m": temp_data,
                                "precipitation_probability": [0, 10, 20, 30, 20, 10, 0],
                                "windspeed_10m": [10, 12, 15, 18, 22, 19, 14]
                            }
                        },
                        "alert": alert,
                        "max_temp": max_temp
                    }
                elif 'districts' in endpoint:
                    response_data = {
                        "data": [
                            {"name": "Downtown", "population": 50000},
                            {"name": "North", "population": 25000},
                            {"name": "East", "population": 30000},
                            {"name": "Mordor", "population": 666}
                        ]
                    }

                self.save_task_result(
                    task_id, task_name, 'http', parent_id,
                    'success', response_data, None
                )
                end_time = datetime.datetime.now()
                duration = (end_time - start_time).total_seconds()

                self.log_event(
                    'task_complete', task_id, task_name, 'http',
                    'success', duration, context, response_data,
                    {'method': method, 'endpoint': endpoint}, event_id
                )

                return {
                    'id': task_id,
                    'status': 'success',
                    'data': response_data
                }
            else:
                headers = render_template(self.jinja_env, task_config.get('headers', {}), context)
                timeout = task_config.get('timeout', 30)

                try:
                    with httpx.Client(timeout=timeout) as client:
                        if method == 'GET':
                            response = client.get(endpoint, params=params, headers=headers)
                        elif method == 'POST':
                            response = client.post(endpoint, json=payload, params=params, headers=headers)
                        elif method == 'PUT':
                            response = client.put(endpoint, json=payload, params=params, headers=headers)
                        elif method == 'DELETE':
                            response = client.delete(endpoint, params=params, headers=headers)
                        elif method == 'PATCH':
                            response = client.patch(endpoint, json=payload, params=params, headers=headers)
                        else:
                            raise ValueError(f"Unsupported HTTP method: {method}")
                        response.raise_for_status() 
                        try:
                            response_data = response.json()
                        except ValueError:
                            response_data = {"text": response.text}

                        response_data = {
                            "data": response_data,
                            "status_code": response.status_code,
                            "headers": dict(response.headers)
                        }

                        self.save_task_result(
                            task_id, task_name, 'http', parent_id,
                            'success', response_data, None
                        )

                        end_time = datetime.datetime.now()
                        duration = (end_time - start_time).total_seconds()

                        self.log_event(
                            'task_complete', task_id, task_name, 'http',
                            'success', duration, context, response_data,
                            {'method': method, 'endpoint': endpoint}, event_id
                        )

                        return {
                            'id': task_id,
                            'status': 'success',
                            'data': response_data
                        }

                except httpx.HTTPStatusError as e:
                    error_msg = f"HTTP error: {e.response.status_code} - {e.response.text}"
                    raise Exception(error_msg)
                except httpx.RequestError as e:
                    error_msg = f"Request error: {str(e)}"
                    raise Exception(error_msg)

        except Exception as e:
            error_msg = str(e)
            logger.error(f"HTTP task error: {error_msg}")
            self.save_task_result(
                task_id, task_name, 'http', parent_id,
                'error', None, error_msg
            )

            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            self.log_event(
                'task_error', task_id, task_name, 'http',
                'error', duration, context, None,
                {'error': error_msg}, parent_id
            )

            return {
                'id': task_id,
                'status': 'error',
                'error': error_msg
            }

    def execute_python_task(self, task_config: Dict, context: Dict, parent_id: str = None) -> Dict:
        task_id = str(uuid.uuid4())
        task_name = task_config.get('task', 'python_task')
        start_time = datetime.datetime.now()

        try:
            code = task_config.get('code', '')
            task_with = render_template(self.jinja_env, task_config.get('with', {}), context)

            # Log task start event
            event_id = self.log_event(
                'task_start', task_id, task_name, 'python',
                'in_progress', 0, context, None,
                {'with_params': task_with}, parent_id
            )

            exec_globals = {
                '__builtins__': __builtins__,
                'logger': logger
            }
            exec_locals = {}
            exec(code, exec_globals, exec_locals)

            if 'main' in exec_locals:
                result_data = exec_locals['main'](**task_with)
                self.save_task_result(
                    task_id, task_name, 'python', parent_id,
                    'success', result_data, None
                )
                end_time = datetime.datetime.now()
                duration = (end_time - start_time).total_seconds()
                self.log_event(
                    'task_complete', task_id, task_name, 'python',
                    'success', duration, context, result_data,
                    {'with_params': task_with}, event_id
                )

                return {
                    'id': task_id,
                    'status': 'success',
                    'data': result_data
                }
            else:
                error_msg = "No main function defined in Python task"
                self.save_task_result(
                    task_id, task_name, 'python', parent_id,
                    'error', None, error_msg
                )
                end_time = datetime.datetime.now()
                duration = (end_time - start_time).total_seconds()
                self.log_event(
                    'task_error', task_id, task_name, 'python',
                    'error', duration, context, None,
                    {'error': error_msg}, event_id
                )

                return {
                    'id': task_id,
                    'status': 'error',
                    'error': error_msg
                }

        except Exception as e:
            error_msg = str(e)
            logger.error(f"Python task execution error: {error_msg}", exc_info=True)
            self.save_task_result(
                task_id, task_name, 'python', parent_id,
                'error', None, error_msg
            )
            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()
            self.log_event(
                'task_error', task_id, task_name, 'python',
                'error', duration, context, None,
                {'error': error_msg}, parent_id
            )

            return {
                'id': task_id,
                'status': 'error',
                'error': error_msg
            }

    def execute_task(self, task_name: str, context: Dict, parent_id: str = None) -> Dict:
        task_config = self.find_task(task_name)
        if not task_config:
            task_id = str(uuid.uuid4())
            error_msg = f"Task not found: {task_name}"
            self.save_task_result(
                task_id, task_name, 'unknown', parent_id,
                'error', None, error_msg
            )
            self.log_event(
                'task_error', task_id, task_name, 'unknown',
                'error', 0, context, None,
                {'error': error_msg}, parent_id
            )

            return {
                'id': task_id,
                'status': 'error',
                'error': error_msg
            }

        task_type = task_config.get('type', 'http')
        task_id = str(uuid.uuid4())
        start_time = datetime.datetime.now()
        event_id = self.log_event(
            'task_execute', task_id, task_name, f'task.{task_type}',
            'in_progress', 0, context, None,
            {'task_type': task_type}, parent_id
        )
        task_with = {} # TODO to debug
        if 'with' in task_config:
            task_with = render_template(self.jinja_env, task_config.get('with'), context)
            context.update(task_with)

        if task_type == 'http':
            result = self.execute_http_task(task_config, context, event_id)
        elif task_type == 'python':
            result = self.execute_python_task(task_config, context, event_id)
        elif task_type == 'loop':
            result = self.execute_loop_task(task_config, context, event_id)
        else:
            error_msg = f"Unsupported task type: {task_type}"
            self.save_task_result(
                task_id, task_name, task_type, parent_id,
                'error', None, error_msg
            )
            self.log_event(
                'task_error', task_id, task_name, f'task.{task_type}',
                'error', 0, context, None,
                {'error': error_msg}, event_id
            )

            result = {
                'id': task_id,
                'status': 'error',
                'error': error_msg
            }

        if 'return' in task_config and result['status'] == 'success':
            transformed_result = render_template(self.jinja_env, task_config['return'], {
                **context,
                'result': result['data'],
                'status': result['status']
            })

            self.conn.execute("""
                              UPDATE task_result
                              SET data = ?
                              WHERE execution_id = ?
                                AND task_id = ?
                              """, (json.dumps(transformed_result), self.execution_id, result['id']))

            result['data'] = transformed_result

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        self.log_event(
            'task_complete', task_id, task_name, f'task.{task_type}',
            result['status'], duration, context, result.get('data'),
            {'task_type': task_type}, event_id
        )

        return result

    def execute_loop_task(self, task_config: Dict, context: Dict, parent_id: str = None) -> Dict:
        # TODO this is deprecated and should not be used for nested task execution.
        # TODO loops handled at the step level only now - Kadyapam - don't change this logic.
        error_msg = "Nested loop task execution is not supported. Use step-level loops only."
        logger.error(error_msg)
        return {
            'id': str(uuid.uuid4()),
            'status': 'error',
            'error': error_msg
        }

    def execute_step(self, step_name: str, step_with: Dict = None) -> Dict:
        step_id = str(uuid.uuid4())
        start_time = datetime.datetime.now()

        step_config = self.find_step(step_name)
        if not step_config:
            error_msg = f"Step not found: {step_name}"
            self.save_step_result(
                step_id, step_name, None,
                'error', None, error_msg
            )
            self.log_event(
                'step_error', step_id, step_name, 'step',
                'error', 0, self.get_context(), None,
                {'error': error_msg}, None
            )

            return {
                'id': step_id,
                'status': 'error',
                'error': error_msg
            }

        logger.info(f"Executing step: {step_name}")
        logger.debug(f"EXECUTE_STEP: step_name={step_name}, step_with={step_with}")
        logger.debug(f"EXECUTE_STEP: context before update: {self.context}")
        step_context = self.get_context()
        if step_with:
            rendered_with = render_template(self.jinja_env, step_with, step_context)
            logger.debug(f"EXECUTE_STEP: rendered_with={rendered_with}")
            if rendered_with:
                step_context.update(rendered_with)
                for key, value in rendered_with.items():
                    self.update_context(key, value)

        logger.debug(f"EXECUTE_STEP: context after update: {step_context}")
        step_event = self.log_event(
            'step_start', step_id, step_name, 'step',
            'in_progress', 0, step_context, None,
            {'step_type': 'standard'}, None
        )
        if 'end_loop' in step_config:
            result = self.end_loop_step(step_config, step_context, step_id)
        elif 'loop' in step_config:
            result = self.execute_loop_step(step_config, step_context, step_id)
        elif 'call' in step_config:
            call_config = step_config['call']
            task_name = call_config.get('task')
            task_with = render_template(self.jinja_env, call_config.get('with', {}), step_context)
            task_context = {**step_context, **task_with}
            result = self.execute_task(task_name, task_context, step_event)
            self.update_context(task_name, result.get('data'))
            self.update_context(task_name + '.result', result.get('data'))
            self.update_context(task_name + '.status', result.get('status'))
            self.update_context('result', result.get('data'))
        else:
            self.save_step_result(
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
        self.log_event(
            'step_complete', step_id, step_name, 'step',
            result['status'], duration, step_context, result.get('data'),
            {'step_type': 'standard'}, step_event
        )
        return result

    def end_loop_step(self, step_config: Dict, context: Dict, step_id: str) -> Dict:
        """end_loop step with result aggregation"""
        start_time = datetime.datetime.now()
        loop_name = step_config.get('end_loop')
        if not loop_name:
            error_msg = "Missing loop name in end_loop step"
            self.save_step_result(
                step_id, step_config.get('step', 'end_loop'), None,
                'error', None, error_msg
            )
            self.log_event(
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
        end_loop_event = self.log_event(
            'end_loop_start', step_id, step_config.get('step', 'end_loop'), 'step.end_loop',
            'in_progress', 0, context, None,
            {'loop_name': loop_name}, None
        )
        loop_info = self.find_loop(loop_name, include_completed=True)
        if not loop_info:
            error_msg = f"Loop context not found: {loop_name}"
            self.save_step_result(
                step_id, step_config.get('step', 'end_loop'), None,
                'error', None, error_msg
            )
            self.log_event(
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
        self.update_context(loop_results_var, loop_results)

        result_config = step_config.get('result', {})
        aggregated_results = {}

        for key, template in result_config.items():
            aggregated_value = render_template(self.jinja_env, template, context)
            aggregated_results[key] = aggregated_value
            self.update_context(key, aggregated_value)
        self.complete_loop(loop_info.get('id'))
        self.save_step_result(
            step_id, step_config.get('step', 'end_loop'), loop_info.get('id'),
            'success', aggregated_results, None
        )

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        self.log_event(
            'end_loop_complete', step_id, step_config.get('step', 'end_loop'), 'step.end_loop',
            'success', duration, context, aggregated_results,
            {'loop_name': loop_name}, end_loop_event
        )

        return {
            'id': step_id,
            'status': 'success',
            'data': aggregated_results
        }

    def execute_loop_step(self, step_config: Dict, context: Dict, step_id: str) -> Dict:
        start_time = datetime.datetime.now()
        loop_config = step_config.get('loop')
        if not loop_config:
            error_msg = "Missing loop configuration"
            self.save_step_result(
                step_id, step_config.get('step', 'loop'), None,
                'error', None, error_msg
            )
            self.log_event(
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
        items = render_template(self.jinja_env, loop_config.get('in', []), context)
        filter_expr = loop_config.get('filter')
        if isinstance(items, str):
            try:
                items = json.loads(items)
            except Exception:
                items = [items]
        if not isinstance(items, list):
            error_msg = f"Loop items must be a list, got: {type(items)}"
            self.save_step_result(
                step_id, step_config.get('step', 'loop'), None,
                'error', None, error_msg
            )
            self.log_event(
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
        logger.debug(f"EXECUTE_LOOP_STEP: iterator={iterator}, items={items}")

        loop_name = step_config.get('step', 'unnamed_loop')
        loop_id = self.create_loop_state(loop_name, iterator, items, step_id)
        loop_start_event = self.log_event(
            'loop_start', loop_id, loop_name, 'step.loop',
            'in_progress', 0, context, None,
            {'item_count': len(items), 'iterator': iterator}, None
        )

        all_results = []

        for idx, item in enumerate(items):
            iter_context = dict(context)
            iter_context[iterator] = validate_dict(item)

            self.update_loop_state(loop_id, idx, item, 'processing')
            iter_event = self.log_event(
                'loop_iteration', f"{loop_id}_{idx}", f"{loop_name}[{idx}]", 'iteration',
                'in_progress', 0, context, None,
                {'index': idx, 'item': item}, loop_start_event
            )

            skip_item = False
            if filter_expr:
                filter_result = render_template(self.jinja_env, filter_expr, iter_context)
                if isinstance(filter_result, str) and filter_result.strip() == "":
                    skip_item = False
                elif not filter_result:
                    skip_item = True

            if skip_item:
                logger.info(f"Filtering out item {idx}")
                self.log_event(
                    'loop_iteration_filtered', f"{loop_id}_{idx}", f"{loop_name}[{idx}]", 'iteration',
                    'filtered', 0, iter_context, None,
                    {'index': idx, 'filter': filter_expr}, iter_event
                )
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

                # passing the iterator variable as a dict in rules for template rendering
                rules = {iterator: iter_context[iterator]}
                logger.debug(f"EXECUTE_LOOP_STEP: Next step: {next_step_name}, next_step_with={next_step_with}, rules={rules}")

                step_with = render_template(self.jinja_env, next_step_with, iter_context, rules)
                logger.debug(f"EXECUTE_LOOP_STEP: Rendered step_with: {step_with}")

                if not next_step_name:
                    continue
                step_result = self.execute_step(next_step_name, step_with)
                iter_results[next_step_name] = step_result.get('data') if step_result.get(
                    'status') == 'success' else None

            all_results.append(iter_results)
            self.add_loop_result(loop_id, iter_results)
            self.log_event(
                'loop_iteration_complete', f"{loop_id}_{idx}", f"{loop_name}[{idx}]", 'iteration',
                'success', 0, iter_context, iter_results,
                {'index': idx, 'item': item}, iter_event
            )

        self.update_loop_state(loop_id, len(items), None, 'completed')
        self.update_context(f"{loop_name}_results", all_results)
        self.save_step_result(
            step_id, step_config.get('step', 'loop'), None,
            'success', all_results, None
        )
        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()
        self.log_event(
            'loop_complete', loop_id, loop_name, 'step.loop',
            'success', duration, context, all_results,
            {'item_count': len(items), 'processed_count': len(all_results)}, loop_start_event
        )

        # Find the corresponding end_loop step for this loop
        loop_name = step_config.get('step')
        for step in self.playbook.get('workflow', []):
            if 'end_loop' in step and step.get('end_loop') == loop_name:
                # Found the end_loop step, set it as the next step
                logger.info(f"Found end_loop step for {loop_name}: {step.get('step')}")
                self.next_step_with = step.get('with', {})
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

    def get_next_steps(self, step_config: Dict, context: Dict) -> List[Tuple[str, Dict]]:
        next_steps = step_config.get('next', [])
        if not next_steps:
            return []

        if not isinstance(next_steps, list):
            next_steps = [next_steps]

        result_steps = []

        for next_step in next_steps:
            if isinstance(next_step, dict) and 'when' in next_step:
                condition = render_template(self.jinja_env, next_step['when'], context)
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

                        result_steps.append((step_name, step_with))
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

                        result_steps.append((step_name, step_with))
            elif isinstance(next_step, dict):
                step_name = next_step.get('step')
                step_with = next_step.get('with', {})
                result_steps.append((step_name, step_with))
            else:
                result_steps.append((next_step, {}))

        return result_steps

    def get_ml_recommendation(self, current_step: str, context: Dict) -> str:
        """ML model recommendation for next step"""
        # TODO placeholder for ML integration
        # This would integrate with an ML model to predict optimal next steps
        # returns the default next step from the workflow for now
        step_config = self.find_step(current_step)
        next_steps = self.get_next_steps(step_config, context)
        if next_steps:
            return next_steps[0][0]
        return None

    def export_execution_data(self, filepath: str = None):
        """Export execution data to Parquet for ML training"""
        if not filepath:
            filepath = f"noetl_execution_{self.execution_id}.parquet"

        event_log = self.conn.execute("""
                                      SELECT *
                                      FROM event_log
                                      WHERE execution_id = ?
                                      ORDER BY timestamp
                                      """, (self.execution_id,)).pl()

        if len(event_log) > 0:
            event_log.write_parquet(filepath)
            logger.info(f"Execution data exported to {filepath}")
            return filepath

        logger.warning("No execution data to export")
        return None

    def postgres_sync(self, noetl_pgdb: str):
        """Sync agent tables to a remote NoETL Postgres database.
        The connection string should be in the format:
        'dbname=noetl user=noetl password=noetl host=localhost port=5434'
        """
        logger.info("Syncing DuckDB tables to Postgres.")
        self.conn.execute("INSTALL postgres; LOAD postgres;")
        self.conn.execute(f"ATTACH '{noetl_pgdb}' AS pg (TYPE POSTGRES);")
        tables = [
            'context', 'task_result', 'step_result', 'loop_state',
            'event_log', 'workflow', 'workbook', 'transition'
        ]
        for table in tables:
            logger.info(f"Syncing table: {table}")
            self.conn.execute(f"CREATE TABLE IF NOT EXISTS pg.public.temp_{table} AS SELECT * FROM {table} WHERE 1=0;")
            self.conn.execute(f"INSERT INTO pg.public.temp_{table} SELECT * FROM {table};")

            if table == 'context':
                self.conn.execute(f"""
                    INSERT INTO pg.public.{table} (execution_id, timestamp, key, value)
                    SELECT t.execution_id, t.timestamp, t.key, t.value 
                    FROM pg.public.temp_{table} t
                    WHERE NOT EXISTS (
                        SELECT 1 FROM pg.public.{table} 
                        WHERE execution_id = t.execution_id AND key = t.key
                    );
                """)
            elif table == 'task_result':
                self.conn.execute(f"""
                    INSERT INTO pg.public.{table} (execution_id, task_id, task_name, task_type, parent_id, timestamp, status, data, error)
                    SELECT t.execution_id, t.task_id, t.task_name, t.task_type, t.parent_id, t.timestamp, t.status, t.data, t.error 
                    FROM pg.public.temp_{table} t
                    WHERE NOT EXISTS (
                        SELECT 1 FROM pg.public.{table} 
                        WHERE execution_id = t.execution_id AND task_id = t.task_id
                    );
                """)
            elif table == 'step_result':
                self.conn.execute(f"""
                    INSERT INTO pg.public.{table} (execution_id, step_id, step_name, parent_id, timestamp, status, data, error)
                    SELECT t.execution_id, t.step_id, t.step_name, t.parent_id, t.timestamp, t.status, t.data, t.error 
                    FROM pg.public.temp_{table} t
                    WHERE NOT EXISTS (
                        SELECT 1 FROM pg.public.{table} 
                        WHERE execution_id = t.execution_id AND step_id = t.step_id
                    );
                """)
            elif table == 'loop_state':
                self.conn.execute(f"""
                    INSERT INTO pg.public.{table} (execution_id, loop_id, loop_name, parent_id, iterator, items, current_index, current_item, results, timestamp, status)
                    SELECT t.execution_id, t.loop_id, t.loop_name, t.parent_id, t.iterator, t.items, t.current_index, t.current_item, t.results, t.timestamp, t.status 
                    FROM pg.public.temp_{table} t
                    WHERE NOT EXISTS (
                        SELECT 1 FROM pg.public.{table} 
                        WHERE execution_id = t.execution_id AND loop_id = t.loop_id
                    );
                """)
            elif table == 'event_log':
                self.conn.execute(f"""
                    INSERT INTO pg.public.{table} (execution_id, event_id, parent_event_id, timestamp, event_type, node_id, node_name, node_type, status, duration, input_context, output_result, metadata)
                    SELECT t.execution_id, t.event_id, t.parent_event_id, t.timestamp, t.event_type, t.node_id, t.node_name, t.node_type, t.status, t.duration, t.input_context, t.output_result, t.metadata 
                    FROM pg.public.temp_{table} t
                    WHERE NOT EXISTS (
                        SELECT 1 FROM pg.public.{table} 
                        WHERE execution_id = t.execution_id AND event_id = t.event_id
                    );
                """)
            elif table == 'workflow':
                self.conn.execute(f"""
                    INSERT INTO pg.public.{table} (execution_id, step_id, step_name, step_type, description, raw_config)
                    SELECT t.execution_id, t.step_id, t.step_name, t.step_type, t.description, t.raw_config 
                    FROM pg.public.temp_{table} t
                    WHERE NOT EXISTS (
                        SELECT 1 FROM pg.public.{table} 
                        WHERE execution_id = t.execution_id AND step_id = t.step_id
                    );
                """)
            elif table == 'workbook':
                self.conn.execute(f"""
                    INSERT INTO pg.public.{table} (execution_id, task_id, task_name, task_type, raw_config)
                    SELECT t.execution_id, t.task_id, t.task_name, t.task_type, t.raw_config 
                    FROM pg.public.temp_{table} t
                    WHERE NOT EXISTS (
                        SELECT 1 FROM pg.public.{table} 
                        WHERE execution_id = t.execution_id AND task_id = t.task_id
                    );
                """)
            elif table == 'transition':
                self.conn.execute(f"""
                    INSERT INTO pg.public.{table} (execution_id, from_step, to_step, condition, with_params)
                    SELECT t.execution_id, t.from_step, t.to_step, t.condition, t.with_params 
                    FROM pg.public.temp_{table} t
                    WHERE NOT EXISTS (
                        SELECT 1 FROM pg.public.{table} 
                        WHERE execution_id = t.execution_id AND from_step = t.from_step AND to_step = t.to_step AND condition = t.condition
                    );
                """)

            self.conn.execute(f"DROP TABLE pg.public.temp_{table};")

        logger.info("Sync to Postgres complete.")

    def run(self, mlflow: bool = False) -> Dict[str, Any]:
        """Run the playbook end to end"""
        logger.info(f"Starting playbook: {self.playbook.get('name', 'Unnamed')}")
        self.update_context('workload', self.playbook.get('workload', {}))
        self.update_context('execution_start', datetime.datetime.now().isoformat())
        execution_start_event = self.log_event(
            'execution_start', self.execution_id, self.playbook.get('name', 'Unnamed'), 'playbook',
            'in_progress', 0, self.context, None,
            {'playbook_path': self.playbook_path}, None
        )
        current_step = 'start'
        while current_step and current_step != 'end':
            step_config = self.find_step(current_step)
            if not step_config:
                logger.error(f"Step not found: {current_step}")
                self.log_event(
                    'execution_error', f"{self.execution_id}_error", self.playbook.get('name', 'Unnamed'), 'playbook',
                    'error', 0, self.context, None,
                    {'error': f"Step not found: {current_step}"}, execution_start_event
                )

                break

            step_result = self.execute_step(current_step, self.next_step_with)
            self.next_step_with = None

            if step_result['status'] != 'success':
                logger.error(f"Step failed: {current_step}, error: {step_result.get('error')}")
                self.log_event(
                    'execution_error', f"{self.execution_id}_error", self.playbook.get('name', 'Unnamed'), 'playbook',
                    'error', 0, self.context, None,
                    {'error': f"Step failed: {current_step}", 'step_error': step_result.get('error')},
                    execution_start_event
                )

                break

            if mlflow:
                next_step = self.get_ml_recommendation(current_step, self.context)
                if next_step:
                    current_step = next_step
                else:
                    break
            else:
                if 'next_step' in step_result:
                    current_step = step_result['next_step']
                    logger.info(f"Using next_step from step result: {current_step}")
                else:
                    next_steps = self.get_next_steps(step_config, self.context)
                    if not next_steps:
                        logger.info(f"No next steps found for: {current_step}")
                        break

                    current_step, step_with = next_steps[0]

                self.log_event(
                    'step_transition', f"{self.execution_id}_transition_{current_step}",
                    f"transition_to_{current_step}", 'transition',
                    'success', 0, self.context, None,
                    {'from_step': step_config.get('step'), 'to_step': current_step, 'with': step_with},
                    execution_start_event
                )
                self.next_step_with = step_with

        logger.info(f"Playbook execution completed")

        execution_duration = (datetime.datetime.now() - datetime.datetime.fromisoformat(
            self.context.get('execution_start'))).total_seconds()

        self.log_event(
            'execution_complete', f"{self.execution_id}_complete", self.playbook.get('name', 'Unnamed'), 'playbook',
            'success', execution_duration, self.context, None,
            {'playbook_path': self.playbook_path}, execution_start_event
        )

        step_result = {}
        rows = self.conn.execute("""
                                 SELECT step_name, data
                                 FROM step_result
                                 WHERE execution_id = ?
                                   AND status = 'success'
                                 """, (self.execution_id,)).fetchall()

        for row in rows:
            if row[1]:  # data exists
                step_result[row[0]] = json.loads(row[1])

        return step_result

    def find_step(self, step_name: str) -> Optional[Dict]:
        for step in self.playbook.get('workflow', []):
            if step.get('step') == step_name:
                return step
        return None

    def find_task(self, task_name: str) -> Optional[Dict]:
        for task in self.playbook.get('workbook', []):
            if task.get('task') == task_name:
                return task
        return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description="NoETL Agent with DuckDB Persistence", allow_abbrev=False)
    parser.add_argument("-f", "--file", required=True, help="Path to playbook YAML file")
    parser.add_argument("--mock", action="store_true", help="Run in mock mode")
    parser.add_argument("-o", "--output", default="json", choices=["json", "plain"], help="Output format")
    parser.add_argument("--duckdb", default=None, help="DuckDB database path (default: agent007.duckdb in script directory)")
    parser.add_argument("--export", help="Export execution data to Parquet file")
    parser.add_argument("--mlflow", action="store_true", help="Use ML model for workflow control")
    parser.add_argument("--sync", action="store_true", help="Sync DuckDB tables to Postgres")
    parser.add_argument("--pgdb", default=None, help="Postgres conn for DuckDB ATTACH (or set NOETL_PGDB env). Example: 'dbname=noetl user=noetl password=noetl host=localhost port=5434'")
    parser.add_argument("--debug", action="store_true", help="Set debug logging level")
    args, unknown = parser.parse_known_args()
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)
    if unknown:
        logger.warning(f"Ignoring unknown arguments: {unknown}")

    try:
        agent = NoETLAgent(args.file, mock_mode=args.mock, db_path=args.duckdb)
        results = agent.run(mlflow=args.mlflow)

        if args.export:
            agent.export_execution_data(args.export)

        if args.output == "json":
            logger.info(json.dumps(results, indent=2))
        else:
            for step, result in results.items():
                logger.info(f"{step}: {result}")

        logger.info(f"DuckDB database file: {agent.db_path}")
        logger.info(f"To validate result open the notebook notebook/agent007_mission_report.ipynb and set 'db_path' to {agent.db_path}")

        if args.sync:
            noetl_pgdb = args.pgdb or os.environ.get("NOETL_PGDB")
            if not noetl_pgdb:
                logger.error("--sync-postgres Postgres connection string missing (use --pgdb or NOETL_PGDB env var)")
            else:
                agent.postgres_sync(noetl_pgdb=noetl_pgdb)

    except Exception as e:
        logger.error(f"Error executing playbook: {e}", exc_info=True)
        print(f"Error executing playbook: {e}")
        return 1

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
