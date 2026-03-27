"""
HTTP plugin package for NoETL.

Provides HTTP request execution capabilities with authentication,
request/response handling, and development mocking support.
"""

from noetl.tools.http.executor import execute_http_task, close_shared_async_http_clients

__all__ = ['execute_http_task', 'close_shared_async_http_clients']
