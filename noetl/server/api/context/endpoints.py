"""
Context API endpoints.
"""

from typing import Any, Dict
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse

from noetl.core.logger import setup_logger
from .service import render_context

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.post("/context/render", response_class=JSONResponse)
async def render_context_endpoint(request: Request) -> Dict[str, Any]:
    """
    Render a Jinja2 template/object against the server-side execution context.
    
    Context is composed from the database:
    - work/workload: From earliest event context
    - results: Map of step_name -> result for all prior completed steps
    - Direct step references: Results accessible by step name
    - Workbook aliases: Workbook task results aliased under workflow step names
    
    Request body:
        execution_id: Execution ID to fetch context for
        template: Template to render (can be any JSON structure)
        extra_context: Optional additional context to merge
        strict: Optional whether to use strict undefined handling (default: True)
    
    Returns:
        JSON response with:
        - status: "ok" on success
        - rendered: Rendered template result
        - context_keys: List of available context keys
    
    Raises:
        HTTPException: On validation or rendering errors
    """
    try:
        body = await request.json()
        execution_id = body.get("execution_id")
        template = body.get("template")
        extra_context = body.get("extra_context")
        strict = body.get("strict", True)
        
        logger.info(f"Received render request for execution {execution_id}")
        
        # Validate required fields
        if not execution_id:
            raise HTTPException(status_code=400, detail="execution_id is required")
        if "template" not in body:
            raise HTTPException(status_code=400, detail="template is required")
        
        # Render template
        rendered, context_keys = await render_context(
            execution_id=execution_id,
            template=template,
            extra_context=extra_context,
            strict=strict
        )
        
        return {
            "status": "ok",
            "rendered": rendered,
            "context_keys": context_keys
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error rendering context: {e}")
        raise HTTPException(status_code=500, detail=str(e))
