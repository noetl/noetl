"""
Iterator configuration extraction and validation.

Handles extracting and validating configuration from task_config,
including collection resolution, filtering, sorting, and execution mode.
"""

from typing import Dict, Any, Optional, List, Tuple
from jinja2 import Environment

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger
from .utils import coerce_items, truthy

logger = setup_logger(__name__, include_location=True)


def candidate_keys(name: Optional[str]) -> List[str]:
    """
    Generate candidate collection key names from element name.
    
    Args:
        name: Element name (e.g., 'item')
        
    Returns:
        List of candidate keys (e.g., ['item', 'items', 'item_list', 'item_items'])
    """
    if not name:
        return []
    
    base = str(name)
    return [
        base,
        f"{base}s",
        f"{base}_list",
        f"{base}_items",
    ]


def extract_from_mapping(
    mapping: Any, 
    name_keys: List[str]
) -> Optional[Any]:
    """
    Extract collection from mapping using candidate keys.
    
    Args:
        mapping: Dictionary or other object to search
        name_keys: List of candidate keys to try
        
    Returns:
        Collection value or None if not found
    """
    if not isinstance(mapping, dict):
        return None
    
    # Try name-based keys first, then fallback keys
    for key in name_keys + ['items', 'values', 'collection']:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    
    # Single-entry dict: treat sole value as the collection
    if len(mapping) == 1:
        return next(iter(mapping.values()))
    
    return None


def resolve_collection(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    task_with: Dict[str, Any],
    iterator_name: str
) -> Any:
    """
    Resolve collection expression from various sources.
    
    Tries in order:
    1. task_config['collection'] or task_config['data']
    2. task_with parameters
    3. context['data'], context['input'], context['work']
    
    Args:
        task_config: Task configuration
        context: Execution context
        task_with: With-parameters
        iterator_name: Element name for implicit lookup
        
    Returns:
        Collection expression (may need rendering)
        
    Raises:
        ValueError: If collection cannot be resolved
    """
    raw_items_expr = (task_config.get('collection') 
                     if task_config.get('collection') is not None 
                     else task_config.get('data'))
    
    name_keys = candidate_keys(iterator_name)
    items_expr = raw_items_expr
    
    # Handle dict collections
    if isinstance(items_expr, dict):
        items_expr = extract_from_mapping(items_expr, name_keys)
    
    # Try task_with parameters
    if items_expr is None:
        picked = extract_from_mapping(task_with, name_keys)
        if picked is not None:
            items_expr = picked
    
    # Try context data/input/work sections
    if items_expr is None and isinstance(context, dict):
        for ctx_key in ('data', 'input', 'work'):
            picked = extract_from_mapping(context.get(ctx_key), name_keys)
            if picked is not None:
                items_expr = picked
                break
    
    if items_expr is None:
        raise ValueError(
            "Iterator requires 'collection' that resolves to an iterable. "
            f"Tried looking for: {name_keys + ['items', 'values', 'collection']}"
        )
    
    return items_expr


def build_loop_context(
    context: Dict[str, Any],
    task_with: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Build enriched context for rendering loop expressions.
    
    Merges work, workload, input, and task_with into a flat context.
    
    Args:
        context: Execution context
        task_with: With-parameters
        
    Returns:
        Enriched loop context
    """
    loop_ctx = dict(context) if isinstance(context, dict) else {}
    
    try:
        if isinstance(context, dict):
            # Merge work
            work = context.get('work')
            if isinstance(work, dict):
                for k, v in work.items():
                    loop_ctx.setdefault(k, v)
            
            # Merge workload
            workload = context.get('workload')
            if isinstance(workload, dict):
                for k, v in workload.items():
                    loop_ctx.setdefault(k, v)
            
            # Merge input
            inp = context.get('input')
            if isinstance(inp, dict):
                for k, v in inp.items():
                    loop_ctx.setdefault(k, v)
    except Exception:
        pass
    
    # Merge task_with
    try:
        if isinstance(task_with, dict):
            for k, v in task_with.items():
                loop_ctx.setdefault(k, v)
    except Exception:
        pass
    
    return loop_ctx


def apply_filtering(
    indexed_items: List[Tuple[int, Any]],
    where_expr: Optional[str],
    iterator_name: str,
    loop_ctx: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment
) -> List[Tuple[int, Any]]:
    """
    Apply where predicate filtering to items.
    
    Args:
        indexed_items: List of (original_index, item) tuples
        where_expr: Where predicate expression
        iterator_name: Element variable name
        loop_ctx: Loop context for rendering
        context: Parent context
        jinja_env: Jinja2 environment
        
    Returns:
        Filtered list of (index, item) tuples
    """
    if where_expr is None:
        return indexed_items
    
    filtered: List[Tuple[int, Any]] = []
    
    for orig_idx, it in indexed_items:
        # Build evaluation context
        eval_ctx = dict(loop_ctx)
        try:
            eval_ctx[iterator_name] = it
            eval_ctx['parent'] = context
        except Exception:
            pass
        
        # Render and evaluate predicate
        try:
            pred_val = render_template(jinja_env, where_expr, eval_ctx)
        except Exception:
            pred_val = False
        
        if truthy(pred_val):
            filtered.append((orig_idx, it))
    
    return filtered


def apply_sorting(
    indexed_items: List[Tuple[int, Any]],
    order_by_expr: Optional[str],
    iterator_name: str,
    loop_ctx: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment
) -> List[Tuple[int, Any]]:
    """
    Apply order_by sorting to items.
    
    Args:
        indexed_items: List of (original_index, item) tuples
        order_by_expr: Order by expression
        iterator_name: Element variable name
        loop_ctx: Loop context for rendering
        context: Parent context
        jinja_env: Jinja2 environment
        
    Returns:
        Sorted list of (index, item) tuples
    """
    if order_by_expr is None:
        return indexed_items
    
    def key_func(t: Tuple[int, Any]):
        idx0, it0 = t
        key_ctx = dict(loop_ctx)
        try:
            key_ctx[iterator_name] = it0
            key_ctx['parent'] = context
        except Exception:
            pass
        
        try:
            k = render_template(jinja_env, order_by_expr, key_ctx)
        except Exception:
            k = None
        
        return (k, idx0)  # stable sort
    
    try:
        return sorted(indexed_items, key=key_func)
    except Exception:
        # Best-effort; keep original order on error
        return indexed_items


def extract_config(task_config: Dict[str, Any]) -> Dict[str, Any]:
    """
    Extract iterator configuration parameters from task_config.
    
    Args:
        task_config: Task configuration
        
    Returns:
        Dictionary with extracted config values
        
    Raises:
        ValueError: If required parameters missing
    """
    iterator_name = task_config.get('element')
    nested_task = task_config.get('task') or {}
    
    print(f"!!! ITERATOR.CONFIG: nested_task keys={list(nested_task.keys()) if isinstance(nested_task, dict) else 'not dict'}")
    print(f"!!! ITERATOR.CONFIG: has_save={bool(nested_task.get('save'))}")
    print(f"!!! ITERATOR.CONFIG: save_block={nested_task.get('save')}")
    
    logger.info(f"ITERATOR.CONFIG: Extracted nested_task with keys: {list(nested_task.keys()) if isinstance(nested_task, dict) else 'not dict'}, has_save={bool(nested_task.get('save'))}")
    
    if iterator_name is None:
        raise ValueError("Iterator requires 'element' key (tool: iterator)")
    
    if not isinstance(nested_task, dict) or not nested_task:
        raise ValueError(
            "Iterator requires a nested 'task' block to execute per element/batch"
        )
    
    # Extract behavior controls
    mode = str(task_config.get('mode') or 'sequential').strip().lower()
    if mode == 'parallel':
        mode = 'async'
    
    concurrency = int(task_config.get('concurrency') or 
                     (8 if mode == 'async' else 1))
    
    enumerate_flag = bool(task_config.get('enumerate') or False)
    where_expr = task_config.get('where')
    
    limit_val = task_config.get('limit')
    try:
        limit_n = int(limit_val) if limit_val is not None else None
    except Exception:
        limit_n = None
    
    chunk_val = task_config.get('chunk')
    try:
        chunk_n = int(chunk_val) if chunk_val is not None else None
    except Exception:
        chunk_n = None
    
    order_by_expr = task_config.get('order_by')
    
    return {
        'iterator_name': iterator_name,
        'nested_task': nested_task,
        'mode': mode,
        'concurrency': concurrency,
        'enumerate_flag': enumerate_flag,
        'where_expr': where_expr,
        'limit_n': limit_n,
        'chunk_n': chunk_n,
        'order_by_expr': order_by_expr,
    }
