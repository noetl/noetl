"""
Unified retry logic for task execution.

This module provides retry functionality for NoETL tasks with a unified
when/then pattern supporting both error recovery and success-driven repetition.

The retry system supports:
- Unified when/then list pattern: Condition-based retry policies
- First-match evaluation: Policies evaluated in order, first match wins
- Error recovery: Retry on failures with configurable backoff
- Success-driven repetition: Response-driven repeats for pagination, polling, streaming
- Tool-agnostic: Works with HTTP, Postgres, Python, and all other tools

Retry configuration format:
   retry:
     - when: "{{ error.status >= 500 }}"
       then:
         max_attempts: 3
         backoff_multiplier: 2.0
     - when: "{{ response.has_more }}"
       then:
         max_attempts: 100
         next_call:
           params:
             page: "{{ response.page + 1 }}"
         collect:
           strategy: append
           path: data
"""

import time
from typing import Dict, Any, Optional, Callable, List
from jinja2 import Environment

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


class DotDict:
    """
    Wrapper to allow dict access via dot notation in Jinja2 templates.
    Converts response['data']['paging']['hasMore'] → response.data.paging.hasMore
    """
    def __init__(self, data):
        object.__setattr__(self, '_data', data)
        
        if isinstance(data, dict):
            for key, value in data.items():
                if isinstance(value, dict):
                    object.__setattr__(self, key, DotDict(value))
                elif isinstance(value, list):
                    object.__setattr__(self, key, [DotDict(item) if isinstance(item, dict) else item for item in value])
                else:
                    object.__setattr__(self, key, value)
        else:
            object.__setattr__(self, '_value', data)
    
    def __getattr__(self, name):
        if hasattr(self, '_data') and isinstance(self._data, dict) and name in self._data:
            return self._data[name]
        return None
    
    def __repr__(self):
        return f"DotDict({self._data if hasattr(self, '_data') else self.__dict__})"


def execute_with_retry(
    executor_func: Callable,
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute a task with unified when/then retry logic.
    
    Args:
        executor_func: The actual task executor function
        task_config: Task configuration
        task_name: Name of the task
        context: Execution context
        jinja_env: Jinja2 environment
        task_with: Additional parameters
        
    Returns:
        Task execution result with accumulated data if using pagination
    """
    retry_config = task_config.get('retry')
    if not retry_config:
        return executor_func(task_config, context, jinja_env, task_with or {})
    
    # Parse retry configuration
    if isinstance(retry_config, bool):
        if not retry_config:
            return executor_func(task_config, context, jinja_env, task_with or {})
        retry_config = [{'when': '{{ error is defined }}', 'then': {'max_attempts': 3}}]
    elif isinstance(retry_config, int):
        retry_config = [{'when': '{{ error is defined }}', 'then': {'max_attempts': retry_config}}]
    elif not isinstance(retry_config, list):
        logger.error(f"Invalid retry configuration: {retry_config}. Must be a list of when/then policies")
        return executor_func(task_config, context, jinja_env, task_with or {})
    
    # Validate policies
    policies = []
    for idx, policy in enumerate(retry_config):
        if 'when' not in policy or 'then' not in policy:
            logger.warning(f"Retry policy {idx} missing 'when' or 'then', skipping")
            continue
        policies.append({'when': policy['when'], 'then': policy['then'], 'index': idx})
    
    if not policies:
        logger.warning("No valid retry policies found, executing without retry")
        return executor_func(task_config, context, jinja_env, task_with or {})
    
    # Check if any policy has pagination (collect/next_call)
    has_pagination = any('collect' in p['then'] or 'next_call' in p['then'] for p in policies)
    
    if has_pagination:
        logger.info(f"Executing '{task_name}' with pagination retry policies")
        return _execute_with_pagination(
            executor_func, task_config, task_name, context, jinja_env, policies, task_with
        )
    else:
        logger.info(f"Executing '{task_name}' with simple retry policies")
        return _execute_with_simple_retry(
            executor_func, task_config, task_name, context, jinja_env, policies, task_with
        )


def _execute_with_simple_retry(
    executor_func: Callable,
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    policies: List[Dict[str, Any]],
    task_with: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Execute task with simple retry (no pagination)."""
    max_overall_attempts = max((p['then'].get('max_attempts', 3) for p in policies), default=3)
    attempt = 0
    last_error = None
    last_result = None
    
    while attempt < max_overall_attempts:
        attempt += 1
        logger.info(f"Executing task '{task_name}' (attempt {attempt}/{max_overall_attempts})")
        
        try:
            result = executor_func(task_config, context, jinja_env, task_with or {})
            last_result = result
            last_error = None
            
            # Check if any policy matches
            matched_policy = _evaluate_policies(policies, result, None, attempt, context, jinja_env)
            
            if not matched_policy:
                logger.info(f"Task '{task_name}' succeeded, no retry policy matched")
                return result
            
            # Policy matched - check max attempts for this policy
            policy_max = matched_policy['then'].get('max_attempts', 3)
            if attempt >= policy_max:
                logger.info(f"Task '{task_name}' reached max_attempts for policy {matched_policy['index']}")
                return result
            
            # Retry
            delay = _calculate_delay(matched_policy['then'], attempt)
            logger.info(f"Policy {matched_policy['index']} matched, retrying after {delay:.2f}s")
            time.sleep(delay)
            
        except Exception as e:
            logger.warning(f"Task '{task_name}' failed on attempt {attempt}: {e}")
            last_error = e
            last_result = {'success': False, 'error': str(e), 'error_type': type(e).__name__}
            
            matched_policy = _evaluate_policies(policies, last_result, e, attempt, context, jinja_env)
            
            if not matched_policy:
                logger.error(f"Task '{task_name}' failed and no retry policy matched")
                raise
            
            policy_max = matched_policy['then'].get('max_attempts', 3)
            if attempt >= policy_max:
                logger.error(f"Task '{task_name}' reached max_attempts for policy {matched_policy['index']}")
                raise
            
            delay = _calculate_delay(matched_policy['then'], attempt)
            logger.info(f"Policy {matched_policy['index']} matched, retrying after {delay:.2f}s")
            time.sleep(delay)
    
    if last_error:
        raise last_error
    return last_result


def _execute_with_pagination(
    executor_func: Callable,
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    policies: List[Dict[str, Any]],
    task_with: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Execute task with pagination support."""
    # Find pagination policy (first one with collect or next_call)
    pagination_policy = None
    for p in policies:
        if 'collect' in p['then'] or 'next_call' in p['then']:
            pagination_policy = p
            break
    
    if not pagination_policy:
        return _execute_with_simple_retry(
            executor_func, task_config, task_name, context, jinja_env, policies, task_with
        )
    
    # Extract pagination config
    then_config = pagination_policy['then']
    collect_config = then_config.get('collect', {})
    collect_strategy = collect_config.get('strategy', 'append')
    collect_path = collect_config.get('path')
    collect_into = collect_config.get('into', 'pages')
    max_attempts = then_config.get('max_attempts', 100)
    next_call_config = then_config.get('next_call', {})
    per_iteration_config = then_config.get('per_iteration', {})
    
    accumulated = None
    iteration = 0
    all_responses = []
    current_config = dict(task_config)
    
    while iteration < max_attempts:
        iteration += 1
        logger.info(f"Pagination iteration {iteration} for '{task_name}'")
        
        retry_context = dict(context)
        retry_context['_retry'] = {'index': iteration, 'count': iteration}
        if accumulated is not None:
            retry_context[collect_into] = accumulated
        
        # Execute iteration with error retry
        try:
            response = _execute_iteration_with_error_retry(
                executor_func, current_config, task_name, retry_context,
                jinja_env, policies, task_with
            )
        except Exception as e:
            logger.error(f"Pagination iteration {iteration} failed: {e}")
            raise
        
        all_responses.append(response)
        
        # Extract and aggregate data
        page_data = _extract_page_data(response, collect_path)
        accumulated = _aggregate_results(accumulated, page_data, collect_strategy)
        
        # Execute per-iteration effects
        if per_iteration_config:
            _execute_per_iteration_effects(
                per_iteration_config, response, page_data, iteration,
                retry_context, jinja_env
            )
        
        # Check if pagination should continue
        matched_policy = _evaluate_policies([pagination_policy], response, None, iteration, retry_context, jinja_env)
        
        if not matched_policy:
            logger.info(f"Pagination stopping after {iteration} iterations")
            break
        
        # Build next request
        current_config = _build_next_request(
            current_config, next_call_config, response, retry_context, jinja_env
        )
    
    return {
        'id': response.get('id') if response else None,
        'status': 'success',
        'data': accumulated,
        'meta': {
            'iterations': iteration,
            'collect_strategy': collect_strategy,
            'responses': all_responses
        }
    }


def _execute_iteration_with_error_retry(
    executor_func: Callable,
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    policies: List[Dict[str, Any]],
    task_with: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Execute single pagination iteration with error retry."""
    max_attempts = max((p['then'].get('max_attempts', 3) for p in policies), default=3)
    attempt = 0
    
    while attempt < max_attempts:
        attempt += 1
        try:
            result = executor_func(task_config, context, jinja_env, task_with or {})
            
            # Check if error retry policy matches
            matched_policy = _evaluate_policies(policies, result, None, attempt, context, jinja_env)
            
            # Skip pagination policies
            if matched_policy and ('collect' in matched_policy['then'] or 'next_call' in matched_policy['then']):
                return result
            
            if not matched_policy:
                return result
            
            # Non-pagination policy matched - retry
            policy_max = matched_policy['then'].get('max_attempts', 3)
            if attempt >= policy_max:
                return result
            
            delay = _calculate_delay(matched_policy['then'], attempt)
            time.sleep(delay)
            
        except Exception as e:
            logger.error(f"Iteration attempt {attempt}: {e}")
            last_result = {'success': False, 'error': str(e)}
            matched_policy = _evaluate_policies(policies, last_result, e, attempt, context, jinja_env)
            
            if not matched_policy or attempt >= matched_policy['then'].get('max_attempts', 3):
                raise
            
            delay = _calculate_delay(matched_policy['then'], attempt)
            time.sleep(delay)
    
    raise Exception(f"Failed after {max_attempts} attempts")


def _evaluate_policies(
    policies: List[Dict[str, Any]],
    result: Dict[str, Any],
    error: Optional[Exception],
    attempt: int,
    context: Dict[str, Any],
    jinja_env: Environment
) -> Optional[Dict[str, Any]]:
    """Evaluate policies in order, return first match."""
    # Build error context
    error_obj = {}
    if error:
        error_obj = {'message': str(error), 'type': type(error).__name__}
    elif result.get('status') == 'error':
        data = result.get('data', {})
        if isinstance(data, dict):
            status_code = data.get('status_code')
            if status_code:
                error_obj = {
                    'status': status_code,
                    'message': str(data.get('data', '')),
                    'type': 'HTTPError'
                }
    
    # Unwrap HTTP response
    http_metadata = result.get('data', result) if isinstance(result, dict) else result
    actual_response = http_metadata.get('data', http_metadata) if isinstance(http_metadata, dict) else http_metadata
    actual_response_dotted = DotDict(actual_response)
    
    # Build evaluation context
    eval_context = dict(context)
    eval_context.update({
        'result': result,
        'response': actual_response_dotted,
        'page': actual_response_dotted,
        'attempt': attempt,
        'error': DotDict(error_obj) if error_obj else None,
        'success': result.get('success', True),
    })
    
    # Evaluate policies (first match wins)
    for policy in policies:
        when_condition = policy.get('when')
        if not when_condition:
            continue
        
        try:
            template = jinja_env.from_string(when_condition)
            result_str = template.render(**eval_context)
            matches = str(result_str).lower() in ('true', '1', 'yes')
            
            if matches:
                logger.info(f"Policy {policy['index']} matched: {when_condition}")
                return policy
        except Exception as e:
            logger.warning(f"Error evaluating policy {policy['index']}: {e}")
            continue
    
    return None


def _calculate_delay(then_config: Dict[str, Any], attempt: int) -> float:
    """Calculate retry delay."""
    initial_delay = then_config.get('initial_delay', 1.0)
    max_delay = then_config.get('max_delay', 60.0)
    backoff_multiplier = then_config.get('backoff_multiplier', 2.0)
    jitter = then_config.get('jitter', True)
    
    delay = min(initial_delay * (backoff_multiplier ** (attempt - 1)), max_delay)
    
    if jitter:
        import random
        delay = delay * (0.5 + random.random())
    
    return delay


def _extract_page_data(response: Dict[str, Any], collect_path: Optional[str]) -> Any:
    """Extract data from response using collect path."""
    http_metadata = response.get('data', response) if isinstance(response, dict) else response
    actual_response = http_metadata.get('data', http_metadata) if isinstance(http_metadata, dict) else http_metadata
    
    if not collect_path:
        return actual_response
    
    data = actual_response
    for part in collect_path.split('.'):
        if isinstance(data, dict):
            data = data.get(part)
            if data is None:
                break
    
    return data


def _aggregate_results(accumulated: Any, page_data: Any, strategy: str) -> Any:
    """Aggregate page data."""
    if strategy == 'append':
        if accumulated is None:
            accumulated = []
        if isinstance(page_data, list):
            accumulated.extend(page_data)
        else:
            accumulated.append(page_data)
        return accumulated
    elif strategy == 'replace':
        return page_data
    elif strategy == 'merge':
        if accumulated is None:
            return page_data
        if isinstance(accumulated, dict) and isinstance(page_data, dict):
            accumulated.update(page_data)
        return accumulated
    return accumulated


def _build_next_request(
    current_config: Dict[str, Any],
    next_call_config: Dict[str, Any],
    response: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment
) -> Dict[str, Any]:
    """Build next request from current response."""
    next_config = dict(current_config)
    
    # Unwrap response
    http_metadata = response.get('data', response) if isinstance(response, dict) else response
    actual_response = http_metadata.get('data', http_metadata) if isinstance(http_metadata, dict) else http_metadata
    actual_response_dotted = DotDict(actual_response)
    
    render_context = dict(context)
    render_context['response'] = actual_response_dotted
    render_context['page'] = actual_response_dotted
    
    # Update params
    if 'params' in next_call_config:
        if 'params' not in next_config:
            next_config['params'] = {}
        for key, template_str in next_call_config['params'].items():
            if isinstance(template_str, str):
                from noetl.core.dsl.render import render_template
                next_config['params'][key] = render_template(jinja_env, template_str, render_context)
            else:
                next_config['params'][key] = template_str
    
    # Update headers
    if 'headers' in next_call_config:
        if 'headers' not in next_config:
            next_config['headers'] = {}
        for key, template_str in next_call_config['headers'].items():
            if isinstance(template_str, str):
                from noetl.core.dsl.render import render_template
                next_config['headers'][key] = render_template(jinja_env, template_str, render_context)
            else:
                next_config['headers'][key] = template_str
    
    # Update URL
    if 'url' in next_call_config:
        from noetl.core.dsl.render import render_template
        next_config['url'] = render_template(jinja_env, next_call_config['url'], render_context)
    
    return next_config


def _execute_per_iteration_effects(
    per_iteration_config: Dict[str, Any],
    response: Dict[str, Any],
    page_data: Any,
    iteration: int,
    context: Dict[str, Any],
    jinja_env: Environment
):
    """Execute per-iteration side effects (sink, etc.)."""
    if 'sink' in per_iteration_config:
        logger.info(f"Executing per-iteration sink for iteration {iteration}")
        
        sink_context = dict(context)
        sink_context['page'] = {'data': page_data}
        sink_context['response'] = response
        sink_context['_retry'] = {'index': iteration, 'count': context.get('_retry', {}).get('count', iteration)}
        
        from noetl.plugin.shared.storage import execute_sink_task
        sink_config = per_iteration_config['sink']
        
        try:
            sink_result = execute_sink_task(sink_config, sink_context, jinja_env)
            if sink_result.get('status') != 'success':
                logger.error(f"Per-iteration sink failed: {sink_result.get('error')}")
        except Exception as e:
            logger.error(f"Per-iteration sink raised exception: {e}")
