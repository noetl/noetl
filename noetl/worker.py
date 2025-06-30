import yaml
import json
import os
import uuid
import datetime
from typing import Dict, List, Any, Optional, Tuple
from jinja2 import Environment, StrictUndefined, BaseLoader
from noetl.common import render_template
from noetl.secret import SecretManager
from noetl.sqlcmd import *
from noetl.common import setup_logger

logger = setup_logger(__name__, include_location=True)

class NoETLAgent:

    def __init__(self, playbook_path: str, mock_mode: bool = True, pgdb: str = None):
        self.playbook_path = playbook_path
        self.mock_mode = mock_mode
        self.execution_id = str(uuid.uuid4())
        self.playbook = self.load_playbook()
        self.jinja_env = Environment(loader=BaseLoader(), undefined=StrictUndefined)
        self.jinja_env.filters['to_json'] = lambda obj: json.dumps(obj)
        self.jinja_env.globals['now'] = lambda: datetime.datetime.now().isoformat()
        self.jinja_env.globals['env'] = os.environ
        self.next_step_with = None
        self.secret_manager = SecretManager(self.jinja_env, self.mock_mode)

        if pgdb is None:
            pgdb = f"dbname={os.environ.get('POSTGRES_DB', 'noetl')} user={os.environ.get('POSTGRES_USER', 'noetl')} password={os.environ.get('POSTGRES_PASSWORD', 'noetl')} host={os.environ.get('POSTGRES_HOST', 'localhost')} port={os.environ.get('POSTGRES_PORT', '5434')}"
            logger.info(f"Default Postgres: {pgdb}")
        else:
            logger.info(f"Modified Postgres: {pgdb}")

        self.pgdb = pgdb
        from noetl.schema import DatabaseSchema
        self.db_schema = DatabaseSchema(pgdb=pgdb)
        self.conn = self.db_schema.conn
        self.db_schema.init_database()

        self.context = {
            'job': {
                'uuid': self.execution_id,
                'id': self.execution_id
            }
        }

        db_workload = self.load_workload()
        if db_workload:
            logger.info(f"Using workload from database for execution {self.execution_id}")
            rendered_workload = render_template(self.jinja_env, db_workload, self.context)
            self.context.update(rendered_workload)
        else:
            logger.info(f"Workload not found in database. Using default from playbook.")
            rendered_workload = render_template(self.jinja_env, self.playbook.get('workload', {}), self.context)
            self.context.update(rendered_workload)

        self.parse_playbook()

    def store_workload(self, data: Dict):
        """
        Store workload data in the database.

        Args:
            data: The workload
        """
        if not isinstance(data, dict):
            logger.error(f"Invalid workload data type: {type(data)}. Expected dict.")
            return

        try:
            data_json = json.dumps(data)
            logger.info(f"Storing workload data for execution {self.execution_id}: {data_json[:100]}.")
            with self.conn.cursor() as cursor:
                cursor.execute(WORKLOAD_TABLE_EXISTS_POSTGRES)
                table_exists = cursor.fetchone()[0]
                if not table_exists:
                    logger.error("Workload table does not exist in the database.")
                    self.db_schema.init_database()
                    self.conn.commit()
                    logger.info("Database schema initialized.")

            with self.conn.cursor() as cursor:
                logger.info(f"Executing INSERT INTO workload for execution_id: {self.execution_id}")
                cursor.execute(WORKLOAD_INSERT_POSTGRES, (self.execution_id, data_json))
                self.conn.commit()
                logger.info(f"INSERT INTO workload completed and committed for execution_id: {self.execution_id}")
                cursor.execute(WORKLOAD_COUNT_BY_ID_POSTGRES, (self.execution_id,))
                count = cursor.fetchone()[0]
                if count == 0:
                    logger.error(f"Failed to store workload data for execution {self.execution_id}.")
                else:
                    logger.info(f"Stored workload data for execution {self.execution_id}. Found {count} rows.")

                    cursor.execute(WORKLOAD_SELECT_POSTGRES, (self.execution_id,))
                    row = cursor.fetchone()
                    if row and row[0]:
                        logger.info(f"Retrieved workload data for execution {self.execution_id}: {row[0][:100]}.")
                    else:
                        logger.error(f"Failed to retrieve workload data for execution {self.execution_id} count: {count}.")
        except Exception as e:
            logger.error(f"Error storing workload data: {e}", exc_info=True)

    def load_workload(self) -> Dict:
        """
        Load workload data from the database.

        Returns:
            The workload data
        """
        try:
            logger.info(f"Loading workload data for execution {self.execution_id}")
            with self.conn.cursor() as cursor:
                logger.info("Checking if workload table exists")
                cursor.execute(WORKLOAD_TABLE_EXISTS_POSTGRES)
                table_exists = cursor.fetchone()[0]
                if not table_exists:
                    logger.error("Workload table does not exist in the database")
                    return {}
                else:
                    logger.info("Workload table exists in the database.")
                logger.info("Checking if workload table has rows")
                cursor.execute(WORKLOAD_COUNT_POSTGRES)
                total_count = cursor.fetchone()[0]
                logger.info(f"Total rows in workload table: {total_count}.")
                logger.info(f"Querying workload data for execution_id: {self.execution_id}")
                cursor.execute(WORKLOAD_SELECT_POSTGRES, (self.execution_id,))
                row = cursor.fetchone()

                if row and row[0]:
                    logger.info(f"Found workload data for execution {self.execution_id}")
                    try:
                        workload_data = json.loads(row[0])
                        logger.info(f"Parsed workload data for execution {self.execution_id}: {str(workload_data)[:100]}.")
                        return workload_data
                    except json.JSONDecodeError as e:
                        logger.error(f"Error decoding workload data: {e}.")
                        logger.error(f"Raw data: {row[0][:100]}.")
                        return {}
                else:
                    logger.info(f"No workload data found for execution {self.execution_id}")
                    cursor.execute(WORKLOAD_SELECT_ALL_IDS_POSTGRES)
                    all_execution_ids = [r[0] for r in cursor.fetchall()]
                    logger.info(f"All execution_ids in workload table: {all_execution_ids}")
                    return {}
        except Exception as e:
            logger.error(f"Error loading workload data: {e}", exc_info=True)
            return {}

    def load_playbook(self) -> Dict:
        """
        Load the playbook from the file.

        Returns:
            The playbook data
        """
        if not os.path.exists(self.playbook_path):
            raise FileNotFoundError(f"Playbook not found: {self.playbook_path}")

        with open(self.playbook_path, 'r') as f:
            return yaml.safe_load(f)

    def parse_playbook(self):
        """
        Parse the playbook and store in the database.
        """
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

                params = (
                    self.execution_id,
                    step_id,
                    step_name,
                    step_type,
                    step.get('desc', ''),
                    json.dumps(step)
                )
                cursor.execute(WORKFLOW_INSERT_POSTGRES, params)

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

                                params = (
                                    self.execution_id,
                                    step_name,
                                    to_step,
                                    condition,
                                    with_params
                                )
                                cursor.execute(TRANSITION_INSERT_CONDITION_POSTGRES, params)
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

                                params = (
                                    self.execution_id,
                                    step_name,
                                    to_step,
                                    'else',
                                    with_params
                                )
                                cursor.execute(TRANSITION_INSERT_CONDITION_POSTGRES, params)
                    elif isinstance(next_step, str):
                        params = (
                            self.execution_id,
                            step_name,
                            next_step,
                            '',
                            '{}'
                        )
                        cursor.execute(TRANSITION_INSERT_CONDITION_POSTGRES, params)
                    else:
                        to_step = next_step.get('step')
                        with_params = json.dumps(next_step.get('with', {}))
                        params = (
                            self.execution_id,
                            step_name,
                            to_step,
                            '',
                            with_params
                        )
                        cursor.execute(TRANSITION_INSERT_CONDITION_POSTGRES, params)

            for task in self.playbook.get('workbook', []):
                task_id = str(uuid.uuid4())
                task_name = task.get('name') or task.get('task')
                task_type = task.get('type', 'http')

                params = (
                    self.execution_id,
                    task_id,
                    task_name,
                    task_type,
                    json.dumps(task)
                )
                cursor.execute(WORKBOOK_INSERT_POSTGRES, params)

            self.conn.commit()

    def update_context(self, key: str, value: Any):
        """
        Update the context with a new kv.

        Args:
            key: key
            value: value to set for the key
        """
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
        """
        Get the current context.

        Args:
            include_locals: local variables to add to the context

        Returns:
            The current context
        """
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
        """
        Log an event to the database.

        Args:
            event_type: The type of event
            node_id: The ID of the node
            node_name: The name of the node
            node_type: The type of node
            status: The status of the event
            duration: The duration of the event
            input_context: The input context
            output_result: The output result
            metadata: Additional metadata
            parent_event_id: The ID of the parent event
            loop_id: The ID of the loop
            loop_name: The name of the loop
            iterator: The iterator variable name
            items: The items being iterated over
            current_index: The current index in the loop
            current_item: The current item in the loop
            results: The results of the loop
            worker_id: The ID of the worker
            distributed_state: The distributed state
            error: The error message
            context_key: The context key being updated
            context_value: The context value being set

        Returns:
            The ID of the event
        """
        event_id = str(uuid.uuid4())

        input_context_serial = json.dumps({k: v for k, v in input_context.items() if not k.startswith('_')})
        output_result_serial = json.dumps(output_result) if output_result is not None else None
        metadata_serial = json.dumps(metadata) if metadata is not None else None
        items_serial = json.dumps(items) if items is not None else None
        current_item_serial = json.dumps(current_item) if current_item is not None else None
        results_serial = json.dumps(results) if results is not None else None
        context_value_serial = json.dumps(context_value) if context_value is not None and not isinstance(context_value, (str, int, float, bool)) else str(context_value) if context_value is not None else None

        params = (
            self.execution_id, event_id, parent_event_id, datetime.datetime.now(), event_type,
            node_id, node_name, node_type, status, duration,
            input_context_serial, output_result_serial, metadata_serial, error,
            loop_id, loop_name, iterator, items_serial, current_index, current_item_serial, results_serial,
            worker_id, distributed_state, context_key, context_value_serial
        )

        with self.conn.cursor() as cursor:
            cursor.execute(EVENT_LOG_INSERT_POSTGRES, params)
            self.conn.commit()

        return event_id

    def save_step_result(self, step_id: str, step_name: str, parent_id: str,
                         status: str, data: Any = None, error: str = None):
        """
        Save the result of a step.

        Args:
            step_id: The ID of the step
            step_name: The name of the step
            parent_id: The ID of the parent step
            status: The status of the step
            data: The data returned by the step
            error: The error message

        Returns:
            The ID of the step
        """
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
        """
        Create a new loop state.

        Args:
            loop_name: The name of the loop
            iterator: The iterator variable name
            items: The items to iterate over
            parent_id: The ID of the parent step

        Returns:
            The ID of the loop
        """
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
        """
        Update the state of a loop.

        Args:
            loop_id: The ID of the loop
            current_index: The current index in the loop
            current_item: The current item in the loop
            status: The status of the loop
        """
        params = (self.execution_id, loop_id)
        with self.conn.cursor() as cursor:
            cursor.execute(LOOP_SELECT_POSTGRES, params)
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
        """
        Add a result to a loop.

        Args:
            loop_id: The ID of the loop
            result: The result to add
        """
        params = (self.execution_id, loop_id)
        with self.conn.cursor() as cursor:
            cursor.execute(LOOP_DETAILS_SELECT_POSTGRES, params)
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
        """
        Get the results of a loop.

        Args:
            loop_id: The ID of the loop

        Returns:
            The results of the loop
        """
        params = (self.execution_id, loop_id)
        with self.conn.cursor() as cursor:
            cursor.execute(LOOP_RESULTS_SELECT_POSTGRES, params)
            result_row = cursor.fetchone()

        if result_row and result_row[0]:
            return json.loads(result_row[0])
        return []

    def get_active_loops(self) -> List[Dict]:
        """
        Get all active loops.

        Returns:
            A list of active loops
        """
        params = (self.execution_id, self.execution_id)
        with self.conn.cursor() as cursor:
            cursor.execute(GET_ACTIVE_LOOPS_POSTGRES, params)
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
        """
        Find a loop by name.

        Args:
            loop_name: The name of the loop
            include_completed: Whether to include completed loops

        Returns:
            The loop information
        """
        logger.debug(f"Loop name: {loop_name}, include_completed: {include_completed}")
        params = (self.execution_id,)
        with self.conn.cursor() as cursor:
            cursor.execute(GET_ALL_LOOPS_POSTGRES, params)
            all_loops = cursor.fetchall()

        logger.debug(f"Loops in database: {all_loops}")
        params = (self.execution_id, loop_name, self.execution_id, loop_name)
        with self.conn.cursor() as cursor:
            if include_completed:
                cursor.execute(FIND_LOOP_INCLUDE_COMPLETED_POSTGRES, params)
            else:
                cursor.execute(FIND_LOOP_EXCLUDE_COMPLETED_POSTGRES, params)
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
        """
        Mark a loop as completed.

        Args:
            loop_id: The ID of the loop
        """
        params = (self.execution_id, loop_id)
        with self.conn.cursor() as cursor:
            cursor.execute(COMPLETE_LOOP_SELECT_POSTGRES, params)
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

    def store_transition(self, params: Tuple):
        """
        Store a transition in the database.

        Args:
            params: The parameters for the transition
        """
        with self.conn.cursor() as cursor:
            cursor.execute(TRANSITION_INSERT_POSTGRES, params)
            self.conn.commit()

    def get_step_results(self) -> Dict[str, Any]:
        """
        Get the results of all steps.

        Returns:
            A dictionary mapping step names to their results
        """
        step_result = {}
        params = (self.execution_id,)
        with self.conn.cursor() as cursor:
            cursor.execute(STEP_RESULTS_SELECT_POSTGRES, params)
            rows = cursor.fetchall()

        for row in rows:
            if row[1]:
                step_result[row[0]] = json.loads(row[1])

        return step_result

    def export_execution_data(self, filepath: str = None):
        """
        Export execution data to a file.

        Args:
            filepath: The path to the file to export to

        Returns:
            The path to the exported file
        """
        if not filepath:
            filepath = f"noetl_execution_{self.execution_id}.json"

        params = (self.execution_id,)
        with self.conn.cursor() as cursor:
            cursor.execute(EXPORT_EXECUTION_DATA_POSTGRES, params)
            rows = cursor.fetchall()

            if rows:
                columns = [desc[0] for desc in cursor.description]
                event_log_data = [dict(zip(columns, row)) for row in rows]

                with open(filepath, 'w') as f:
                    json.dump(event_log_data, f, default=str, indent=2)

                logger.info(f"Execution data exported to {filepath}")
                return filepath

        logger.warning("No data to export")
        return None

    def find_step(self, step_name: str) -> Optional[Dict]:
        """
        Find a step by name.

        Args:
            step_name: The name of the step

        Returns:
            The step configuration
        """
        for step in self.playbook.get('workflow', []):
            if step.get('step') == step_name:
                return step
        return None

    def find_task(self, task_name: str) -> Optional[Dict]:
        """
        Find a task by name.

        Args:
            task_name: The name of the task

        Returns:
            The task configuration
        """
        for task in self.playbook.get('workbook', []):
            if task.get('name') == task_name or task.get('task') == task_name:
                return task
        return None

    def ml_recommendation(self, current_step: str, context: Dict) -> str:
        """
        TODO: future feature. Placeholder for ML recommendation.
        Get a recommendation for the next step using ML.

        Args:
            current_step: The current step
            context: The current context

        Returns:
            The recommended next step
        """
        return None

    def run(self, mlflow: bool = False) -> Dict[str, Any]:
        """
        Run the agent workflow.

        Args:
            mlflow: Flag to use ML flow for workflow control

        Returns:
            A dictionary of workflow results
        """
        from noetl.broker import Broker
        server_url = os.environ.get('NOETL_SERVER_URL', 'http://localhost:8082')
        daemon = Broker(self, server_url=server_url)
        return daemon.run(mlflow)
