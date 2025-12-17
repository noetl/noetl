#!/usr/bin/env python3
"""
Quick test script for the new when/then retry implementation.
"""

import sys
sys.path.insert(0, '/Users/akuksin/projects/noetl/noetl')

from jinja2 import Environment
from noetl.tools.runtime.retry import execute_with_retry

# Mock executor function
call_count = 0
def mock_executor(config, context, jinja_env, task_with):
    global call_count
    call_count += 1
    
    print(f"Mock executor called (attempt {call_count})")
    
    if call_count < 3:
        # Simulate failure
        return {
            'status': 'error',
            'data': {
                'status_code': 500,
                'data': 'Server error'
            }
        }
    else:
        # Success
        return {
            'status': 'success',
            'data': {
                'status_code': 200,
                'data': {'message': 'Success!'}
            }
        }

# Test configuration
task_config = {
    'retry': [
        {
            'when': '{{ error.status >= 500 }}',
            'then': {
                'max_attempts': 5,
                'initial_delay': 0.1,
                'backoff_multiplier': 1.5
            }
        }
    ]
}

context = {}
jinja_env = Environment()

print("Testing new when/then retry implementation...")
print("=" * 60)

try:
    result = execute_with_retry(
        mock_executor,
        task_config,
        'test_task',
        context,
        jinja_env
    )
    print("\n" + "=" * 60)
    print(f"SUCCESS! Result: {result}")
    print(f"Total attempts: {call_count}")
except Exception as e:
    print(f"\nFAILED: {e}")
    sys.exit(1)
