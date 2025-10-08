"""
Core EventService and dependency injection functions.
"""

import json
import os
from typing import Dict, Any, List, Optional
from datetime import datetime
from fastapi import HTTPException
from noetl.core.common import get_async_db_connection, get_snowflake_id_str, get_snowflake_id
from noetl.core.logger import setup_logger
from noetl.core.status import validate_status
from noetl.api.routers.event.event_log import EventLog

logger = setup_logger(__name__, include_location=True)


class EventService:
    def __init__(self, pgdb_conn_string: str | None = None):
        pass



    async def get_all_executions(self) -> List[Dict[str, Any]]:
        """
        Get all executions from the event table.

        Returns:
            A list of execution data dictionaries
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        WITH latest_events AS (
                            SELECT 
                                execution_id,
                                MAX(created_at) as latest_timestamp
                            FROM event
                            GROUP BY execution_id
                        )
                        SELECT 
                            e.execution_id,
                            e.catalog_id,
                            e.event_type,
                            e.status,
                            e.created_at,
                            e.meta,
                            e.context,
                            e.result,
                            e.error,
                            e.stack_trace,
                            c.path,
                            c.version
                        FROM event e
                        JOIN latest_events le ON e.execution_id = le.execution_id AND e.created_at = le.latest_timestamp
                        JOIN catalog c on c.catalog_id = e.catalog_id
                        ORDER BY e.created_at DESC
                    """)

                    rows = await cursor.fetchall()
                    executions = []

                    for row in rows:
                        execution_id = row[0]
                        # catalog_id = row[1]
                        # metadata = row[5] if row[5] else {}  # meta is now JSONB
                        # input_context = json.loads(row[6]) if row[6] else {}
                        output_result = json.loads(row[7]) if row[7] else {}
                        
                        # Try to get playbook info from catalog_id first, then fallback to metadata
                        playbook_id = row[10]
                        playbook_name = playbook_id.split('/')[-1] if playbook_id else 'Unknown'
                       
                    
                        
                        raw_status = row[3]
                        
                        # For existing data, we need to handle potentially non-normalized statuses
                        # by normalizing them only for display purposes, but log warnings
                        if raw_status and raw_status in {'STARTED', 'RUNNING', 'PAUSED', 'PENDING', 'FAILED', 'COMPLETED'}:
                            status = raw_status
                        else:
                            # Legacy data - normalize for display but log warning
                            from noetl.core.status import normalize_status
                            try:
                                status = normalize_status(raw_status)
                                logger.warning(f"Found non-normalized status '{raw_status}' in execution {execution_id}. This should be fixed in the source.")
                            except ValueError:
                                logger.error(f"Invalid status '{raw_status}' in execution {execution_id}. Defaulting to 'PENDING'.")
                                status = 'PENDING'

                        start_time = row[4].isoformat() if row[4] else None
                        end_time = None
                        duration = None

                        await cursor.execute("""
                            SELECT MIN(created_at) FROM event WHERE execution_id = %s
                        """, (execution_id,))
                        min_time_row = await cursor.fetchone()
                        if min_time_row and min_time_row[0]:
                            start_time = min_time_row[0].isoformat()

                        if status in ['completed', 'failed']:
                            await cursor.execute("""
                                SELECT MAX(created_at) FROM event WHERE execution_id = %s
                            """, (execution_id,))
                            max_time_row = await cursor.fetchone()
                            if max_time_row and max_time_row[0]:
                                end_time = max_time_row[0].isoformat()

                                if start_time:
                                    start_dt = datetime.fromisoformat(start_time)
                                    end_dt = datetime.fromisoformat(end_time)
                                    duration = (end_dt - start_dt).total_seconds()

                        progress = 100 if status in ['COMPLETED', 'FAILED'] else 0
                        if status in ['STARTED', 'RUNNING']:
                            # Count total events & those considered finished (completed/failed)
                            await cursor.execute("""
                                SELECT status FROM event WHERE execution_id = %s
                            """, (execution_id,))
                            event_statuses = []
                            for r in await cursor.fetchall():
                                event_status = r[0]
                                if event_status and event_status in {'STARTED', 'RUNNING', 'PAUSED', 'PENDING', 'FAILED', 'COMPLETED'}:
                                    event_statuses.append(event_status)
                                else:
                                    # Legacy data - normalize for calculation
                                    from noetl.core.status import normalize_status
                                    try:
                                        normalized = normalize_status(event_status)
                                        event_statuses.append(normalized)
                                    except ValueError:
                                        event_statuses.append('PENDING')
                            total_steps = len(event_statuses)
                            completed_steps = sum(1 for s in event_statuses if s in {'COMPLETED', 'FAILED'})
                            if total_steps > 0:
                                progress = int((completed_steps / total_steps) * 100)

                        execution_data = {
                            "id": execution_id,
                            "playbook_id": playbook_id,
                            "playbook_name": playbook_name,
                            "status": status,
                            "start_time": start_time,
                            "end_time": end_time,
                            "duration": duration,
                            "progress": progress,
                            "result": output_result,
                            "error": row[8]
                        }

                        # Attach stack trace when present
                        try:
                            st = row[9]
                            if st:
                                execution_data['stack_trace'] = st
                        except Exception:
                            pass
                        executions.append(execution_data)

                    return executions

        except Exception as e:
            logger.exception(f"Error getting all executions: {e}")
            return []

    async def emit(self, event_data: Dict[str, Any]) -> Dict[str, Any]:
        logger.info(f"EVENT_SERVICE_EMIT: Called with event_type={event_data.get('event_type')} execution_id={event_data.get('execution_id')}")
        try:
            # Generate event_id using snowflake when not provided
            try:
                snow = get_snowflake_id_str()
            except Exception as e:
                logger.debug(f"String snowflake ID generation failed: {e}")
                try:
                    snow = str(get_snowflake_id())
                except Exception as e2:
                    logger.warning(f"Numeric snowflake ID generation failed: {e2}")
                    snow = None
            event_id = event_data.get("event_id", snow or f"evt_{os.urandom(16).hex()}")
            event_data["event_id"] = event_id
            event_type = event_data.get("event_type", "UNKNOWN")
            raw_status = event_data.get("status", "PENDING")
            
            # Validate status - this will raise ValueError if invalid
            try:
                status = validate_status(raw_status) if raw_status in {'STARTED', 'RUNNING', 'PAUSED', 'PENDING', 'FAILED', 'COMPLETED'} else validate_status('PENDING')
            except ValueError as e:
                logger.error(f"Invalid status '{raw_status}' in event: {e}")
                raise ValueError(f"Invalid event status '{raw_status}'. {str(e)}")
            
            parent_event_id = event_data.get("parent_id") or event_data.get("parent_event_id")
            execution_id = event_data.get("execution_id", event_id)
            node_id = event_data.get("node_id", event_id)
            node_name = event_data.get("node_name") or event_type
            node_type = event_data.get("node_type", "event")
            duration = event_data.get("duration", 0.0)
            metadata = event_data.get("meta", {})
            trace_component = event_data.get("trace_component")
            error = event_data.get("error")
            if error and not isinstance(error, str):
                error = json.dumps(error)
            traceback_text = event_data.get("traceback")
            context_dict = event_data.get("context", {})
            # Accept either 'result' (preferred) or legacy 'output_result' key from callers
            result_dict = event_data.get("result", {})
            if (not result_dict) and (event_data.get("output_result") is not None):
                result_dict = event_data.get("output_result")
            context = json.dumps(context_dict)
            result = json.dumps(result_dict)

            if not parent_event_id:
                try:
                    meta_sources = []
                    if isinstance(context_dict, dict):
                        meta_sources.append(context_dict.get('_meta'))
                        work_ctx = context_dict.get('work')
                        if isinstance(work_ctx, dict):
                            meta_sources.append(work_ctx.get('_meta'))
                        workload_ctx = context_dict.get('workload')
                        if isinstance(workload_ctx, dict):
                            meta_sources.append(workload_ctx.get('_meta'))
                    for meta in meta_sources:
                        if isinstance(meta, dict) and meta.get('parent_event_id'):
                            parent_event_id = meta.get('parent_event_id')
                            break
                except Exception:
                    parent_event_id = parent_event_id

            # Derive better node_name/node_type when missing using context
            try:
                # Infer node_name from context when absent or generic
                if (not node_name) or (node_name == event_type) or (str(node_name).lower() == 'unknown'):
                    if isinstance(context_dict, dict):
                        work_ctx = context_dict.get('work') or context_dict.get('workload') or {}
                        step_nm = None
                        if isinstance(work_ctx, dict):
                            step_nm = work_ctx.get('step_name') or work_ctx.get('step') or work_ctx.get('name')
                        step_nm = step_nm or context_dict.get('step_name') or context_dict.get('step') or context_dict.get('name')
                        if step_nm:
                            node_name = str(step_nm)
                # Infer node_type when absent/unknown/event
                nt_lower = str(node_type or '').lower()
                if (not node_type) or (nt_lower in ('event', 'unknown', '')):
                    inferred_type = None
                    if isinstance(context_dict, dict):
                        # If a task section is present, it's a task step
                        task_ctx = context_dict.get('task')
                        if isinstance(task_ctx, dict):
                            inferred_type = 'task'
                        else:
                            work_ctx = context_dict.get('work') or context_dict.get('workload') or {}
                            if isinstance(work_ctx, dict) and isinstance(work_ctx.get('_loop'), dict):
                                inferred_type = 'loop' if str(event_type or '').lower().startswith('loop') else 'task'
                    # Fall back to event_type prefixes
                    et = str(event_type or '').lower()
                    if not inferred_type:
                        if et in {'execution_start', 'execution_started', 'start', 'execution_completed', 'execution_complete'}:
                            inferred_type = 'playbook'
                        elif et.startswith('action_'):
                            inferred_type = 'task'
                        elif et.startswith('loop_'):
                            inferred_type = 'loop'
                        elif et == 'result':
                            inferred_type = 'task'
                    node_type = inferred_type or node_type or 'event'
            except Exception:
                pass
            
            # DEBUG: Log what we're actually storing
            logger.debug(f"EMIT_DEBUG: event_type={event_type}, context_dict={context_dict}, context_json_length={len(context)}")
            metadata_str = json.dumps(metadata)
            trace_component_str = json.dumps(trace_component) if trace_component is not None else None

            async with get_async_db_connection() as conn:
                try:
                    async with conn.cursor() as cursor:
                      # Dedupe guards for common marker events to prevent duplicate spam
                      try:
                          et_l = (str(event_type) if event_type is not None else '').lower()
                          if et_l == 'step_started':
                              await cursor.execute(
                                  """
                                  SELECT 1 FROM event
                                  WHERE execution_id = %s AND node_name = %s AND event_type = 'step_started'
                                  LIMIT 1
                                  """,
                                  (execution_id, node_name)
                              )
                              if await cursor.fetchone():
                                  # Skip duplicate insert and scheduling
                                  return event_data
                          if et_l == 'loop_iteration':
                              # When current_index is present, dedupe by (execution_id, node_name, current_index)
                              try:
                                  _ci_val = event_data.get('current_index')
                              except Exception:
                                  _ci_val = None
                              _idx_txt = str(_ci_val) if (_ci_val is not None) else None
                              if _idx_txt is not None:
                                  await cursor.execute(
                                      """
                                  SELECT 1 FROM event
                                      WHERE execution_id = %s AND node_name = %s AND event_type = 'loop_iteration'
                                        AND current_index::text = %s
                                      LIMIT 1
                                      """,
                                      (execution_id, node_name, _idx_txt)
                                  )
                                  if await cursor.fetchone():
                                      return event_data
                      except Exception:
                          logger.debug("EMIT: dedupe guard failed; proceeding with insert", exc_info=True)
                      # Default parent_event_id if missing: link to previous event in the same execution
                      if not parent_event_id:
                          try:
                              await cursor.execute("SELECT event_id FROM event WHERE execution_id = %s ORDER BY created_at DESC LIMIT 1", (execution_id,))
                              _prev = await cursor.fetchone()
                              if _prev and _prev[0]:
                                  parent_event_id = _prev[0]
                          except Exception:
                              pass

                      # Resolve catalog_id from metadata if available - REQUIRED
                      catalog_id = None
                      try:
                          # First try metadata
                          if metadata and isinstance(metadata, dict):
                              resource_path = metadata.get('path')
                              resource_version = metadata.get('version')
                              if resource_path and resource_version:
                                  await cursor.execute(
                                      "SELECT catalog_id FROM noetl.catalog WHERE path = %s AND version = %s",
                                      (resource_path, resource_version)
                                  )
                                  catalog_row = await cursor.fetchone()
                                  if catalog_row:
                                      catalog_id = catalog_row[0]
                          
                          # If not found in metadata, try context directly
                          if not catalog_id and context_dict and isinstance(context_dict, dict):
                              # Check direct path/version in context
                              ctx_path = context_dict.get('path')
                              ctx_version = context_dict.get('version')
                              if ctx_path and ctx_version:
                                  await cursor.execute(
                                      "SELECT catalog_id FROM noetl.catalog WHERE path = %s AND version = %s",
                                      (ctx_path, ctx_version)
                                  )
                                  catalog_row = await cursor.fetchone()
                                  if catalog_row:
                                      catalog_id = catalog_row[0]
                              
                              # Also check nested workload/work contexts
                              if not catalog_id:
                                  for ctx_key in ['work', 'workload']:
                                      ctx_data = context_dict.get(ctx_key)
                                      if isinstance(ctx_data, dict):
                                          ctx_path = ctx_data.get('path')
                                          ctx_version = ctx_data.get('version')
                                          if ctx_path and ctx_version:
                                              await cursor.execute(
                                                  "SELECT catalog_id FROM noetl.catalog WHERE path = %s AND version = %s",
                                                  (ctx_path, ctx_version)
                                              )
                                              catalog_row = await cursor.fetchone()
                                              if catalog_row:
                                                  catalog_id = catalog_row[0]
                                                  break
                          
                          # catalog_id is REQUIRED - fail if not found
                          if catalog_id is None:
                              error_msg = f"catalog_id is required but could not be resolved for event {event_type} in execution {execution_id}. Available metadata: {metadata}, context keys: {list(context_dict.keys()) if context_dict else 'None'}"
                              logger.error(error_msg)
                              raise ValueError(error_msg)
                              
                      except ValueError:
                          # Re-raise validation errors
                          raise
                      except Exception as e:
                          error_msg = f"Failed to resolve catalog_id for event {event_type} in execution {execution_id}: {e}"
                          logger.error(error_msg)
                          raise ValueError(error_msg)
                      await cursor.execute("""
                          SELECT COUNT(*) FROM event
                          WHERE execution_id = %s AND event_id = %s
                      """, (execution_id, event_id))

                      row = await cursor.fetchone()
                      exists = row[0] > 0 if row else False

                      # Iterator processing for type: iterator steps
                      # Remove old loop_id/loop_name processing since those columns are removed
                      
                      iterator_val = json.dumps(event_data.get('iterator')) if event_data.get('iterator') is not None else None
                      
                      current_index_val = event_data.get('current_index')
                      if current_index_val is not None and not isinstance(current_index_val, (str, int)):
                          current_index_val = json.dumps(current_index_val)
                      elif current_index_val is not None:
                          current_index_val = str(current_index_val)
                      
                      current_item_val = json.dumps(event_data.get('current_item')) if event_data.get('current_item') is not None else None
                      
                      # Enhanced iterator metadata extraction: check context for iterator info
                      if context_dict and isinstance(context_dict, dict):
                          # Support both 'workload' (server) and 'work' (worker) context keys
                          workload = context_dict.get('workload')
                          work = context_dict.get('work')
                          candidate_contexts = []
                          if workload and isinstance(workload, dict):
                              candidate_contexts.append(workload)
                          if work and isinstance(work, dict):
                              candidate_contexts.append(work)
                          
                          # Extract iterator information from context
                          for cctx in candidate_contexts:
                              if isinstance(cctx, dict) and isinstance(cctx.get('_iterator'), dict):
                                  iter_data = cctx.get('_iterator')
                                  if current_index_val is None:
                                      current_index_val = iter_data.get('index')
                                  if current_item_val is None:
                                      current_item_val = json.dumps(iter_data.get('item')) if iter_data.get('item') is not None else None
                                  if iterator_val is None:
                                      iterator_val = json.dumps(iter_data.get('collection')) if iter_data.get('collection') is not None else None
                                  break
                      
                      # Extract parent_execution_id from metadata or event_data
                      parent_execution_id = None
                      if metadata and isinstance(metadata, dict):
                          parent_execution_id = metadata.get('parent_execution_id')
                      if not parent_execution_id:
                          parent_execution_id = event_data.get('parent_execution_id')
                      if not parent_execution_id and metadata and isinstance(metadata, dict):
                          # Convert string to int if needed for bigint
                          parent_exec_str = metadata.get('parent_execution_id')
                          if parent_exec_str:
                              try:
                                  parent_execution_id = int(parent_exec_str)
                              except (ValueError, TypeError):
                                  pass
                      
                      # Extract parent_execution_id from metadata or event_data
                      parent_execution_id = None
                      if metadata and isinstance(metadata, dict):
                          parent_execution_id = metadata.get('parent_execution_id')
                      if not parent_execution_id:
                          parent_execution_id = event_data.get('parent_execution_id')
                      if not parent_execution_id and metadata and isinstance(metadata, dict):
                          # Convert string to int if needed for bigint
                          parent_exec_str = metadata.get('parent_execution_id')
                          if parent_exec_str:
                              try:
                                  parent_execution_id = int(parent_exec_str)
                              except (ValueError, TypeError):
                                  pass

                      if exists:
                          await cursor.execute("""
                              UPDATE event SET
                                  catalog_id = %s,
                                  event_type = %s,
                                  status = %s,
                                  duration = %s,
                                  context = %s,
                                  result = %s,
                                  meta = %s::jsonb,
                                  error = %s,
                                  trace_component = %s::jsonb,
                                  current_index = %s,
                                  current_item = %s::jsonb,
                                  created_at = CURRENT_TIMESTAMP
                              WHERE execution_id = %s AND event_id = %s
                          """, (
                              catalog_id,
                              event_type,
                              status,
                              duration,
                              context,
                              result,
                              metadata_str,
                              error,
                              trace_component_str,
                              current_index_val,
                              current_item_val,
                              execution_id,
                              event_id
                          ))
                      else:
                          # DEBUG: Log what we're about to insert
                          logger.debug(f"EMIT_DB_INSERT: About to insert execution_id={execution_id}, event_id={event_id}, context_length={len(context) if context else 0}, context_preview={context[:100] if context and isinstance(context, str) else 'None'}")
                          logger.debug(f"EMIT_DB_INSERT_PARAMS: execution_id={type(execution_id)}, event_id={type(event_id)}, parent_event_id={type(parent_event_id)}, event_type={type(event_type)}")
                          logger.debug(f"EMIT_DB_INSERT_PARAMS: context={type(context)}, result={type(result)}, metadata_str={type(metadata_str)}, error={type(error)}")
                          logger.debug(f"EMIT_DB_INSERT_PARAMS: iterator_val={type(iterator_val)}, current_index_val={type(current_index_val)}, current_item_val={type(current_item_val)}")

                          # Insert event via storage layer
                          await EventLog().insert_event(
                              execution_id=execution_id,
                              event_id=event_id,
                              parent_event_id=parent_event_id,
                              parent_execution_id=parent_execution_id,
                              catalog_id=catalog_id,
                              event_type=event_type,
                              node_id=node_id,
                              node_name=node_name,
                              node_type=node_type,
                              status=status,
                              duration=duration,
                              context_json=context,
                              result_json=result,
                              metadata_json=metadata_str,
                              error_text=error,
                              trace_component_json=trace_component_str,
                              current_index=current_index_val,
                              current_item_json=current_item_val,
                              stack_trace=traceback_text,
                          )

                      try:
                          status_l = (str(status) if status is not None else '').lower()
                          evt_l = (str(event_type) if event_type is not None else '').lower()
                          is_error = ("error" in status_l) or ("failed" in status_l) or ("error" in evt_l) or (error is not None)
                          if is_error:
                              from noetl.core.dsl.schema import DatabaseSchema
                              ds = DatabaseSchema(auto_setup=False)
                              err_type = event_type or 'action_error'
                              err_msg = str(error) if error is not None else 'Unknown error'
                              await ds.log_error_async(
                                  error_type=err_type,
                                  error_message=err_msg,
                                  execution_id=execution_id,
                                  step_id=node_id,
                                  step_name=node_name,
                                  template_string=None,
                                  context_data=context_dict,
                                  stack_trace=traceback_text,
                                  input_data=context_dict,
                                  output_data=result_dict,
                                  severity='error'
                              )
                      except Exception:
                          pass

                      try:
                          if str(event_type).lower() in {"execution_start", "execution_started", "start"}:
                              try:
                                  await cursor.execute(
                                      """
                                      INSERT INTO workload (execution_id, data)
                                      VALUES (%s, %s)
                                      ON CONFLICT (execution_id) DO UPDATE SET data = EXCLUDED.data
                                      """,
                                      (execution_id, context)
                                  )
                              except Exception:
                                  pass
                      except Exception:
                          pass

                      await conn.commit()
                      # Control dispatcher: route event to specialized controllers (best-effort)
                      try:
                          from .control import route_event
                          event_data['trigger_event_id'] = event_id
                          await route_event(event_data)
                      except Exception:
                          logger.debug("EVENT_SERVICE_EMIT: route_event failed", exc_info=True)
                except Exception as db_error:
                    logger.error(f"Database error in emit: {db_error}", exc_info=True)
                    try:
                        await conn.rollback()
                    except Exception:
                        pass
                    # Best-effort error_log entry even if event insert failed
                    try:
                        from noetl.core.dsl.schema import DatabaseSchema
                        ds = DatabaseSchema(auto_setup=False)
                        await ds.log_error_async(
                            error_type='event_emit_error',
                            error_message=str(db_error),
                            execution_id=str(event_data.get('execution_id') or ''),
                            step_id=str(event_data.get('node_id') or ''),
                            step_name=str(event_data.get('node_name') or ''),
                            template_string=None,
                            context_data=event_data.get('context'),
                            stack_trace=None,
                            input_data=event_data,
                            output_data=None,
                            severity='error'
                        )
                    except Exception:
                        pass
                    raise

            logger.info(f"Event emitted: {event_id} - {event_type} - {status}")

            # Check if this is a child execution completion event and handle completion logic
            if event_type in ['execution_completed', 'execution_complete']:
                print(f"[PRINT DEBUG] Processing completion event for execution {execution_id}")
                logger.info(f"COMPLETION_HANDLER: Processing completion event for execution {execution_id}")
                logger.info(f"COMPLETION_HANDLER: Event data: {event_data}")
                try:
                    meta = metadata if isinstance(metadata, dict) else {}
                    logger.info(f"COMPLETION_HANDLER: Meta data: {meta}")
                    parent_execution_id = meta.get('parent_execution_id') or event_data.get('parent_execution_id')
                    parent_step = meta.get('parent_step')
                    exec_id = execution_id
                    logger.info(f"COMPLETION_HANDLER: parent_execution_id={parent_execution_id}, parent_step={parent_step}, exec_id={exec_id}")
                    
                    if parent_execution_id and exec_id and parent_execution_id != exec_id:
                        # If parent_step is not in metadata, derive it from result events sent to parent
                        if not parent_step:
                            try:
                                async with get_async_db_connection() as conn:
                                    async with conn.cursor() as cur:
                                        # Find parent_step from result events sent back to parent for this child
                                        await cur.execute(
                                            """
                                            SELECT context::json->>'parent_step' as parent_step
                                            FROM noetl.event
                                            WHERE execution_id = %s
                                              AND event_type = 'result'
                                              AND context LIKE %s
                                              AND context::json->>'parent_step' IS NOT NULL
                                            LIMIT 1
                                            """,
                                            (parent_execution_id, f'%"child_execution_id": "{exec_id}"%')
                                        )
                                        row = await cur.fetchone()
                                        if row and row[0]:
                                            parent_step = row[0]
                            except Exception:
                                logger.debug("Failed to derive parent_step from result events", exc_info=True)
                        
                        if parent_step:
                            logger.info(f"COMPLETION_HANDLER: Child execution {exec_id} completed for parent {parent_execution_id} step {parent_step}")
                            print(f"completion handler: about to extract result for {exec_id}")
                            
                            # Extract the child execution result 
                            try:
                                async with get_async_db_connection() as conn:
                                    async with conn.cursor() as cur:
                                        # Get the final result from the most recent action_completed event
                                        await cur.execute(
                                            """
                                            SELECT result, context
                                            FROM noetl.event
                                            WHERE execution_id = %s
                                              AND event_type = 'action_completed'
                                              AND result IS NOT NULL
                                              AND result != '{}'
                                              AND result != 'null'
                                            ORDER BY created_at DESC
                                            LIMIT 1
                                            """,
                                            (exec_id,)
                                        )
                                        result_row = await cur.fetchone()
                                        child_result = {}
                                        if result_row and result_row[0]:
                                            try:
                                                child_result = json.loads(result_row[0])
                                            except:
                                                child_result = {"raw_result": result_row[0]}
                                                
                                        logger.info(f"COMPLETION_HANDLER: Extracted result for child {exec_id}: {child_result}")
                                        
                                        # Get loop metadata from workload
                                        loop_metadata = {}
                                        try:
                                            await cur.execute(
                                                "SELECT data FROM noetl.workload WHERE execution_id = %s",
                                                (exec_id,)
                                            )
                                            workload_row = await cur.fetchone()
                                            if workload_row and workload_row[0]:
                                                workload_data = json.loads(workload_row[0])
                                                iterator_data = workload_data.get('_iterator', {})
                                                if iterator_data:
                                                    loop_metadata = {
                                                        'current_index': iterator_data.get('current_index'),
                                                        'current_item': iterator_data.get('current_item')
                                                    }
                                        except Exception as e:
                                            logger.debug(f"Failed to extract loop metadata: {e}")
                                        
                                        # Emit action_completed event to parent
                                        await self.emit({
                                            'event_type': 'action_completed',
                                            'execution_id': parent_execution_id,
                                            'node_id': parent_step,
                                            'node_name': parent_step,
                                            'node_type': 'distributed_task',
                                            'status': 'completed',
                                            'result': child_result,
                                            'context': {
                                                'child_execution_id': exec_id,
                                                'distributed': True,
                                                'parent_step': parent_step,
                                                **loop_metadata
                                            }
                                        })
                                        
                                        logger.info(f"COMPLETION_HANDLER: Emitted action_completed for parent {parent_execution_id} step {parent_step} from child {exec_id} with result: {child_result} and loop metadata: {loop_metadata}")
                                        
                                        logger.info(f"COMPLETION_HANDLER: Calling distributed loop completion check for parent {parent_execution_id} step {parent_step}")
                                        
                                        # Check if this completes a distributed loop
                                        try:
                                            from .processing import _check_distributed_loop_completion
                                            await _check_distributed_loop_completion(parent_execution_id, parent_step)
                                            logger.info(f"COMPLETION_HANDLER: Distributed loop completion check completed for parent {parent_execution_id} step {parent_step}")
                                        except Exception as e:
                                            logger.error(f"COMPLETION_HANDLER: Error in distributed loop completion check: {e}", exc_info=True)
                                        
                            except Exception as e:
                                logger.error(f"COMPLETION_HANDLER: Error processing child completion: {e}", exc_info=True)
                                
                except Exception as e:
                    logger.error(f"COMPLETION_HANDLER: Error in completion handler: {e}", exc_info=True)

            # Notify central BrokerService that an event has been persisted (non-blocking)
            try:
                from noetl.api.routers.broker import get_broker_service
                get_broker_service().on_event_persisted(event_data)
            except Exception:
                logger.debug("Failed to notify BrokerService.on_event_persisted", exc_info=True)

            try:
                evt_l = (str(event_type) if event_type is not None else '').lower()
                # Re-evaluate broker on key lifecycle events, including task completion/errors (legacy fast path)
                if evt_l in {"execution_start", "action_completed", "action_error", "task_completed", "task_error", "loop_iteration", "loop_completed", "result"}:
                    logger.info(f"EVENT_EMIT: Triggering broker evaluation for execution {execution_id} due to event_type: {evt_l}")
                    try:
                        import asyncio
                        from .processing import evaluate_broker_for_execution
                        if asyncio.get_event_loop().is_running():
                            asyncio.create_task(evaluate_broker_for_execution(execution_id))
                        else:
                            await evaluate_broker_for_execution(execution_id)
                    except RuntimeError:
                        from .processing import evaluate_broker_for_execution
                        await evaluate_broker_for_execution(execution_id)
            except Exception:
                logger.debug("Failed to schedule broker evaluation from emit", exc_info=True)

            return event_data

        except Exception as e:
            logger.exception(f"Error emitting event: {e}")
            raise HTTPException(
                status_code=500,
                detail=f"Error emitting event: {e}"
            )

    async def get_events_by_execution_id(self, execution_id: str) -> Optional[Dict[str, Any]]:
        """
        Get all events for a specific execution.

        Args:
            execution_id: The ID of the execution

        Returns:
            A dictionary containing events or None if not found
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        SELECT 
                            event_id, 
                            event_type, 
                            node_id, 
                            node_name, 
                            node_type, 
                            status, 
                            duration, 
                            timestamp, 
                            context, 
                            result, 
                            meta, 
                            error,
                            catalog_id
                        FROM event 
                        WHERE execution_id = %s
                        ORDER BY created_at
                    """, (execution_id,))

                    rows = await cursor.fetchall()
                    if rows:
                        events = []
                        for row in rows:
                            event_data = {
                                "event_id": row[0],
                                "event_type": row[1],
                                "node_id": row[2],
                                "node_name": row[3],
                                "node_type": row[4],
                                "status": row[5],
                                "duration": row[6],
                                "timestamp": row[7].isoformat() if row[7] else None,
                                # Store in canonical keys
                                "context": json.loads(row[8]) if row[8] else None,
                                "result": json.loads(row[9]) if row[9] else None,
                                "metadata": row[10] if row[10] else None,  # meta is now JSONB
                                "error": row[11],
                                "catalog_id": row[12],
                                "execution_id": execution_id,
                                "resource_path": None,
                                "resource_version": None,
                            }
                            
                            # Add normalized_status for backwards compatibility
                            # For existing data, handle potentially non-normalized statuses
                            raw_status = row[5]
                            if raw_status and raw_status in {'STARTED', 'RUNNING', 'PAUSED', 'PENDING', 'FAILED', 'COMPLETED'}:
                                event_data["normalized_status"] = raw_status
                            else:
                                # Legacy data - normalize for compatibility
                                from noetl.core.status import normalize_status
                                try:
                                    event_data["normalized_status"] = normalize_status(raw_status)
                                    logger.warning(f"Found non-normalized status '{raw_status}' in event {row[0]}. This should be fixed in the source.")
                                except ValueError:
                                    logger.error(f"Invalid status '{raw_status}' in event {row[0]}. Defaulting to 'PENDING'.")
                                    event_data["normalized_status"] = 'PENDING'
                            # Backward/consumer compatibility: also expose legacy alias keys
                            try:
                                event_data["input_context"] = event_data.get("context")
                                event_data["output_result"] = event_data.get("result")
                            except Exception:
                                pass

                            # Use new schema field names directly
                            # No backward compatibility mappings needed

                            events.append(event_data)

                        return {"events": events}

                    return None
        except Exception as e:
            logger.exception(f"Error getting events by execution_id: {e}")
            return None

    async def get_event_by_id(self, event_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a single event by its ID.

        Args:
            event_id: The ID of the event

        Returns:
            A dictionary containing the event or None if not found
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        SELECT 
                            event_id, 
                            event_type, 
                            node_id, 
                            node_name, 
                            node_type, 
                            status, 
                            duration, 
                            timestamp, 
                            context, 
                            result, 
                            meta, 
                            error,
                            stack_trace,
                            execution_id,
                            catalog_id
                        FROM event 
                        WHERE event_id = %s
                    """, (event_id,))

                    row = await cursor.fetchone()
                    if row:
                        event_data = {
                            "event_id": row[0],
                            "event_type": row[1],
                            "node_id": row[2],
                            "node_name": row[3],
                            "node_type": row[4],
                            "status": row[5],
                            "duration": row[6],
                            "timestamp": row[7].isoformat() if row[7] else None,
                            "context": json.loads(row[8]) if row[8] else None,
                            "result": json.loads(row[9]) if row[9] else None,
                            "metadata": row[10] if row[10] else None,  # meta is now JSONB
                            "error": row[11],
                            "stack_trace": row[12],
                            "execution_id": row[13],
                            "catalog_id": row[14],
                            "resource_path": None,
                            "resource_version": None
                        }
                        # Backward/consumer compatibility: alias keys
                        try:
                            event_data["input_context"] = event_data.get("context")
                            event_data["output_result"] = event_data.get("result")
                        except Exception:
                            pass
                        # Use new schema field names directly
                        # No backward compatibility mappings needed
                        return {"events": [event_data]}

                    return None
        except Exception as e:
            logger.exception(f"Error getting event by ID: {e}")
            return None

    async def get_event(self, id_param: str) -> Optional[Dict[str, Any]]:
        """
        Get events by execution_id or event_id (legacy method for backward compatibility).

        Args:
            id_param: Either an execution_id or an event_id

        Returns:
            A dictionary containing events or None if not found
        """
        try:
            async with get_async_db_connection() as conn:
                async with conn.cursor() as cursor:
                    await cursor.execute("""
                        SELECT COUNT(*) FROM event WHERE execution_id = %s
                    """, (id_param,))
                    row = await cursor.fetchone()
                    count = row[0] if row else 0

                    if count > 0:
                        events = await self.get_events_by_execution_id(id_param)
                        if events:
                            return events

                event = await self.get_event_by_id(id_param)
                if event:
                    return event

                async with get_async_db_connection() as conn:
                    async with conn.cursor() as cursor:
                        await cursor.execute("""
                            SELECT DISTINCT execution_id FROM event
                            WHERE event_id = %s
                        """, (id_param,))
                        execution_ids = [row[0] for row in await cursor.fetchall()]

                        if execution_ids:
                            events = await self.get_events_by_execution_id(execution_ids[0])
                            if events:
                                return events

                return None
        except Exception as e:
            logger.exception(f"Error in get_event: {e}")
            return None


def get_event_service() -> EventService:
    return EventService()


def get_event_service_dependency() -> EventService:
    return EventService()
