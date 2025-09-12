"""
Workflow database management functions.
Handles populating workflow, transition, and workbook tables.
"""

import json
from typing import Any, Dict
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


async def populate_workflow_tables(cursor, execution_id: str, playbook_path: str, playbook: Dict[str, Any]) -> None:
    """
    Populate workflow, transition, and workbook tables for the given execution.
    
    Args:
        cursor: Database cursor
        execution_id: Execution ID 
        playbook_path: Path to the playbook
        playbook: Parsed playbook content
    """
    try:
        # Get workflow steps
        workflow_steps = playbook.get('workflow', []) or playbook.get('steps', [])
        if not workflow_steps:
            return
            
        # Insert workflow steps
        for step in workflow_steps:
            step_name = step.get('step') or step.get('name')
            if not step_name:
                continue
                
            step_id = step.get('id') or step_name
            description = step.get('description')
            await cursor.execute(
                """
                INSERT INTO noetl.workflow (execution_id, step_id, step_name, step_type, description, raw_config)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT (execution_id, step_id) DO NOTHING
                """,
                (
                    execution_id,
                    step_id,
                    step_name,
                    step.get('type', 'unknown'),
                    description,
                    json.dumps(step)
                )
            )
            
            # Insert transitions for this step
            next_steps = step.get('next', [])
            if not isinstance(next_steps, list):
                next_steps = [next_steps] if next_steps else []
                
            for next_def in next_steps:
                if isinstance(next_def, dict):
                    next_step_name = next_def.get('step') or next_def.get('name')
                    condition = next_def.get('when') or next_def.get('pass')
                    with_data = next_def.get('with')
                elif isinstance(next_def, str):
                    next_step_name = next_def
                    condition = None
                    with_data = None
                else:
                    continue
                    
                if next_step_name:
                    await cursor.execute(
                        """
                        INSERT INTO noetl.transition (execution_id, from_step, to_step, condition_expr, with_data)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (execution_id, from_step, to_step) DO NOTHING
                        """,
                        (
                            execution_id,
                            step_name,
                            next_step_name,
                            json.dumps(condition) if condition else None,
                            json.dumps(with_data) if with_data else None
                        )
                    )
        
        # Insert workbook entry
        await cursor.execute(
            """
            INSERT INTO noetl.workbook (execution_id, playbook_path, content)
            VALUES (%s, %s, %s)
            ON CONFLICT (execution_id) DO NOTHING
            """,
            (
                execution_id,
                playbook_path,
                json.dumps(playbook)
            )
        )
        
    except Exception as e:
        logger.error(f"Error populating workflow tables for {execution_id}: {e}")
        # Re-raise to allow outer logic to rollback aborted transaction before continuing
        raise