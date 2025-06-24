import yaml
import json
import logging
import os
import uuid
import datetime
from typing import Dict, List, Any, Optional, Tuple
from jinja2 import Environment, StrictUndefined, BaseLoader
import psycopg
import httpx

logger = logging.getLogger(__name__)

def render_template(env: Environment, template: Any, context: Dict, rules: Dict = None) -> Any:

    if isinstance(template, str) and '{{' in template and '}}' in template:
        logger.debug(f"Render template: {template}")
        logger.debug(f"Render template context keys: {list(context.keys())}")
        if 'city' in context:
            logger.debug(f"Render template city value: {context['city']}, Type: {type(context['city'])}")
        if rules:
            logger.debug(f"Render template rules: {rules}")

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
    def __init__(self, playbook_path: str, mock_mode: bool = True, pgdb: str = None):
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

        if pgdb is None:
            pgdb = "dbname=noetl user=noetl password=noetl host=localhost port=5434"
            logger.info(f"Default Postgres: {pgdb}")
        else:
            logger.info(f"Modified Postgres: {pgdb}")

        self.pgdb = pgdb
        self.conn = psycopg.connect(pgdb)
        self.init_database()
        self.parse_playbook()

    def init_database(self):
        with self.conn.cursor() as cursor:
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS context (
                    execution_id VARCHAR,
                    timestamp TIMESTAMP,
                    key VARCHAR,
                    value TEXT,
                    PRIMARY KEY (execution_id, key)
                )
            """)

            cursor.execute("""
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
                    duration DOUBLE PRECISION,
                    input_context TEXT,
                    output_result TEXT,
                    metadata TEXT,
                    error TEXT,
                    loop_id VARCHAR,
                    loop_name VARCHAR,
                    iterator VARCHAR,
                    items TEXT,
                    current_index INTEGER,
                    current_item TEXT,
                    results TEXT,
                    worker_id VARCHAR,
                    distributed_state VARCHAR,
                    context_key VARCHAR,
                    context_value TEXT,
                    PRIMARY KEY (execution_id, event_id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workflow (
                    execution_id VARCHAR,
                    step_id VARCHAR,
                    step_name VARCHAR,
                    step_type VARCHAR,
                    description TEXT,
                    raw_config TEXT,
                    PRIMARY KEY (execution_id, step_id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS workbook (
                    execution_id VARCHAR,
                    task_id VARCHAR,
                    task_name VARCHAR,
                    task_type VARCHAR,
                    raw_config TEXT,
                    PRIMARY KEY (execution_id, task_id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS transition (
                    execution_id VARCHAR,
                    from_step VARCHAR,
                    to_step VARCHAR,
                    condition TEXT,
                    with_params TEXT,
                    PRIMARY KEY (execution_id, from_step, to_step, condition)
                )
            """)

            self.conn.commit()

    def load_playbook(self) -> Dict:
        if not os.path.exists(self.playbook_path):
            raise FileNotFoundError(f"Playbook not found: {self.playbook_path}")

        with open(self.playbook_path, 'r') as f:
            return yaml.safe_load(f)

    def parse_playbook(self):
        with self.conn.cursor() as cursor:
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

                cursor.execute("""
                              INSERT INTO workflow
                              VALUES (%s, %s, %s, %s, %s, %s)
                              """, (
                                  self.execution_id,
                                  step_id,
                                  step_name,
                                  step_type,
                                  step.get('desc', ''),
                                  json.dumps(step)
                              ))

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

                            cursor.execute("""
                                              INSERT INTO transition
                                              VALUES (%s, %s, %s, %s, %s)
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

                            cursor.execute("""
                                              INSERT INTO transition
                                              VALUES (%s, %s, %s, %s, %s)
                                              """, (
                                                  self.execution_id,
                                                  step_name,
                                                  to_step,
                                                  'else',
                                                  with_params
                                              ))
                elif isinstance(next_step, str):
                    cursor.execute("""
                                      INSERT INTO transition
                                      VALUES (%s, %s, %s, %s, %s)
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
                    cursor.execute("""
                                      INSERT INTO transition
                                      VALUES (%s, %s, %s, %s, %s)
                                      """, (
                                          self.execution_id,
                                          step_name,
                                          to_step,
                                          '',
                                          with_params
                                      ))

            for task in self.playbook.get('workbook', []):
                task_id = str(uuid.uuid4())
                task_name = task.get('name') or task.get('task')
                task_type = task.get('type', 'http')

                cursor.execute("""
                              INSERT INTO workbook
                              VALUES (%s, %s, %s, %s, %s)
                              """, (
                                  self.execution_id,
                                  task_id,
                                  task_name,
                                  task_type,
                                  json.dumps(task)
                              ))

            self.conn.commit()

    def update_context(self, key: str, value: Any):
        self.context[key] = value

        self.log_event(
            'context_update', f"{self.execution_id}_context_{key}", key, 'context',
            'success', 0, self.get_context(), None,
            {'context_updated': True}, None,
            worker_id=os.environ.get('WORKER_ID', 'local'),
            distributed_state='updated',
            context_key=key,
            context_value=value
        )

    def get_context(self, include_locals: Dict = None) -> Dict:
        if include_locals:
            return {**self.context, **include_locals}
        return self.context

    def log_event(self, event_type: str, node_id: str, node_name: str, node_type: str,
                  status: str, duration: float, input_context: Dict, output_result: Any,
                  metadata: Dict = None, parent_event_id: str = None,
                  loop_id: str = None, loop_name: str = None, iterator: str = None,
                  items: List[Any] = None, current_index: int = None, current_item: Any = None,
                  results: List[Any] = None, worker_id: str = None, distributed_state: str = None,
                  error: str = None, context_key: str = None, context_value: Any = None):
        event_id = str(uuid.uuid4())

        input_context_serial = json.dumps({k: v for k, v in input_context.items() if not k.startswith('_')})
        output_result_serial = json.dumps(output_result) if output_result is not None else None
        metadata_serial = json.dumps(metadata) if metadata is not None else None
        items_serial = json.dumps(items) if items is not None else None
        current_item_serial = json.dumps(current_item) if current_item is not None else None
        results_serial = json.dumps(results) if results is not None else None
        context_value_serial = json.dumps(context_value) if context_value is not None and not isinstance(context_value, (str, int, float, bool)) else str(context_value) if context_value is not None else None

        with self.conn.cursor() as cursor:
            cursor.execute("""
                          INSERT INTO event_log
                          (execution_id, event_id, parent_event_id, timestamp, event_type,
                           node_id, node_name, node_type, status, duration,
                           input_context, output_result, metadata, error,
                           loop_id, loop_name, iterator, items, current_index, current_item, results,
                           worker_id, distributed_state, context_key, context_value)
                          VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                          """, (
                              self.execution_id, event_id, parent_event_id, datetime.datetime.now(), event_type,
                              node_id, node_name, node_type, status, duration,
                              input_context_serial, output_result_serial, metadata_serial, error,
                              loop_id, loop_name, iterator, items_serial, current_index, current_item_serial, results_serial,
                              worker_id, distributed_state, context_key, context_value_serial
                          ))
            self.conn.commit()

        return event_id


    def save_step_result(self, step_id: str, step_name: str, parent_id: str,
                         status: str, data: Any = None, error: str = None):
        event_id = self.log_event(
            'step_result', step_id, step_name, 'step',
            status, 0, self.get_context(), data,
            {'parent_id': parent_id}, parent_id,
            worker_id=os.environ.get('WORKER_ID', 'local'),
            distributed_state=status,
            error=error
        )

        return step_id

    def create_loop_state(self, loop_name: str, iterator: str, items: List[Any], parent_id: str = None):
        loop_id = str(uuid.uuid4())

        self.log_event(
            'loop_state_created', loop_id, loop_name, 'step.loop',
            'created', 0, self.get_context(), None,
            {'state_created': True}, parent_id,
            loop_id=loop_id, loop_name=loop_name, iterator=iterator,
            items=items, current_index=-1, current_item=None, results=[],
            worker_id=os.environ.get('WORKER_ID', 'local'),
            distributed_state='created'
        )

        return loop_id

    def update_loop_state(self, loop_id: str, current_index: int, current_item: Any, status: str):
        with self.conn.cursor() as cursor:
            cursor.execute("""
                           SELECT loop_name, iterator, items, results
                           FROM event_log
                           WHERE execution_id = %s
                             AND loop_id = %s
                           ORDER BY timestamp DESC
                           LIMIT 1
                           """, (self.execution_id, loop_id))
            row = cursor.fetchone()

        if row:
            loop_name, iterator, items, results = row

            self.log_event(
                'loop_state_updated', loop_id, loop_name, 'step.loop',
                'success', 0, self.get_context(), None,
                {'state_updated': True}, None,
                loop_id=loop_id, loop_name=loop_name, iterator=iterator,
                items=json.loads(items) if items else None,
                current_index=current_index,
                current_item=current_item,
                results=json.loads(results) if results else [],
                worker_id=os.environ.get('WORKER_ID', 'local'),
                distributed_state=status
            )

    def add_loop_result(self, loop_id: str, result: Any):
        with self.conn.cursor() as cursor:
            cursor.execute("""
                           SELECT loop_name, iterator, items, current_index, current_item, results
                           FROM event_log
                           WHERE execution_id = %s
                             AND loop_id = %s
                           ORDER BY timestamp DESC
                           LIMIT 1
                           """, (self.execution_id, loop_id))
            row = cursor.fetchone()

        if row:
            loop_name, iterator, items, current_index, current_item, results = row

            current_results = json.loads(results) if results else []
            current_results.append(result)
            self.log_event(
                'loop_result_added', loop_id, loop_name, 'step.loop',
                'success', 0, self.get_context(), result,
                {'result_added': True}, None,
                loop_id=loop_id, loop_name=loop_name, iterator=iterator,
                items=json.loads(items) if items else None,
                current_index=current_index,
                current_item=json.loads(current_item) if current_item else None,
                results=current_results,
                worker_id=os.environ.get('WORKER_ID', 'local'),
                distributed_state='result_added'
            )

    def get_loop_results(self, loop_id: str) -> List[Any]:
        with self.conn.cursor() as cursor:
            cursor.execute("""
                           SELECT results
                           FROM event_log
                           WHERE execution_id = %s
                             AND loop_id = %s
                           ORDER BY timestamp DESC
                           LIMIT 1
                           """, (self.execution_id, loop_id))
            result_row = cursor.fetchone()

        if result_row and result_row[0]:
            return json.loads(result_row[0])
        return []

    def get_active_loops(self) -> List[Dict]:
        with self.conn.cursor() as cursor:
            cursor.execute("""
                           SELECT el.loop_id, el.loop_name, el.iterator, el.items, el.current_index, el.current_item, el.results
                           FROM event_log el
                           INNER JOIN (
                               SELECT loop_id, MAX(timestamp) as latest_timestamp
                               FROM event_log
                               WHERE execution_id = %s
                                 AND loop_id IS NOT NULL
                               GROUP BY loop_id
                           ) latest ON el.loop_id = latest.loop_id AND el.timestamp = latest.latest_timestamp
                           WHERE el.execution_id = %s
                             AND el.distributed_state != 'completed'
                           ORDER BY el.timestamp ASC
                           """, (self.execution_id, self.execution_id))
            rows = cursor.fetchall()

        loops = []
        for row in rows:
            loops.append({
                'id': row[0],
                'name': row[1],
                'iterator': row[2],
                'items': json.loads(row[3]) if row[3] else [],
                'index': row[4],
                'current_item': json.loads(row[5]) if row[5] else None,
                'results': json.loads(row[6]) if row[6] else []
            })

        return loops

    def find_loop(self, loop_name: str, include_completed: bool = False) -> Optional[Dict]:
        logger.debug(f"Finding loop by name: {loop_name}, include_completed: {include_completed}")

        with self.conn.cursor() as cursor:
            cursor.execute("""
                         SELECT DISTINCT loop_id, loop_name, distributed_state
                         FROM event_log
                         WHERE execution_id = %s
                           AND loop_id IS NOT NULL
                         """, (self.execution_id,))
            all_loops = cursor.fetchall()
        logger.debug(f"All loops in database: {all_loops}")

        if include_completed:
            query = """
                   SELECT el.loop_id, el.iterator, el.items, el.current_index, el.current_item, el.results
                   FROM event_log el
                   INNER JOIN (
                       SELECT loop_id, MAX(timestamp) as latest_timestamp
                       FROM event_log
                       WHERE execution_id = %s
                         AND loop_name = %s
                         AND loop_id IS NOT NULL
                       GROUP BY loop_id
                   ) latest ON el.loop_id = latest.loop_id AND el.timestamp = latest.latest_timestamp
                   WHERE el.execution_id = %s
                     AND el.loop_name = %s
                   ORDER BY el.timestamp DESC
                   LIMIT 1
                   """
            params = (self.execution_id, loop_name, self.execution_id, loop_name)
        else:
            query = """
                   SELECT el.loop_id, el.iterator, el.items, el.current_index, el.current_item, el.results
                   FROM event_log el
                   INNER JOIN (
                       SELECT loop_id, MAX(timestamp) as latest_timestamp
                       FROM event_log
                       WHERE execution_id = %s
                         AND loop_name = %s
                         AND loop_id IS NOT NULL
                       GROUP BY loop_id
                   ) latest ON el.loop_id = latest.loop_id AND el.timestamp = latest.latest_timestamp
                   WHERE el.execution_id = %s
                     AND el.loop_name = %s
                     AND el.distributed_state != 'completed'
                   ORDER BY el.timestamp DESC
                   LIMIT 1
                   """
            params = (self.execution_id, loop_name, self.execution_id, loop_name)

        with self.conn.cursor() as cursor:
            cursor.execute(query, params)
            row = cursor.fetchone()

        if row:
            return {
                'id': row[0],
                'iterator': row[1],
                'items': json.loads(row[2]) if row[2] else [],
                'index': row[3],
                'current_item': json.loads(row[4]) if row[4] else None,
                'results': json.loads(row[5]) if row[5] else []
            }
        return None

    def complete_loop(self, loop_id: str):
        with self.conn.cursor() as cursor:
            cursor.execute("""
                         SELECT loop_name, iterator, items, current_index, results
                         FROM event_log
                         WHERE execution_id = %s
                           AND loop_id = %s
                         ORDER BY timestamp DESC
                         LIMIT 1
                         """, (self.execution_id, loop_id))
            row = cursor.fetchone()

        if row:
            loop_name, iterator, items, current_index, results = row

            self.log_event(
                'loop_complete', loop_id, loop_name, 'step.loop',
                'success', 0, self.get_context(), None,
                {'completed_by': 'complete_loop'}, None,
                loop_id=loop_id, loop_name=loop_name, iterator=iterator,
                items=json.loads(items) if items else None,
                current_index=current_index,
                current_item=None,
                results=json.loads(results) if results else None,
                worker_id=os.environ.get('WORKER_ID', 'local'),
                distributed_state='completed'
            )

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
        logger.debug(f"Executing step: step_name={step_name}, step_with={step_with}")
        logger.debug(f"Executing step: context before update: {self.context}")
        step_context = self.get_context()
        if step_with:
            rendered_with = render_template(self.jinja_env, step_with, step_context)
            logger.debug(f"Executing step: rendered_with={rendered_with}")
            if rendered_with:
                step_context.update(rendered_with)
                for key, value in rendered_with.items():
                    self.update_context(key, value)

        logger.debug(f"Executing step: context after update: {step_context}")
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
            task_name = call_config.get('name') or call_config.get('task')
            call_type = call_config.get('type', 'workbook')
            task_with = render_template(self.jinja_env, call_config.get('with', {}), step_context)
            task_context = {**step_context, **task_with}

            if call_type == 'workbook':
                result = self.execute_task(task_name, task_context, step_event)
            else:
                error_msg = f"Unsupported call type: {call_type}"
                logger.error(error_msg)
                result = {
                    'id': str(uuid.uuid4()),
                    'status': 'error',
                    'error': error_msg
                }

            self.save_step_result(
                step_id, step_name, None,
                result.get('status', 'success'), result.get('data'), result.get('error')
            )

            self.update_context(step_name, result.get('data'))
            self.update_context(step_name + '.result', result.get('data'))
            self.update_context(step_name + '.status', result.get('status'))
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
        logger.debug(f"Loop step iterator={iterator}, items={items}")

        loop_name = step_config.get('step', 'unnamed_loop')
        loop_id = str(uuid.uuid4())

        loop_start_event = self.log_event(
            'loop_start', loop_id, loop_name, 'step.loop',
            'in_progress', 0, context, None,
            {'item_count': len(items), 'iterator': iterator}, None,
            loop_id=loop_id, loop_name=loop_name, iterator=iterator,
            items=items, current_index=-1, current_item=None, results=[],
            worker_id=os.environ.get('WORKER_ID', 'local'), distributed_state='created'
        )

        all_results = []

        for idx, item in enumerate(items):
            iter_context = dict(context)
            iter_context[iterator] = validate_dict(item)

            iter_event = self.log_event(
                'loop_iteration', f"{loop_id}_{idx}", f"{loop_name}[{idx}]", 'iteration',
                'in_progress', 0, context, None,
                {'index': idx, 'item': item}, loop_start_event,
                loop_id=loop_id, loop_name=loop_name, iterator=iterator,
                items=items, current_index=idx, current_item=item, results=all_results,
                worker_id=os.environ.get('WORKER_ID', 'local'), distributed_state='processing'
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

                rules = {iterator: iter_context[iterator]}
                logger.debug(f"Loop next step: {next_step_name}, next_step_with={next_step_with}, rules={rules}")

                step_with = render_template(self.jinja_env, next_step_with, iter_context, rules)
                logger.debug(f"Loop step rendered with: {step_with}")

                if not next_step_name:
                    continue
                step_result = self.execute_step(next_step_name, step_with)
                iter_results[next_step_name] = step_result.get('data') if step_result.get(
                    'status') == 'success' else None

            all_results.append(iter_results)
            self.log_event(
                'loop_iteration_complete', f"{loop_id}_{idx}", f"{loop_name}[{idx}]", 'iteration',
                'success', 0, iter_context, iter_results,
                {'index': idx, 'item': item}, iter_event,
                loop_id=loop_id, loop_name=loop_name, iterator=iterator,
                items=items, current_index=idx, current_item=item, results=all_results,
                worker_id=os.environ.get('WORKER_ID', 'local'), distributed_state='iteration_complete'
            )

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
            {'item_count': len(items), 'processed_count': len(all_results)}, loop_start_event,
            loop_id=loop_id, loop_name=loop_name, iterator=iterator,
            items=items, current_index=len(items), current_item=None, results=all_results,
            worker_id=os.environ.get('WORKER_ID', 'local'), distributed_state='completed'
        )

        loop_name = step_config.get('step')
        for step in self.playbook.get('workflow', []):
            if 'end_loop' in step and step.get('end_loop') == loop_name:
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

    def get_next_steps(self, step_config: Dict, context: Dict) -> List[Tuple[str, Dict, str]]:
        next_steps = step_config.get('next', [])
        if not next_steps:
            return []

        if not isinstance(next_steps, list):
            next_steps = [next_steps]

        result_steps = []

        for next_step in next_steps:
            if isinstance(next_step, dict) and 'when' in next_step:
                condition_text = next_step['when']
                condition = render_template(self.jinja_env, condition_text, context)
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

    def get_ml_recommendation(self, current_step: str, context: Dict) -> str:
        step_config = self.find_step(current_step)
        next_steps = self.get_next_steps(step_config, context)
        if next_steps:
            return next_steps[0][0]
        return None

    def export_execution_data(self, filepath: str = None):
        if not filepath:
            filepath = f"noetl_execution_{self.execution_id}.json"

        with self.conn.cursor() as cursor:
            cursor.execute("""
                           SELECT execution_id, event_id, parent_event_id, timestamp, event_type,
                                  node_id, node_name, node_type, status, duration,
                                  input_context, output_result, metadata, error,
                                  loop_id, loop_name, iterator, items, current_index, current_item, results,
                                  worker_id, distributed_state, context_key, context_value
                           FROM event_log
                           WHERE execution_id = %s
                           ORDER BY timestamp
                           """, (self.execution_id,))

            rows = cursor.fetchall()

            if rows:
                columns = [desc[0] for desc in cursor.description]
                event_log_data = [dict(zip(columns, row)) for row in rows]

                with open(filepath, 'w') as f:
                    json.dump(event_log_data, f, default=str, indent=2)

                logger.info(f"Execution data exported to {filepath}")
                return filepath

        logger.warning("No execution data to export")
        return None

    def run(self, mlflow: bool = False) -> Dict[str, Any]:
        logger.info(f"Starting playbook: {self.playbook.get('name', 'Unnamed')}")
        self.update_context('workload', self.playbook.get('workload', {}))
        self.update_context('execution_start', datetime.datetime.now().isoformat())
        execution_start_event = self.log_event(
            'execution_start', self.execution_id, self.playbook.get('name', 'Unnamed'),
            'playbook',
            'in_progress',
            0, self.context,
            None,
            {'playbook_path': self.playbook_path},
            None
        )
        current_step = 'start'
        while current_step and current_step != 'end':
            step_config = self.find_step(current_step)
            if not step_config:
                logger.error(f"Step not found: {current_step}")
                self.log_event(
                    'execution_error',
                    f"{self.execution_id}_error", self.playbook.get('name', 'Unnamed'),
                    'playbook',
                    'error', 0, self.context, None,
                    {'error': f"Step not found: {current_step}"}, execution_start_event
                )

                break

            step_result = self.execute_step(current_step, self.next_step_with)
            self.next_step_with = None

            if step_result['status'] != 'success':
                logger.error(f"Step failed: {current_step}, error: {step_result.get('error')}")
                self.log_event(
                    'execution_error',
                    f"{self.execution_id}_error", self.playbook.get('name', 'Unnamed'),
                    'playbook',
                    'error', 0, self.context, None,
                    {'error': f"Step failed: {current_step}", 'step_error': step_result.get('error')},
                    execution_start_event
                )

                break

            if mlflow:
                next_step = self.get_ml_recommendation(current_step, self.context)
                if next_step:
                    step_config = self.find_step(current_step)
                    next_steps = self.get_next_steps(step_config, self.context)
                    step_with = {}
                    condition = "ml_recommendation"

                    for ns in next_steps:
                        if ns[0] == next_step:
                            step_with = ns[1]
                            condition = f"{ns[2]} (ml_selected)"
                            break

                    self.log_event(
                        'step_transition', f"{self.execution_id}_transition_{next_step}",
                        f"transition_to_{next_step}", 'transition',
                        'success', 0, self.context, None,
                        {'from_step': step_config.get('step'), 'to_step': next_step, 'with': step_with, 'condition': condition},
                        execution_start_event
                    )

                    with self.conn.cursor() as cursor:
                        cursor.execute("""
                            INSERT INTO transition (execution_id, from_step, to_step, condition, with_params)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (
                            self.execution_id,
                            step_config.get('step'),
                            next_step,
                            condition,
                            json.dumps(step_with) if step_with else '{}'
                        ))
                        self.conn.commit()

                    self.next_step_with = step_with
                    current_step = next_step
                else:
                    break
            else:
                if 'next_step' in step_result:
                    next_step = step_result['next_step']
                    logger.info(f"Using next_step from step result: {next_step}")

                    self.log_event(
                        'step_transition', f"{self.execution_id}_transition_{next_step}",
                        f"transition_to_{next_step}", 'transition',
                        'success', 0, self.context, None,
                        {'from_step': step_config.get('step'), 'to_step': next_step, 'with': {}, 'condition': 'direct_specification'},
                        execution_start_event
                    )

                    with self.conn.cursor() as cursor:
                        cursor.execute("""
                            INSERT INTO transition (execution_id, from_step, to_step, condition, with_params)
                            VALUES (%s, %s, %s, %s, %s)
                        """, (
                            self.execution_id,
                            step_config.get('step'),
                            next_step,
                            'direct_specification',
                            '{}'
                        ))
                        self.conn.commit()

                    current_step = next_step
                else:
                    next_steps = self.get_next_steps(step_config, self.context)
                    if not next_steps:
                        logger.info(f"No next steps found for: {current_step}")
                        break

                    current_step, step_with, condition = next_steps[0]

                self.log_event(
                    'step_transition', f"{self.execution_id}_transition_{current_step}",
                    f"transition_to_{current_step}", 'transition',
                    'success', 0, self.context, None,
                    {'from_step': step_config.get('step'), 'to_step': current_step, 'with': step_with, 'condition': condition},
                    execution_start_event
                )

                with self.conn.cursor() as cursor:
                    cursor.execute("""
                        INSERT INTO transition (execution_id, from_step, to_step, condition, with_params)
                        VALUES (%s, %s, %s, %s, %s)
                    """, (
                        self.execution_id,
                        step_config.get('step'),
                        current_step,
                        condition,
                        json.dumps(step_with) if step_with else '{}'
                    ))
                    self.conn.commit()

                self.next_step_with = step_with

        logger.info(f"Playbook execution completed")

        execution_duration = (datetime.datetime.now() - datetime.datetime.fromisoformat(
            self.context.get('execution_start'))).total_seconds()

        self.log_event(
            'execution_complete',
            f"{self.execution_id}_complete", self.playbook.get('name', 'Unnamed'),
            'playbook',
            'success', execution_duration, self.context, None,
            {'playbook_path': self.playbook_path}, execution_start_event
        )

        step_result = {}
        with self.conn.cursor() as cursor:
            cursor.execute("""
                           SELECT node_name, output_result
                           FROM event_log
                           WHERE execution_id = %s
                             AND event_type = 'step_result'
                             AND status = 'success'
                           """, (self.execution_id,))
            rows = cursor.fetchall()

            for row in rows:
                if row[1]:
                    step_result[row[0]] = json.loads(row[1])

        return step_result

    def find_step(self, step_name: str) -> Optional[Dict]:
        for step in self.playbook.get('workflow', []):
            if step.get('step') == step_name:
                return step
        return None

    def find_task(self, task_name: str) -> Optional[Dict]:
        for task in self.playbook.get('workbook', []):
            if task.get('name') == task_name or task.get('task') == task_name:
                return task
        return None


def main():
    import argparse
    parser = argparse.ArgumentParser(description="NoETL Agent with PostgreSQL Persistence", allow_abbrev=False)
    parser.add_argument("-f", "--file", required=True, help="Path to playbook YAML file")
    parser.add_argument("--mock", action="store_true", help="Run in mock mode")
    parser.add_argument("-o", "--output", default="json", choices=["json", "plain"], help="Output format")
    parser.add_argument("--export", help="Export execution data to Parquet file")
    parser.add_argument("--mlflow", action="store_true", help="Use ML model for workflow control")
    parser.add_argument("--pgdb", default=None, help="PostgreSQL connection string. \
                                            Example: 'dbname=noetl user=noetl password=noetl host=localhost port=5434'")
    parser.add_argument("--input", help="Path to JSON file with input payload for the playbook")
    parser.add_argument("--debug", action="store_true", help="Debug logging level")
    args, unknown = parser.parse_known_args()
    logging.basicConfig(
        format='[%(levelname)s] %(asctime)s,%(msecs)03d (%(name)s:%(funcName)s:%(lineno)d) - %(message)s',
        datefmt='%Y-%m-%dT%H:%M:%S',
        level=logging.DEBUG if args.debug else logging.INFO
    )
    if unknown:
        logger.warning(f"Ignoring unknown arguments: {unknown}")

    try:
        input_payload = None
        if args.input:
            try:
                with open(args.input, 'r') as f:
                    input_payload = json.load(f)
                logger.info(f"Loaded input payload from {args.input}")
            except Exception as e:
                logger.error(f"Error loading input payload: {e}")
                return 1

        pgdb = args.pgdb or os.environ.get("NOETL_PGDB")
        if not pgdb:
            pgdb = "dbname=noetl user=noetl password=noetl host=localhost port=5434"
            logger.info(f"Using default PostgreSQL connection string: {pgdb}")

        agent = NoETLAgent(args.file, mock_mode=args.mock, pgdb=pgdb)

        if input_payload:
            for key, value in input_payload.items():
                agent.update_context(key, value)

        results = agent.run(mlflow=args.mlflow)

        if args.export:
            agent.export_execution_data(args.export)

        if args.output == "json":
            logger.info(json.dumps(results, indent=2))
        else:
            for step, result in results.items():
                logger.info(f"{step}: {result}")

        logger.info(f"PostgreSQL connection: {agent.pgdb}")
        logger.info(f"Open notebook/agent_mission_report.ipynb and set 'pgdb' to {agent.pgdb}")

    except Exception as e:
        logger.error(f"Error executing playbook: {e}", exc_info=True)
        print(f"Error executing playbook: {e}")
        return 1

    return 0


if __name__ == "__main__":
    import sys

    sys.exit(main())
