"""
HTTP plugin package for NoETL.

Provides HTTP request execution capabilities with authentication,
request/response handling, and development mocking support.
"""

from noetl.tools.http.executor import execute_http_task

__all__ = ['execute_http_task']
