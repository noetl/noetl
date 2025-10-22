# """
# Unit tests for create_workload using an async mock that mimics psycopg connection/cursor
# """
# import pytest
# from unittest.mock import AsyncMock, MagicMock, patch

# from noetl.server.api.broker.execute import create_workload


# class AsyncConnCM:
#     """Simple async context manager that yields the provided connection object."""

#     def __init__(self, conn):
#         self._conn = conn

#     async def __aenter__(self):
#         return self._conn

#     async def __aexit__(self, exc_type, exc, tb):
#         return False

# """
# Unit tests for create_workload using an async mock that mimics psycopg connection/cursor
# """
# import pytest
# from unittest.mock import AsyncMock, MagicMock, patch

# from noetl.server.api.broker.execute import create_workload


# class AsyncConnCM:
#     """Async context manager that yields the provided connection object."""

#     def __init__(self, conn):
#         self._conn = conn

#     async def __aenter__(self):
#         return self._conn

#     async def __aexit__(self, exc_type, exc, tb):
#         return False


# def make_mock_conn_with_cursor(exec_id: int):
#     """Return (mock_conn, mock_cursor) where cursor is an async context manager."""
#     mock_cursor = AsyncMock()
#     mock_cursor.fetchone = AsyncMock(return_value={"execution_id": exec_id})
#     mock_cursor.execute = AsyncMock()

#     cursor_cm = AsyncMock()
#     cursor_cm.__aenter__ = AsyncMock(return_value=mock_cursor)
#     cursor_cm.__aexit__ = AsyncMock(return_value=None)

#     mock_conn = MagicMock()
#     # conn.cursor() -> async context manager
#     mock_conn.cursor = MagicMock(return_value=cursor_cm)
#     mock_conn.commit = AsyncMock()

#     return mock_conn, mock_cursor


# @pytest.mark.asyncio
# async def test_create_workload_basic():
#     mock_conn, mock_cursor = make_mock_conn_with_cursor(12345)
#     conn_cm = AsyncConnCM(mock_conn)

#     with patch("noetl.server.api.broker.execute.get_async_db_connection", return_value=conn_cm):
#         path = "test/playbook"
#         version = "1.0.0"
#         workload = {"test": "data", "number": 42}

#         result = await create_workload(path, version, workload)

#         assert result == 12345

#         mock_cursor.execute.assert_called_once()
#         sql, params = mock_cursor.execute.call_args[0]
#         assert "INSERT INTO noetl.workload" in sql
#         assert "RETURNING execution_id" in sql
#         assert params["data"]["path"] == path
#         assert params["data"]["version"] == version
#         assert params["data"]["workload"] == workload


# @pytest.mark.asyncio
# async def test_create_workload_none_workload():
#     mock_conn, mock_cursor = make_mock_conn_with_cursor(67890)
#     conn_cm = AsyncConnCM(mock_conn)

#     with patch("noetl.server.api.broker.execute.get_async_db_connection", return_value=conn_cm):
#         result = await create_workload("test/path", "2.0.0", None)

#         assert result == 67890

#         mock_cursor.execute.assert_called_once()
#         sql, params = mock_cursor.execute.call_args[0]
#         assert params["data"]["workload"] == {}
#     class MockConnCM:
#         def __init__(self, conn):
#             self.conn = conn
        
#         async def __aenter__(self):
#             return self.conn
        
#         async def __aexit__(self, exc_type, exc_val, exc_tb):
#             pass

#     mock_conn_cm = MockConnCM(mock_conn)

#     with patch('noetl.server.api.broker.execute.get_async_db_connection', return_value=mock_conn_cm):
#         # Test data
#         path = "test/playbook"
#         version = "1.0.0"
#         workload = {"test": "data", "number": 42}

#         # Call the function
#         result = await create_workload(path, version, workload)

#         # Assertions
#         assert result == 12345
#         assert isinstance(result, int)

#         # Verify the execute was called with correct parameters
#         mock_cursor.execute.assert_called_once()
#         call_args = mock_cursor.execute.call_args
#         assert "INSERT INTO noetl.workload" in call_args[0][0]
#         assert "RETURNING execution_id" in call_args[0][0]

#         # Verify payload structure
#         payload = call_args[0][1]["data"]
#         assert payload["path"] == path
#         assert payload["version"] == version
#         assert payload["workload"] == workload


# @pytest.mark.asyncio
# async def test_create_workload_empty_workload():
#     """Test create_workload with None workload"""
#     # Mock the database connection and cursor
#     mock_cursor = AsyncMock()
#     mock_cursor.fetchone.return_value = {"execution_id": 67890}
#     mock_cursor.execute = AsyncMock()

#     mock_conn = AsyncMock()
#     # Create cursor context manager
#     cursor_cm = AsyncMock()
#     cursor_cm.__aenter__.return_value = mock_cursor
#     cursor_cm.__aexit__.return_value = None
#     mock_conn.cursor = AsyncMock(return_value=cursor_cm)
#     mock_conn.commit = AsyncMock()

#     # Create a proper async context manager mock
#     class MockConnCM:
#         def __init__(self, conn):
#             self.conn = conn
        
#         async def __aenter__(self):
#             return self.conn
        
#         async def __aexit__(self, exc_type, exc_val, exc_tb):
#             pass

#     mock_conn_cm = MockConnCM(mock_conn)

#     with patch('noetl.server.api.broker.execute.get_async_db_connection', return_value=mock_conn_cm):
#         # Test with None workload
#         result = await create_workload("test/path", "2.0.0", None)

#         assert result == 67890

#         # Verify payload has empty dict for workload
#         call_args = mock_cursor.execute.call_args
#         payload = call_args[0][1]["data"]
#         assert payload["workload"] == {}