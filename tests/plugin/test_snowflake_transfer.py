#!/usr/bin/env python3
"""
Snowflake Transfer Plugin - Unit Tests

Tests the transfer module functionality without requiring actual database connections.
Uses mocks to verify the logic and flow.
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from decimal import Decimal
from datetime import datetime

# Import the transfer module
from noetl.plugin.snowflake.transfer import (
    _convert_value,
    transfer_snowflake_to_postgres,
    transfer_postgres_to_snowflake
)


class TestValueConversion:
    """Test the _convert_value helper function"""
    
    def test_none_value(self):
        """Test that None is preserved"""
        assert _convert_value(None) is None
    
    def test_string_value(self):
        """Test that strings pass through unchanged"""
        assert _convert_value("test") == "test"
        assert _convert_value("") == ""
    
    def test_integer_value(self):
        """Test that integers pass through unchanged"""
        assert _convert_value(123) == 123
        assert _convert_value(0) == 0
        assert _convert_value(-456) == -456
    
    def test_decimal_conversion(self):
        """Test that Decimal is converted to float"""
        assert _convert_value(Decimal("123.45")) == 123.45
        assert _convert_value(Decimal("0")) == 0.0
    
    def test_datetime_conversion(self):
        """Test that datetime is converted to ISO format"""
        dt = datetime(2024, 1, 15, 12, 30, 45)
        result = _convert_value(dt)
        assert result == "2024-01-15T12:30:45"
    
    def test_date_conversion(self):
        """Test that date is converted to ISO format"""
        from datetime import date
        d = date(2024, 1, 15)
        result = _convert_value(d)
        assert result == "2024-01-15"


class TestSnowflakeToPostgres:
    """Test Snowflake to PostgreSQL transfer"""
    
    @patch('noetl.plugin.snowflake.transfer.logger')
    def test_successful_transfer(self, mock_logger):
        """Test successful data transfer with single chunk"""
        # Mock Snowflake cursor
        sf_cursor = Mock()
        sf_cursor.description = [['id'], ['name'], ['value']]
        sf_cursor.fetchmany.side_effect = [
            [(1, 'Alice', 100.5), (2, 'Bob', 200.75)],  # First chunk
            []  # End of data
        ]
        
        # Mock Snowflake connection
        sf_conn = Mock()
        sf_conn.cursor.return_value = sf_cursor
        
        # Mock PostgreSQL cursor
        pg_cursor = Mock()
        pg_cursor.__enter__ = Mock(return_value=pg_cursor)
        pg_cursor.__exit__ = Mock(return_value=False)
        
        # Mock PostgreSQL connection
        pg_conn = Mock()
        pg_conn.cursor.return_value = pg_cursor
        pg_conn.commit = Mock()
        
        # Execute transfer
        result = transfer_snowflake_to_postgres(
            sf_conn=sf_conn,
            pg_conn=pg_conn,
            source_query="SELECT * FROM test_table",
            target_table="public.target",
            chunk_size=1000,
            mode='append'
        )
        
        # Verify results
        assert result['status'] == 'success'
        assert result['rows_transferred'] == 2
        assert result['chunks_processed'] == 1
        assert result['target_table'] == 'public.target'
        assert result['columns'] == ['id', 'name', 'value']
        
        # Verify cursor was called
        sf_cursor.execute.assert_called_once()
        sf_cursor.close.assert_called_once()
        
        # Verify commit was called
        pg_conn.commit.assert_called()
    
    @patch('noetl.plugin.snowflake.transfer.logger')
    def test_multiple_chunks(self, mock_logger):
        """Test transfer with multiple chunks"""
        sf_cursor = Mock()
        sf_cursor.description = [['id'], ['name']]
        sf_cursor.fetchmany.side_effect = [
            [(1, 'A'), (2, 'B')],  # Chunk 1
            [(3, 'C'), (4, 'D')],  # Chunk 2
            [(5, 'E')],            # Chunk 3
            []                      # End
        ]
        
        sf_conn = Mock()
        sf_conn.cursor.return_value = sf_cursor
        
        pg_cursor = Mock()
        pg_cursor.__enter__ = Mock(return_value=pg_cursor)
        pg_cursor.__exit__ = Mock(return_value=False)
        
        pg_conn = Mock()
        pg_conn.cursor.return_value = pg_cursor
        
        result = transfer_snowflake_to_postgres(
            sf_conn=sf_conn,
            pg_conn=pg_conn,
            source_query="SELECT * FROM test",
            target_table="public.target",
            chunk_size=2
        )
        
        assert result['status'] == 'success'
        assert result['rows_transferred'] == 5
        assert result['chunks_processed'] == 3
    
    @patch('noetl.plugin.snowflake.transfer.logger')
    def test_replace_mode(self, mock_logger):
        """Test transfer with replace mode"""
        sf_cursor = Mock()
        sf_cursor.description = [['id']]
        sf_cursor.fetchmany.side_effect = [[(1,)], []]
        
        sf_conn = Mock()
        sf_conn.cursor.return_value = sf_cursor
        
        pg_cursor = Mock()
        pg_cursor.__enter__ = Mock(return_value=pg_cursor)
        pg_cursor.__exit__ = Mock(return_value=False)
        
        pg_conn = Mock()
        pg_conn.cursor.return_value = pg_cursor
        
        result = transfer_snowflake_to_postgres(
            sf_conn=sf_conn,
            pg_conn=pg_conn,
            source_query="SELECT * FROM test",
            target_table="public.target",
            mode='replace'
        )
        
        # Verify TRUNCATE was called
        pg_cursor.execute.assert_any_call('TRUNCATE TABLE public.target')
        assert result['status'] == 'success'
    
    @patch('noetl.plugin.snowflake.transfer.logger')
    def test_error_handling(self, mock_logger):
        """Test error handling during transfer"""
        sf_cursor = Mock()
        sf_cursor.execute.side_effect = Exception("Connection error")
        
        sf_conn = Mock()
        sf_conn.cursor.return_value = sf_cursor
        
        pg_conn = Mock()
        
        result = transfer_snowflake_to_postgres(
            sf_conn=sf_conn,
            pg_conn=pg_conn,
            source_query="SELECT * FROM test",
            target_table="public.target"
        )
        
        assert result['status'] == 'error'
        assert 'error' in result
        assert 'Connection error' in result['error']


class TestPostgresToSnowflake:
    """Test PostgreSQL to Snowflake transfer"""
    
    @patch('noetl.plugin.snowflake.transfer.logger')
    def test_successful_transfer(self, mock_logger):
        """Test successful PG to SF transfer"""
        # Mock PostgreSQL cursor
        pg_cursor = Mock()
        pg_cursor.description = [['id'], ['name']]
        pg_cursor.fetchmany.side_effect = [
            [(1, 'Alice'), (2, 'Bob')],
            []
        ]
        pg_cursor.__enter__ = Mock(return_value=pg_cursor)
        pg_cursor.__exit__ = Mock(return_value=False)
        
        pg_conn = Mock()
        pg_conn.cursor.return_value = pg_cursor
        
        # Mock Snowflake cursor
        sf_cursor = Mock()
        
        sf_conn = Mock()
        sf_conn.cursor.return_value = sf_cursor
        
        result = transfer_postgres_to_snowflake(
            pg_conn=pg_conn,
            sf_conn=sf_conn,
            source_query="SELECT * FROM test",
            target_table="TARGET_TABLE",
            chunk_size=1000
        )
        
        assert result['status'] == 'success'
        assert result['rows_transferred'] == 2
        assert result['chunks_processed'] == 1


class TestProgressCallback:
    """Test progress callback functionality"""
    
    @patch('noetl.plugin.snowflake.transfer.logger')
    def test_progress_callback_called(self, mock_logger):
        """Test that progress callback is invoked"""
        progress_calls = []
        
        def progress_cb(rows, total):
            progress_calls.append((rows, total))
        
        sf_cursor = Mock()
        sf_cursor.description = [['id']]
        sf_cursor.fetchmany.side_effect = [
            [(1,), (2,)],
            [(3,), (4,)],
            []
        ]
        
        sf_conn = Mock()
        sf_conn.cursor.return_value = sf_cursor
        
        pg_cursor = Mock()
        pg_cursor.__enter__ = Mock(return_value=pg_cursor)
        pg_cursor.__exit__ = Mock(return_value=False)
        
        pg_conn = Mock()
        pg_conn.cursor.return_value = pg_cursor
        
        result = transfer_snowflake_to_postgres(
            sf_conn=sf_conn,
            pg_conn=pg_conn,
            source_query="SELECT * FROM test",
            target_table="public.target",
            chunk_size=2,
            progress_callback=progress_cb
        )
        
        # Verify callback was called for each chunk
        assert len(progress_calls) == 2
        assert progress_calls[0] == (2, -1)
        assert progress_calls[1] == (4, -1)


if __name__ == '__main__':
    # Run tests using pytest
    import sys
    
    print("Running Snowflake Transfer Plugin Unit Tests...\n")
    print("To run all tests with pytest:")
    print("  pytest tests/plugin/test_snowflake_transfer.py -v\n")
    
    # Simple smoke test
    print("Running basic smoke tests...")
    
    # Test value conversion
    test_conv = TestValueConversion()
    test_conv.test_none_value()
    test_conv.test_string_value()
    test_conv.test_integer_value()
    test_conv.test_decimal_conversion()
    test_conv.test_datetime_conversion()
    test_conv.test_date_conversion()
    print("✓ Value conversion tests passed")
    
    print("\n" + "═" * 60)
    print("Basic smoke tests passed! ✓")
    print("═" * 60)
    print("\nFor full test coverage, run:")
    print("  pytest tests/plugin/test_snowflake_transfer.py -v")
    print("\nOr use NoETL's test command:")
    print("  task test")
    
    sys.exit(0)
