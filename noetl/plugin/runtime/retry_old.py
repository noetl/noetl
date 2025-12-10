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
import asyncio
from typing import Dict, Any, Optional, Callable, List
from jinja2 import Environment, Template

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


class DotDict:
    """
    Wrapper to allow dict access via dot notation in Jinja2 templates.
    Converts response['data']['paging']['hasMore'] → response.data.paging.hasMore
    """
    def __init__(self, data):
        # Store original data
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
            # Not a dict, store as-is
            object.__setattr__(self, '_value', data)
    
    def __getattr__(self, name):
        # Check if it's in _data dict (fallback)
        if hasattr(self, '_data') and isinstance(self._data, dict) and name in self._data:
            return self._data[name]
        # Return None for truly missing attributes
        return None
    
    def __repr__(self):
        return f"DotDict({self._data if hasattr(self, '_data') else self.__dict__})"


class RetryPolicy:
    """
    Retry policy configuration and evaluation.
    
    Supports:
    - Expression-based retry conditions
    - Configurable max attempts
    - Exponential backoff with configurable delay
    - Jitter for distributed systems
    """
    
    def __init__(
        self,
        retry_config: Dict[str, Any],
        jinja_env: Environment
    ):
        """
        Initialize retry policy from task configuration.
        
        Args:
            retry_config: Retry configuration from task
            jinja_env: Jinja2 environment for expression evaluation
        """
        self.max_attempts = retry_config.get('max_attempts', 3)
        self.initial_delay = retry_config.get('initial_delay', 1.0)
        self.max_delay = retry_config.get('max_delay', 60.0)
        self.backoff_multiplier = retry_config.get('backoff_multiplier', 2.0)
        self.jitter = retry_config.get('jitter', True)
        
        # Retry condition - Jinja2 expression that evaluates to boolean
        # Expression has access to: result, status_code, error, attempt
        # Support both 'retry_when' (explicit) and 'when' (shorthand in on_error/on_success blocks)
        self.retry_when = retry_config.get('retry_when') or retry_config.get('when')
        
        # Stop condition - overrides retry_when if true
        self.stop_when = retry_config.get('stop_when', None)
        
        self.jinja_env = jinja_env
        
    def should_retry(
        self,
        result: Dict[str, Any],
        attempt: int,
        error: Optional[Exception] = None
    ) -> bool:
        """
        Determine if task should be retried based on result and policy.
        
        Args:
            result: Task execution result
            attempt: Current attempt number (1-indexed)
            error: Exception if task failed
            
        Returns:
            True if task should be retried, False otherwise
        """
        # Check max attempts
        # attempt represents the NEXT attempt number, so we check if it would exceed max
        if attempt > self.max_attempts:
            logger.info(f"Max retry attempts ({self.max_attempts}) reached (next attempt would be {attempt})")
            return False
            
        # Build error context for template evaluation
        # Handle HTTP error responses: {status: 'error', data: {status_code: 500, ...}}
        error_obj = {}
        if error:
            error_obj = {'message': str(error), 'type': type(error).__name__}
        elif result.get('status') == 'error':
            # HTTP error response - extract status code
            data = result.get('data', {})
            if isinstance(data, dict):
                status_code = data.get('status_code')
                if status_code:
                    error_obj = {
                        'status': status_code,
                        'message': data.get('data', {}).get('detail') if isinstance(data.get('data'), dict) else str(data.get('data')),
                        'type': 'HTTPError'
                    }
        
        # Build context for expression evaluation
        eval_context = {
            'result': result,
            'attempt': attempt,
            'error': DotDict(error_obj) if error_obj else None,
            'status_code': result.get('status_code'),
            'success': result.get('success', True),
            'data': result.get('data'),
        }
        
        # Check stop condition first
        if self.stop_when:
            try:
                template = self.jinja_env.from_string(self.stop_when)
                should_stop = template.render(**eval_context)
                # Convert to boolean
                stop = str(should_stop).lower() in ('true', '1', 'yes')
                if stop:
                    logger.info(f"Stop condition met: {self.stop_when}")
                    return False
            except Exception as e:
                logger.warning(f"Error evaluating stop_when expression: {e}")
                return False
        
        # Check retry condition
        if self.retry_when:
            try:
                logger.info(f"Evaluating retry_when: {self.retry_when}, error_obj={error_obj}, eval_context keys={list(eval_context.keys())}")
                template = self.jinja_env.from_string(self.retry_when)
                should_retry = template.render(**eval_context)
                # Convert to boolean
                retry = str(should_retry).lower() in ('true', '1', 'yes')
                logger.info(f"Retry condition '{self.retry_when}' evaluated to: {should_retry} -> {retry}")
                return retry
            except Exception as e:
                logger.warning(f"Error evaluating retry_when expression: {e}")
                return False
        
        # Default: retry on error
        if error or not result.get('success', True):
            logger.info("No retry condition specified, retrying on error/failure")
            return True
            
        return False
    
    def get_delay(self, attempt: int) -> float:
        """
        Calculate delay before next retry using exponential backoff.
        
        Args:
            attempt: Current attempt number (1-indexed)
            
        Returns:
            Delay in seconds
        """
        # Exponential backoff: initial_delay * (multiplier ^ (attempt - 1))
        delay = min(
            self.initial_delay * (self.backoff_multiplier ** (attempt - 1)),
            self.max_delay
        )
        
        # Add jitter to prevent thundering herd
        if self.jitter:
            import random
            delay = delay * (0.5 + random.random())
        
        return delay


class SuccessRetryPolicy:
    """
    Success-side retry policy for pagination, polling, and streaming patterns.
    
    Enables response-driven repetition where successful responses trigger
    subsequent invocations with updated parameters.
    """
    
    def __init__(
        self,
        config: Dict[str, Any],
        jinja_env: Environment
    ):
        """
        Initialize success retry policy.
        
        Args:
            config: on_success configuration block
            jinja_env: Jinja2 environment for expression evaluation
        """
        # Continuation condition
        self.while_condition = config.get('while')
        if not self.while_condition:
            raise ValueError("retry.on_success.while is required")
        
        # Max iterations guard
        self.max_attempts = config.get('max_attempts', 100)
        
        # How to build next request
        self.next_call = config.get('next_call', {})
        
        # Result collection/aggregation
        collect_config = config.get('collect', {})
        self.collect_strategy = collect_config.get('strategy', 'append')  # append|replace|merge
        self.collect_path = collect_config.get('path')  # JSONPath to extract from response
        self.collect_into = collect_config.get('into', 'pages')  # Variable name for accumulated results
        
        # Per-iteration side effects
        self.per_iteration = config.get('per_iteration', {})
        
        self.jinja_env = jinja_env
    
    def should_continue(
        self,
        response: Dict[str, Any],
        iteration: int,
        context: Dict[str, Any]
    ) -> bool:
        """
        Check if iteration should continue based on response and condition.
        
        Args:
            response: Current response
            iteration: Current iteration number (1-indexed)
            context: Execution context
            
        Returns:
            True if should continue iterating
        """
        # Check max attempts
        if iteration >= self.max_attempts:
            logger.info(f"Success retry max_attempts ({self.max_attempts}) reached")
            return False
        
        # Evaluate while condition
        eval_context = dict(context)
        
        # Unwrap HTTP envelope (DOUBLE unwrapping for HTTP responses)
        # Structure: {'id': ..., 'status': ..., 'data': {'status_code': 200, 'data': <actual_response>}}
        # First unwrap: Get the HTTP metadata level
        http_metadata = response.get('data', response) if isinstance(response, dict) else response
        # Second unwrap: Get the actual API response from 'data' key
        actual_response = http_metadata.get('data', http_metadata) if isinstance(http_metadata, dict) else http_metadata
        
        # DEBUG: Log the actual response structure
        logger.critical(f"RETRY.should_continue: response type={type(response)}, keys={list(response.keys()) if isinstance(response, dict) else 'N/A'}")
        logger.critical(f"RETRY.should_continue: http_metadata type={type(http_metadata)}, keys={list(http_metadata.keys()) if isinstance(http_metadata, dict) else 'N/A'}")
        logger.critical(f"RETRY.should_continue: actual_response type={type(actual_response)}, keys={list(actual_response.keys()) if isinstance(actual_response, dict) else 'N/A'}")
        if isinstance(actual_response, dict):
            logger.critical(f"RETRY.should_continue: actual_response.paging={actual_response.get('paging')}")
        
        # Convert to DotDict to allow dot notation in Jinja2 templates
        # This enables response.paging.hasMore instead of response['paging']['hasMore']
        actual_response_dotted = DotDict(actual_response)
        
        eval_context['response'] = actual_response_dotted
        eval_context['page'] = actual_response_dotted  # Alias for pagination clarity
        eval_context['iteration'] = iteration
        eval_context['_retry'] = {
            'index': iteration,
            'count': iteration  # Will be updated at end
        }
        
        try:
            template = self.jinja_env.from_string(self.while_condition)
            result = template.render(**eval_context)
            should_continue = str(result).lower() in ('true', '1', 'yes')
            logger.info(f"Success retry while condition evaluated to: {should_continue} (iteration {iteration})")
            return should_continue
        except Exception as e:
            logger.warning(f"Error evaluating success retry while condition: {e}")
            logger.warning(f"Response structure: {type(response)}")
            import traceback
            logger.warning(f"Traceback: {traceback.format_exc()}")
            return False
    
    def extract_page_data(self, response: Dict[str, Any]) -> Any:
        """
        Extract data from response using collect.path.
        
        Args:
            response: Response to extract from (HTTP envelope format)
            
        Returns:
            Extracted data
        """
        # Unwrap HTTP envelope (DOUBLE unwrapping)
        # Structure: {'id': ..., 'status': ..., 'data': {'status_code': 200, 'data': <actual_response>}}
        http_metadata = response.get('data', response) if isinstance(response, dict) else response
        actual_response = http_metadata.get('data', http_metadata) if isinstance(http_metadata, dict) else http_metadata
        
        if not self.collect_path:
            return actual_response
        
        data = actual_response
        parts = self.collect_path.split('.')
        for part in parts:
            if isinstance(data, dict):
                data = data.get(part)
                if data is None:
                    logger.warning(f"Collect path part '{part}' not found")
                    break
            else:
                logger.warning(f"Cannot traverse collect path '{part}' on non-dict")
                break
        
        return data
    
    def aggregate_results(
        self,
        accumulated: Any,
        page_data: Any
    ) -> Any:
        """
        Aggregate page data into accumulated results based on strategy.
        
        Args:
            accumulated: Previously accumulated data
            page_data: Current page data to aggregate
            
        Returns:
            Updated accumulated data
        """
        if self.collect_strategy == 'append':
            if accumulated is None:
                accumulated = []
            if isinstance(page_data, list):
                accumulated.extend(page_data)
            else:
                accumulated.append(page_data)
            return accumulated
        
        elif self.collect_strategy == 'replace':
            return page_data
        
        elif self.collect_strategy == 'merge':
            if accumulated is None:
                return page_data
            if isinstance(accumulated, dict) and isinstance(page_data, dict):
                accumulated.update(page_data)
                return accumulated
            else:
                logger.warning(f"Cannot merge non-dict types, using replace strategy")
                return page_data
        
        return accumulated


class UnifiedRetryPolicy:
    """
    Unified retry policy supporting both error recovery and success-driven repetition.
    
    Handles:
    - New format: List of when/then policies (first-match evaluation)
    - Legacy format: on_error and/or on_success blocks (backward compatible)
    
    New format example:
        retry:
          - when: "{{ error.status >= 500 }}"
            then: {max_attempts: 3}
          - when: "{{ response.has_more }}"
            then: {next_call: ..., collect: ...}
    
    Legacy format example:
        retry:
          on_error: {when: ..., max_attempts: 3}
          on_success: {while: ..., next_call: ...}
    """
    
    def __init__(
        self,
        retry_config: Dict[str, Any],
        jinja_env: Environment
    ):
        """
        Initialize unified retry policy.
        
        Args:
            retry_config: Retry configuration (list or legacy format)
            jinja_env: Jinja2 environment
        """
        self.jinja_env = jinja_env
        self.policies = []  # List of (when_condition, then_config) tuples
        
        # Check format: list (new) or dict (legacy)
        if isinstance(retry_config, list):
            # New unified when/then list format
            logger.info(f"Parsing {len(retry_config)} when/then retry policies")
            for idx, policy in enumerate(retry_config):
                if 'when' not in policy or 'then' not in policy:
                    logger.warning(f"Retry policy {idx} missing 'when' or 'then', skipping")
                    continue
                self.policies.append({
                    'when': policy['when'],
                    'then': policy['then'],
                    'index': idx
                })
            self.is_list_format = True
            self.on_error_policy = None
            self.on_success_policy = None
        else:
            # Legacy format: on_error and/or on_success
            has_on_error = 'on_error' in retry_config
            has_on_success = 'on_success' in retry_config
            
            if has_on_error or has_on_success:
                # Legacy unified structure
                self.on_error_policy = RetryPolicy(retry_config.get('on_error', {}), jinja_env) if has_on_error else None
                self.on_success_policy = SuccessRetryPolicy(retry_config['on_success'], jinja_env) if has_on_success else None
                self.is_list_format = False
            else:
                # Very old legacy structure - treat as on_error only
                self.on_error_policy = RetryPolicy(retry_config, jinja_env)
                self.on_success_policy = None
                self.is_list_format = False


def execute_with_retry(
    executor_func: Callable,
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute a task with unified retry logic (error recovery + success repetition).
    
    Supports:
    - on_error: Classic retry on failures
    - on_success: Pagination, polling, cursor-based iteration
    
    Args:
        executor_func: The actual task executor function
        task_config: Task configuration
        task_name: Name of the task
        context: Execution context
        jinja_env: Jinja2 environment
        task_with: Additional parameters
        
    Returns:
        Task execution result with accumulated data if using on_success
        
    Raises:
        Exception: If all error retry attempts fail
    """
    # Check if retry is configured
    retry_config = task_config.get('retry')
    if not retry_config:
        # No retry configured, execute once
        return executor_func(task_config, context, jinja_env, task_with or {})
    
    # Parse retry configuration
    if isinstance(retry_config, bool):
        # Simple retry: true = default policy, false = no retry
        if not retry_config:
            return executor_func(task_config, context, jinja_env, task_with or {})
        retry_config = {}  # Use defaults for error retry
    elif isinstance(retry_config, int):
        # Retry with max attempts only
        retry_config = {'max_attempts': retry_config}
    elif not isinstance(retry_config, dict):
        logger.warning(f"Invalid retry configuration: {retry_config}, ignoring")
        return executor_func(task_config, context, jinja_env, task_with or {})
    
    # Create unified retry policy
    policy = UnifiedRetryPolicy(retry_config, jinja_env)
    
    # Route based on format
    if policy.is_list_format:
        # New when/then list format - use new execution path
        logger.info(f"Executing '{task_name}' with when/then retry policies (first-match)")
        return _execute_with_policy_list(
            executor_func, task_config, task_name, context, jinja_env,
            policy, task_with
        )
    elif policy.on_success_policy:
        # Legacy format with success-side retry (pagination/polling)
        logger.info(f"Executing '{task_name}' with success-side retry (pagination/polling)")
        return _execute_with_success_retry(
            executor_func, task_config, task_name, context, jinja_env,
            policy, task_with
        )
    else:
        # Legacy format with error-only retry
        logger.info(f"Executing '{task_name}' with error-side retry")
        return _execute_with_error_retry(
            executor_func, task_config, task_name, context, jinja_env,
            policy.on_error_policy, task_with
        )


def _execute_with_policy_list(
    executor_func: Callable,
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    unified_policy: UnifiedRetryPolicy,
    task_with: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute task with when/then policy list (first-match evaluation).
    
    Evaluates policies in order, first truthy 'when' condition wins.
    Supports both error recovery and success-driven pagination within same list.
    
    Args:
        executor_func: The actual task executor function
        task_config: Task configuration
        task_name: Name of the task
        context: Execution context
        jinja_env: Jinja2 environment
        unified_policy: Unified retry policy with policy list
        task_with: Additional parameters
        
    Returns:
        Task execution result with accumulated data if using pagination
    """
    policies = unified_policy.policies
    
    # Check if any policy looks like pagination (has collect, next_call)
    has_pagination = any(
        'collect' in p.get('then', {}) or 'next_call' in p.get('then', {})
        for p in policies
    )
    
    if has_pagination:
        # Use pagination-aware execution path
        return _execute_with_policy_list_pagination(
            executor_func, task_config, task_name, context, jinja_env,
            unified_policy, task_with
        )
    else:
        # Simple retry (error recovery only)
        return _execute_with_policy_list_simple(
            executor_func, task_config, task_name, context, jinja_env,
            unified_policy, task_with
        )


def _execute_with_policy_list_simple(
    executor_func: Callable,
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    unified_policy: UnifiedRetryPolicy,
    task_with: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute task with policy list for simple error retry (no pagination).
    
    Evaluates policies in order after each attempt, first match wins.
    """
    policies = unified_policy.policies
    attempt = 0
    max_overall_attempts = max((p.get('then', {}).get('max_attempts', 3) for p in policies), default=3)
    
    last_error = None
    last_result = None
    
    while attempt < max_overall_attempts:
        attempt += 1
        logger.info(f"Executing task '{task_name}' (attempt {attempt})")
        
        try:
            # Execute task
            result = executor_func(task_config, context, jinja_env, task_with or {})
            last_result = result
            last_error = None
            
            # Success - check if any policy matches for continuation
            matched_policy = _evaluate_policies(policies, result, None, attempt, context, jinja_env)
            
            if not matched_policy:
                # No policy matched, task succeeded
                logger.info(f"Task '{task_name}' succeeded on attempt {attempt}, no retry policy matched")
                return result
            
            # Policy matched - check if we should retry
            then_config = matched_policy['then']
            policy_max_attempts = then_config.get('max_attempts', 3)
            
            if attempt >= policy_max_attempts:
                logger.info(f"Task '{task_name}' matched policy {matched_policy['index']} but reached max_attempts")
                return result
            
            # Retry needed
            delay = _calculate_delay(then_config, attempt)
            logger.info(f"Task '{task_name}' matched policy {matched_policy['index']}, retrying after {delay:.2f}s")
            time.sleep(delay)
            
        except Exception as e:
            logger.warning(f"Task '{task_name}' failed on attempt {attempt}: {e}")
            last_error = e
            last_result = {
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            }
            
            # Check if any policy matches the error
            matched_policy = _evaluate_policies(policies, last_result, e, attempt, context, jinja_env)
            
            if not matched_policy:
                logger.error(f"Task '{task_name}' failed and no retry policy matched")
                raise
            
            # Policy matched - check if we should retry
            then_config = matched_policy['then']
            policy_max_attempts = then_config.get('max_attempts', 3)
            
            if attempt >= policy_max_attempts:
                logger.error(f"Task '{task_name}' matched policy {matched_policy['index']} but reached max_attempts")
                raise
            
            # Retry needed
            delay = _calculate_delay(then_config, attempt)
            logger.info(f"Task '{task_name}' matched policy {matched_policy['index']}, retrying after {delay:.2f}s")
            time.sleep(delay)
    
    # All attempts exhausted
    if last_error:
        logger.error(f"Task '{task_name}' failed after {max_overall_attempts} attempts")
        raise last_error
    else:
        logger.warning(f"Task '{task_name}' did not succeed after {max_overall_attempts} attempts")
        return last_result


def _execute_with_policy_list_pagination(
    executor_func: Callable,
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    unified_policy: UnifiedRetryPolicy,
    task_with: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute task with policy list supporting pagination (success-side retry).
    
    Evaluates policies in order, first match wins. Supports collect/next_call.
    """
    policies = unified_policy.policies
    
    # Find pagination policy (first one with collect or next_call)
    pagination_policy = None
    for p in policies:
        then_config = p.get('then', {})
        if 'collect' in then_config or 'next_call' in then_config:
            pagination_policy = p
            break
    
    if not pagination_policy:
        # No pagination policy found, fall back to simple retry
        return _execute_with_policy_list_simple(
            executor_func, task_config, task_name, context, jinja_env,
            unified_policy, task_with
        )
    
    # Extract pagination configuration
    then_config = pagination_policy['then']
    collect_config = then_config.get('collect', {})
    collect_strategy = collect_config.get('strategy', 'append')
    collect_path = collect_config.get('path')
    collect_into = collect_config.get('into', 'pages')
    max_attempts = then_config.get('max_attempts', 100)
    next_call_config = then_config.get('next_call', {})
    per_iteration_config = then_config.get('per_iteration', {})
    
    # Accumulator for collected results
    accumulated = None
    iteration = 0
    all_responses = []
    current_config = dict(task_config)
    
    while iteration < max_attempts:
        iteration += 1
        logger.info(f"Pagination iteration {iteration} for '{task_name}'")
        
        # Update context with retry metadata
        retry_context = dict(context)
        retry_context['_retry'] = {
            'index': iteration,
            'count': iteration
        }
        if accumulated is not None:
            retry_context[collect_into] = accumulated
        
        # Execute task (with error retry if matching policy exists)
        try:
            response = _execute_iteration_with_policy_list_error_retry(
                executor_func, current_config, task_name, retry_context,
                jinja_env, policies, task_with
            )
        except Exception as e:
            logger.error(f"Pagination iteration {iteration} failed: {e}")
            raise
        
        all_responses.append(response)
        
        # Extract and aggregate page data
        page_data = _extract_page_data(response, collect_path)
        accumulated = _aggregate_results(accumulated, page_data, collect_strategy)
        logger.info(f"Aggregated data from iteration {iteration}")
        
        # Execute per-iteration side effects
        if per_iteration_config:
            _execute_per_iteration_effects(
                per_iteration_config,
                response,
                page_data,
                iteration,
                retry_context,
                jinja_env
            )
        
        # Check if pagination policy's when condition still matches
        matched_policy = _evaluate_policies([pagination_policy], response, None, iteration, retry_context, jinja_env)
        
        if not matched_policy:
            logger.info(f"Pagination stopping after {iteration} iterations (when condition no longer matches)")
            break
        
        # Build next request
        current_config = _build_next_request(
            current_config,
            next_call_config,
            response,
            retry_context,
            jinja_env
        )
    
    # Update final context
    final_context = dict(context)
    final_context['_retry'] = {
        'index': iteration,
        'count': iteration
    }
    final_context[collect_into] = accumulated
    
    # Return result with accumulated data
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


def _execute_iteration_with_policy_list_error_retry(
    executor_func: Callable,
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    policies: List[Dict[str, Any]],
    task_with: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Execute single pagination iteration with error retry from policy list."""
    # Find error retry policies (those that match errors)
    max_attempts = max((p.get('then', {}).get('max_attempts', 3) for p in policies), default=3)
    attempt = 0
    
    while attempt < max_attempts:
        attempt += 1
        try:
            result = executor_func(task_config, context, jinja_env, task_with or {})
            
            # Check if any policy matches for retry
            matched_policy = _evaluate_policies(policies, result, None, attempt, context, jinja_env)
            
            # Skip pagination policies (those with collect/next_call)
            if matched_policy and ('collect' in matched_policy.get('then', {}) or 'next_call' in matched_policy.get('then', {})):
                # This is pagination policy, not error retry - return success
                return result
            
            if not matched_policy:
                return result
            
            # Non-pagination policy matched on success - retry
            policy_max = matched_policy.get('then', {}).get('max_attempts', 3)
            if attempt >= policy_max:
                return result
            
            delay = _calculate_delay(matched_policy['then'], attempt)
            logger.info(f"Iteration error retry: sleeping for {delay}s before next attempt")
            time.sleep(delay)
            
        except Exception as e:
            logger.error(f"Iteration attempt {attempt}: exception {e}")
            
            last_result = {'success': False, 'error': str(e)}
            matched_policy = _evaluate_policies(policies, last_result, e, attempt, context, jinja_env)
            
            if not matched_policy or attempt >= matched_policy.get('then', {}).get('max_attempts', 3):
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
    """
    Evaluate policy list in order, return first matching policy.
    
    Args:
        policies: List of when/then policies
        result: Task result
        error: Exception if task failed
        attempt: Current attempt number
        context: Execution context
        jinja_env: Jinja2 environment
        
    Returns:
        First matching policy dict, or None if no match
    """
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
                    'message': data.get('data', {}).get('detail') if isinstance(data.get('data'), dict) else str(data.get('data')),
                    'type': 'HTTPError'
                }
    
    # Unwrap HTTP response for evaluation
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
        'status_code': result.get('status_code'),
        'success': result.get('success', True),
        'data': result.get('data'),
    })
    
    # Evaluate policies in order (first match wins)
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
            logger.warning(f"Error evaluating policy {policy['index']} when condition: {e}")
            continue
    
    return None


def _calculate_delay(then_config: Dict[str, Any], attempt: int) -> float:
    """Calculate retry delay from then config."""
    initial_delay = then_config.get('initial_delay', 1.0)
    max_delay = then_config.get('max_delay', 60.0)
    backoff_multiplier = then_config.get('backoff_multiplier', 2.0)
    jitter = then_config.get('jitter', True)
    
    delay = min(
        initial_delay * (backoff_multiplier ** (attempt - 1)),
        max_delay
    )
    
    if jitter:
        import random
        delay = delay * (0.5 + random.random())
    
    return delay


def _extract_page_data(response: Dict[str, Any], collect_path: Optional[str]) -> Any:
    """Extract data from response using collect path."""
    # Unwrap HTTP envelope (double unwrapping)
    http_metadata = response.get('data', response) if isinstance(response, dict) else response
    actual_response = http_metadata.get('data', http_metadata) if isinstance(http_metadata, dict) else http_metadata
    
    if not collect_path:
        return actual_response
    
    data = actual_response
    parts = collect_path.split('.')
    for part in parts:
        if isinstance(data, dict):
            data = data.get(part)
            if data is None:
                logger.warning(f"Collect path part '{part}' not found")
                break
        else:
            logger.warning(f"Cannot traverse collect path '{part}' on non-dict")
            break
    
    return data


def _aggregate_results(accumulated: Any, page_data: Any, strategy: str) -> Any:
    """Aggregate page data into accumulated results."""
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
        else:
            logger.warning(f"Cannot merge non-dict types, using replace strategy")
            return page_data
    
    return accumulated


def _execute_with_error_retry(
    executor_func: Callable,
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    policy: RetryPolicy,
    task_with: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute task with classic error-side retry.
    
    This is the original retry logic - retry on failures with backoff.
    """
    attempt = 0
    last_error = None
    last_result = None
    
    while attempt < policy.max_attempts:
        attempt += 1
        logger.info(f"Executing task '{task_name}' (attempt {attempt}/{policy.max_attempts})")
        
        try:
            # Execute task
            result = executor_func(task_config, context, jinja_env, task_with or {})
            last_result = result
            last_error = None
            
            # Check if retry is needed
            if not policy.should_retry(result, attempt, None):
                logger.info(f"Task '{task_name}' succeeded on attempt {attempt}")
                return result
            
            # Retry needed
            if attempt < policy.max_attempts:
                delay = policy.get_delay(attempt)
                logger.info(f"Task '{task_name}' will retry after {delay:.2f}s (attempt {attempt}/{policy.max_attempts})")
                time.sleep(delay)
            
        except Exception as e:
            logger.warning(f"Task '{task_name}' failed on attempt {attempt}: {e}")
            last_error = e
            last_result = {
                'success': False,
                'error': str(e),
                'error_type': type(e).__name__
            }
            
            # Check if retry is needed
            if not policy.should_retry(last_result, attempt, e):
                logger.error(f"Task '{task_name}' failed and retry condition not met")
                raise
            
            # Retry needed
            if attempt < policy.max_attempts:
                delay = policy.get_delay(attempt)
                logger.info(f"Task '{task_name}' will retry after {delay:.2f}s (attempt {attempt}/{policy.max_attempts})")
                time.sleep(delay)
    
    # All attempts exhausted
    if last_error:
        logger.error(f"Task '{task_name}' failed after {policy.max_attempts} attempts")
        raise last_error
    else:
        logger.warning(f"Task '{task_name}' did not succeed after {policy.max_attempts} attempts")
        return last_result


def _execute_with_success_retry(
    executor_func: Callable,
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    unified_policy: UnifiedRetryPolicy,
    task_with: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Execute task with success-side retry (pagination/polling).
    
    This implements the new unified retry concept where successful responses
    can trigger re-invocation with updated parameters.
    """
    success_policy = unified_policy.on_success_policy
    error_policy = unified_policy.on_error_policy
    
    # Accumulator for collected results
    accumulated = None
    iteration = 0
    all_responses = []
    
    # Build initial request config
    current_config = dict(task_config)
    
    while iteration < success_policy.max_attempts:
        iteration += 1
        logger.info(f"Success retry iteration {iteration} for '{task_name}'")
        
        # Update context with retry metadata
        retry_context = dict(context)
        retry_context['_retry'] = {
            'index': iteration,
            'count': iteration  # Will be final count at end
        }
        if accumulated is not None:
            retry_context[success_policy.collect_into] = accumulated
        
        # Execute task (with optional error retry)
        if error_policy:
            # Execute with error retry for this iteration
            try:
                response = _execute_iteration_with_error_retry(
                    executor_func, current_config, task_name, retry_context,
                    jinja_env, error_policy, task_with
                )
            except Exception as e:
                logger.error(f"Success retry iteration {iteration} failed after error retries: {e}")
                raise
        else:
            # Execute without error retry
            try:
                response = executor_func(current_config, retry_context, jinja_env, task_with or {})
            except Exception as e:
                logger.error(f"Success retry iteration {iteration} failed: {e}")
                raise
        
        all_responses.append(response)
        
        # Extract and aggregate page data
        page_data = success_policy.extract_page_data(response)
        accumulated = success_policy.aggregate_results(accumulated, page_data)
        logger.info(f"Aggregated data from iteration {iteration}")
        
        # Execute per-iteration side effects (sink, etc.)
        if success_policy.per_iteration:
            _execute_per_iteration_effects(
                success_policy.per_iteration,
                response,
                page_data,
                iteration,
                retry_context,
                jinja_env
            )
        
        # Check if we should continue
        if not success_policy.should_continue(response, iteration, retry_context):
            logger.info(f"Success retry stopping after {iteration} iterations")
            break
        
        # Build next request
        current_config = _build_next_request(
            current_config,
            success_policy.next_call,
            response,
            retry_context,
            jinja_env
        )
    
    # Update final count in context
    final_context = dict(context)
    final_context['_retry'] = {
        'index': iteration,
        'count': iteration
    }
    final_context[success_policy.collect_into] = accumulated
    
    # Return result with accumulated data
    return {
        'id': response.get('id') if response else None,
        'status': 'success',
        'data': accumulated,
        'meta': {
            'iterations': iteration,
            'collect_strategy': success_policy.collect_strategy,
            'responses': all_responses
        }
    }


def _execute_iteration_with_error_retry(
    executor_func: Callable,
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    error_policy: RetryPolicy,
    task_with: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Execute single iteration with error retry."""
    attempt = 0
    while attempt < error_policy.max_attempts:
        attempt += 1
        try:
            result = executor_func(task_config, context, jinja_env, task_with or {})
            logger.info(f"Error retry attempt {attempt}: result status={result.get('status')}, checking if should retry")
            should_retry_result = error_policy.should_retry(result, attempt, None)
            logger.info(f"Error retry attempt {attempt}: should_retry={should_retry_result}")
            if not should_retry_result:
                return result
            logger.info(f"Error retry: retrying after delay (attempt {attempt}/{error_policy.max_attempts})")
            if attempt < error_policy.max_attempts:
                delay = error_policy.get_delay(attempt)
                logger.info(f"Error retry: sleeping for {delay}s before next attempt")
                time.sleep(delay)
        except Exception as e:
            logger.error(f"Error retry attempt {attempt}: exception {e}")
            if attempt >= error_policy.max_attempts or not error_policy.should_retry({'success': False}, attempt, e):
                raise
            time.sleep(error_policy.get_delay(attempt))
    raise Exception(f"Failed after {error_policy.max_attempts} attempts")


def _build_next_request(
    current_config: Dict[str, Any],
    next_call_config: Dict[str, Any],
    response: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment
) -> Dict[str, Any]:
    """
    Build next request configuration from current response.
    
    Applies next_call transformations to update params, headers, etc.
    """
    next_config = dict(current_config)
    
    # Unwrap HTTP envelope (DOUBLE unwrapping)
    # Structure: {'id': ..., 'status': ..., 'data': {'status_code': 200, 'data': <actual_response>}}
    http_metadata = response.get('data', response) if isinstance(response, dict) else response
    actual_response = http_metadata.get('data', http_metadata) if isinstance(http_metadata, dict) else http_metadata
    
    # Convert to DotDict for template rendering
    actual_response_dotted = DotDict(actual_response)
    
    # Build context for template rendering
    render_context = dict(context)
    render_context['response'] = actual_response_dotted
    render_context['page'] = actual_response_dotted
    
    # Update parameters from next_call
    if 'params' in next_call_config:
        if 'params' not in next_config:
            next_config['params'] = {}
        for key, template_str in next_call_config['params'].items():
            if isinstance(template_str, str):
                from noetl.core.dsl.render import render_template
                next_config['params'][key] = render_template(jinja_env, template_str, render_context)
            else:
                next_config['params'][key] = template_str
    
    # Update headers if specified
    if 'headers' in next_call_config:
        if 'headers' not in next_config:
            next_config['headers'] = {}
        for key, template_str in next_call_config['headers'].items():
            if isinstance(template_str, str):
                from noetl.core.dsl.render import render_template
                next_config['headers'][key] = render_template(jinja_env, template_str, render_context)
            else:
                next_config['headers'][key] = template_str
    
    # Update URL if specified
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
    """
    Execute per-iteration side effects (sink, logging, etc.).
    
    Args:
        per_iteration_config: Configuration for per-iteration effects
        response: Full response from this iteration
        page_data: Extracted page data
        iteration: Current iteration number
        context: Execution context
        jinja_env: Jinja2 environment
    """
    # Execute sink if configured
    if 'sink' in per_iteration_config:
        logger.info(f"Executing per-iteration sink for iteration {iteration}")
        
        # Build context for sink with page data
        sink_context = dict(context)
        sink_context['page'] = {'data': page_data}
        sink_context['response'] = response
        sink_context['_retry'] = {
            'index': iteration,
            'count': context.get('_retry', {}).get('count', iteration)
        }
        
        # Execute sink
        from noetl.plugin.shared.storage import execute_sink_task
        sink_config = per_iteration_config['sink']
        
        try:
            # Note: This will need to be async if executor_func is async
            # For now, assuming sync execution
            sink_result = execute_sink_task(
                sink_config,
                sink_context,
                jinja_env
            )
            
            if sink_result.get('status') != 'success':
                logger.error(f"Per-iteration sink failed: {sink_result.get('error')}")
        except Exception as e:
            logger.error(f"Per-iteration sink raised exception: {e}")
