"""
Retry logic for task execution.

This module provides retry functionality for NoETL tasks with configurable
retry policies based on expression evaluation.
"""

import time
from typing import Dict, Any, Optional, Callable
from jinja2 import Environment, Template

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


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
        self.retry_when = retry_config.get('retry_when', None)
        
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
        if attempt >= self.max_attempts:
            logger.info(f"Max retry attempts ({self.max_attempts}) reached")
            return False
            
        # Build context for expression evaluation
        eval_context = {
            'result': result,
            'attempt': attempt,
            'error': str(error) if error else None,
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
                template = self.jinja_env.from_string(self.retry_when)
                should_retry = template.render(**eval_context)
                # Convert to boolean
                retry = str(should_retry).lower() in ('true', '1', 'yes')
                logger.info(f"Retry condition '{self.retry_when}' evaluated to: {retry}")
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


def execute_with_retry(
    executor_func: Callable,
    task_config: Dict[str, Any],
    task_name: str,
    context: Dict[str, Any],
    jinja_env: Environment,
    task_with: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a task with retry logic.
    
    Args:
        executor_func: The actual task executor function
        task_config: Task configuration
        task_name: Name of the task
        context: Execution context
        jinja_env: Jinja2 environment
        task_with: Additional parameters
        log_event_callback: Event logging callback
        
    Returns:
        Task execution result
        
    Raises:
        Exception: If all retry attempts fail
    """
    # Check if retry is configured
    retry_config = task_config.get('retry')
    if not retry_config:
        # No retry configured, execute once
        return executor_func(task_config, context, jinja_env, task_with or {}, log_event_callback)
    
    # Parse retry configuration
    if isinstance(retry_config, bool):
        # Simple retry: true = default policy, false = no retry
        if not retry_config:
            return executor_func(task_config, context, jinja_env, task_with or {}, log_event_callback)
        retry_config = {}  # Use defaults
    elif isinstance(retry_config, int):
        # Retry with max attempts only
        retry_config = {'max_attempts': retry_config}
    elif not isinstance(retry_config, dict):
        logger.warning(f"Invalid retry configuration: {retry_config}, ignoring")
        return executor_func(task_config, context, jinja_env, task_with or {}, log_event_callback)
    
    # Create retry policy
    policy = RetryPolicy(retry_config, jinja_env)
    
    # Execute with retry
    attempt = 0
    last_error = None
    last_result = None
    
    while attempt < policy.max_attempts:
        attempt += 1
        logger.info(f"Executing task '{task_name}' (attempt {attempt}/{policy.max_attempts})")
        
        try:
            # Execute task
            result = executor_func(task_config, context, jinja_env, task_with or {}, log_event_callback)
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
