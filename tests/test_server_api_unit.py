import os
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock
import tempfile
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from noetl.server import CatalogService

class TestCatalogService(unittest.TestCase):
    def setUp(self):
        self.psycopg_connect_patcher = patch('noetl.server.psycopg.connect')
        self.mock_connect = self.psycopg_connect_patcher.start()
        self.conn_mock = Mock()
        self.cursor_mock = Mock()
        self.conn_mock.cursor.return_value = MagicMock()
        self.conn_mock.cursor.return_value.__enter__.return_value = self.cursor_mock
        self.mock_connect.return_value = self.conn_mock
        self.addCleanup(self.psycopg_connect_patcher.stop)
        self.catalog_service = CatalogService()

    def test_register_resource(self):
        self.cursor_mock.fetchone.side_effect = [(0,), (0,)]  # COUNT queries should return integers
        self.cursor_mock.fetchall.return_value = []  # No existing versions
        test_playbook = """
apiVersion: 0.1.0
kind: Playbook
name: test_playbook
path: test_playbook
steps:
  - name: test_step
    action: log
    input:
      message: "Hello World"
"""

        result = self.catalog_service.register_resource(test_playbook)

        self.assertIsInstance(result, dict)
        self.assertIn('resource_path', result)
        self.assertIn('resource_version', result)
        self.assertEqual(result['resource_path'], 'test_playbook')

    def test_get_latest_version_no_entries(self):
        self.cursor_mock.fetchone.return_value = (0,)

        version = self.catalog_service.get_latest_version('nonexistent_resource')

        self.assertEqual(version, '0.1.0')

    def test_get_latest_version_with_entries(self):
        self.cursor_mock.fetchone.side_effect = [(2,), ('0.2.0',)]
        self.cursor_mock.fetchall.return_value = [('0.1.0',), ('0.2.0',)]

        version = self.catalog_service.get_latest_version('existing_resource')

        self.assertEqual(version, '0.2.0')

    def test_increment_version(self):
        test_cases = [
            ('0.1.0', '0.1.1'),
            ('1.0.0', '1.0.1'),
            ('2.5.3', '2.5.4'),
            ('1.0', '1.0.1'),
            ('1', '1.0.1')
        ]

        for input_version, expected in test_cases:
            with self.subTest(input_version=input_version):
                result = self.catalog_service.increment_version(input_version)
                self.assertEqual(result, expected)

    def test_fetch_entry_found(self):
        mock_result = ('test_path', 'playbook', '0.1.0', 'content', 'payload', 'meta')
        self.cursor_mock.fetchone.return_value = mock_result

        result = self.catalog_service.fetch_entry('test_path', '0.1.0')

        self.assertIsNotNone(result)
        self.assertEqual(result['resource_path'], 'test_path')
        self.assertEqual(result['resource_version'], '0.1.0')

    def test_fetch_entry_not_found(self):
        self.cursor_mock.fetchone.return_value = None

        result = self.catalog_service.fetch_entry('nonexistent', '0.1.0')

        self.assertIsNone(result)

    def test_fetch_entry_with_path_fallback(self):
        self.cursor_mock.fetchone.side_effect = [None, ('filename', 'playbook', '0.1.0', 'content', 'payload', 'meta')]

        result = self.catalog_service.fetch_entry('path/to/filename', '0.1.0')

        self.assertIsNotNone(result)
        self.assertEqual(result['resource_path'], 'filename')

if __name__ == '__main__':
    unittest.main()
