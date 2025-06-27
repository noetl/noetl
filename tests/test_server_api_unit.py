import os
import sys
import unittest
from unittest.mock import Mock, patch, MagicMock
import tempfile
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from noetl.server import CatalogService, AgentService

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
        self.cursor_mock.fetchone.side_effect = [(0,), ('0.1.0',), (0,)]
        self.cursor_mock.fetchall.return_value = [('0.1.0',)]
        test_playbook = """
apiVersion: 0.1.0
kind: Playbook
name: test_playbook
path: test_playbook
spec:
  steps:
    - name: echo
      type: echo
      input:
        message: "Hello, World!"
        """

        with patch.object(self.catalog_service, 'get_latest_version', return_value='0.1.0'):
            with patch.object(self.catalog_service, 'increment_version', return_value='0.1.1'):
                result = self.catalog_service.register_resource(test_playbook)

        self.cursor_mock.execute.assert_any_call(
            "INSERT INTO resource (name) VALUES (%s) ON CONFLICT DO NOTHING",
            ('playbook',)
        )

        self.assertIsNotNone(result)
        self.assertIn('resource_path', result)
        self.assertEqual(result['resource_path'], 'test_playbook')

    def test_fetch_entry(self):
        self.cursor_mock.fetchone.return_value = (
            'test_playbook', 'playbook', '0.1.0', 'content', '{}', '{}'
        )
        result = self.catalog_service.fetch_entry('test_playbook', '0.1.0')
        self.assertTrue(
            any(
                call[0][0].strip().startswith("SELECT resource_path")
                for call in self.cursor_mock.execute.call_args_list
            ),
            "SELECT resource_path call not found"
        )

        self.assertIsNotNone(result)
        self.assertIn('resource_path', result)
        self.assertEqual(result['resource_path'], 'test_playbook')

    def test_list_resources(self):
        self.cursor_mock.fetchall.return_value = [
            ('test_playbook1', 'playbook', '0.1.0', '{}', '2023-01-01'),
            ('test_playbook2', 'playbook', '0.1.0', '{}', '2023-01-02')
        ]

        result = self.catalog_service.list_entries()

        self.assertTrue(
            any(
                call[0][0].strip().startswith("SELECT resource_path")
                for call in self.cursor_mock.execute.call_args_list
            ),
            "Expected SELECT resource_path... call not found"
        )

        self.assertIsNotNone(result)
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]['resource_path'], 'test_playbook1')
        self.assertEqual(result[1]['resource_path'], 'test_playbook2')

class TestAgentService(unittest.TestCase):

    def setUp(self):
        self.pgdb_conn_string = "dbname=noetl user=noetl password=noetl host=localhost port=5434"
        self.agent_service = AgentService(self.pgdb_conn_string)

    @patch('noetl.server.NoETLAgent')
    def test_execute_agent(self, mock_agent_class):
        with tempfile.NamedTemporaryFile(suffix=".yaml", delete=False) as temp_file:
            temp_file_path = temp_file.name
            temp_file.write(b"test playbook content")
            temp_file.flush()

            try:
                mock_agent = Mock()
                mock_agent.run.return_value = {"result": "success"}
                mock_agent.execution_id = "test_execution_id"
                mock_agent.playbook = {"workload": {}}
                mock_agent_class.return_value = mock_agent
                with patch('tempfile.NamedTemporaryFile') as mock_tempfile:
                    mock_temp_file = Mock()
                    mock_temp_file.name = temp_file_path
                    mock_tempfile.return_value.__enter__.return_value = mock_temp_file

                    result = self.agent_service.execute_agent(
                        playbook_content="test playbook content",
                        playbook_path="test_playbook",
                        playbook_version="0.1.0"
                    )
                mock_agent_class.assert_called_once_with(
                    temp_file_path,
                    mock_mode=False,
                    pgdb=self.pgdb_conn_string
                )
                mock_agent.run.assert_called_once()
                self.assertIsNotNone(result)
                self.assertEqual(result['status'], 'success')
                self.assertEqual(result['execution_id'], 'test_execution_id')
            finally:
                if os.path.exists(temp_file_path):
                    os.unlink(temp_file_path)

def main():
    unittest.main()

if __name__ == "__main__":
    main()
