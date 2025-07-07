import os
import sys
import time
import base64
import requests
import subprocess
import tempfile
import logging
import psycopg
import signal
import socket
import unittest
import json
from unittest.mock import Mock, patch, MagicMock
from fastapi.testclient import TestClient
from fastapi import FastAPI

logging.basicConfig(
    format='[%(levelname)s] %(asctime)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

SERVER_HOST = "localhost"
SERVER_PORT = 8083
SERVER_URL = f"http://{SERVER_HOST}:{SERVER_PORT}"

DB_CONN_STRING = "dbname=noetl user=noetl password=noetl host=localhost port=5434"

def check_port(port, host='localhost'):
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except socket.error:
        return False
    finally:
        sock.close()

def kill_process(port):
    logger.info(f"Checking for processes using port {port}...")

    if check_port(port):
        logger.info(f"Port {port} is already available")
        return True

    logger.info(f"Port {port} is in use. Attempting to kill the process...")

    try:
        if sys.platform.startswith('darwin') or sys.platform.startswith('linux'):
            cmd = f"lsof -i :{port} -t"
            try:
                output = subprocess.check_output(cmd, shell=True).decode().strip()

                if output:
                    pids = output.split('\n')
                    killed = False

                    for pid in pids:
                        if pid.strip():
                            logger.info(f"Killing process {pid} using port {port}")
                            try:
                                os.kill(int(pid), signal.SIGTERM)
                                time.sleep(1)
                                try:
                                    os.kill(int(pid), 0)
                                    logger.info(f"Process {pid} did not terminate, sending SIGKILL")
                                    os.kill(int(pid), signal.SIGKILL)
                                except OSError:
                                    logger.info(f"Process {pid} terminated successfully")

                                killed = True
                            except OSError as e:
                                logger.warning(f"Error killing process {pid}: {e}")

                    if check_port(port):
                        logger.info(f"Port {port} is now available")
                        return True
                    else:
                        logger.warning(f"Port {port} is still in use after killing processes")
                        return False
            except subprocess.CalledProcessError as e:
                logger.warning(f"Error running lsof command: {e}.")
                time.sleep(2)
                if check_port(port):
                    logger.info(f"Port {port} is now available")
                    return True
        elif sys.platform.startswith('win'):
            cmd = f"netstat -ano | findstr :{port}"
            output = subprocess.check_output(cmd, shell=True).decode()

            if output:
                lines = output.strip().split('\n')
                killed = False

                for line in lines:
                    if f":{port}" in line and "LISTENING" in line:
                        pid = line.strip().split()[-1]
                        logger.info(f"Killing process {pid} using port {port}")
                        try:
                            result = subprocess.call(f"taskkill /F /PID {pid}", shell=True)
                            if result == 0:
                                logger.info(f"Process {pid} terminated successfully")
                                killed = True
                            else:
                                logger.warning(f"Failed to kill process {pid}")
                        except Exception as e:
                            logger.warning(f"Error killing process {pid}: {e}")

                if check_port(port):
                    logger.info(f"Port {port} is now available")
                    return True
                else:
                    logger.warning(f"Port {port} is still in use after killing processes")
                    return False

        logger.warning(f"Could not kill process using port {port}")
        if check_port(port):
            logger.info(f"Port {port} is now available")
            return True
        return False
    except Exception as e:
        logger.error(f"Error killing process on port {port}: {e}")
        if check_port(port):
            logger.info(f"Port {port} is now available despite errors")
            return True
        return False

def start_server():
    logger.info("Starting NoETL server...")
    if not kill_process(SERVER_PORT):
        logger.error(f"Failed to free up port {SERVER_PORT}. Cannot start server.")
        return None, None

    server_log = tempfile.NamedTemporaryFile(delete=False, suffix=".log")
    server_log_path = server_log.name
    server_log.close()

    cmd = [
        "noetl",
        "server",
        "--port", str(SERVER_PORT),
        "--force"
    ]

    logger.info(f"Running command: {' '.join(cmd)}")

    with open(server_log_path, "w") as log_file:
        server_process = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            preexec_fn=os.setsid
        )

    logger.info("Waiting for server to start...")
    max_retries = 10
    retry_interval = 1

    for i in range(max_retries):
        try:
            response = requests.get(f"{SERVER_URL}/health")
            if response.status_code == 200:
                logger.info("Server started successfully")
                return server_process, server_log_path
        except requests.exceptions.ConnectionError:
            pass

        logger.info(f"Waiting for server to start (attempt {i+1}/{max_retries})...")
        time.sleep(retry_interval)
    logger.error("Failed to start server")

    try:
        with open(server_log_path, "r") as log_file:
            logger.error(f"Server log:\n{log_file.read()}")
    except Exception as e:
        logger.error(f"Error reading server log: {e}")

    try:
        os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
    except Exception as e:
        logger.error(f"Error killing server process: {e}")

    return None, server_log_path

def stop_server(server_process, server_log_path):
    if server_process:
        logger.info("Stopping NoETL server")
        try:
            os.killpg(os.getpgid(server_process.pid), signal.SIGTERM)
            server_process.wait(timeout=5)
            logger.info("Server stopped")
        except Exception as e:
            logger.error(f"Error stopping server: {e}")
            try:
                os.killpg(os.getpgid(server_process.pid), signal.SIGKILL)
            except:
                pass
    if server_log_path and os.path.exists(server_log_path):
        try:
            with open(server_log_path, "r") as log_file:
                logger.info(f"Server log:\n{log_file.read()}")
            os.unlink(server_log_path)
        except Exception as e:
            logger.error(f"Error reading/removing server log: {e}")

def clean_database():
    try:
        conn = psycopg.connect(DB_CONN_STRING)
        with conn.cursor() as cursor:
            cursor.execute(
                "DELETE FROM catalog WHERE resource_path LIKE 'test_%'"
            )
        conn.commit()
        conn.close()
        logger.info("Database cleaned up")
    except Exception as e:
        logger.error(f"Error cleaning database: {e}")

def test_upload_playbook():
    logger.info("Testing playbook upload")
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

    playbook_base64 = base64.b64encode(test_playbook.encode()).decode()

    response = requests.post(
        f"{SERVER_URL}/catalog/register",
        json={"content_base64": playbook_base64}
    )

    if response.status_code == 200:
        logger.info("Playbook uploaded")
        logger.info(f"Response: {response.json()}")
        return True
    else:
        logger.error(f"Failed to upload playbook: {response.status_code}")
        logger.error(f"Response: {response.text}")
        return False

def test_list_playbooks():
    logger.info("Testing playbook listing")
    response = requests.get(f"{SERVER_URL}/catalog/list")

    if response.status_code == 200:
        response_data = response.json()
        playbooks = response_data.get("entries", [])
        logger.info(f"Found {len(playbooks)} playbooks")

        test_playbook_found = False
        for playbook in playbooks:
            if playbook.get("resource_path") == "test_playbook":
                test_playbook_found = True
                logger.info("Test playbook found in catalog")
                break

        if not test_playbook_found:
            logger.error("Test playbook not found in catalog")
            logger.info(f"Playbooks in catalog: {playbooks}")
            return False

        return True
    else:
        logger.error(f"Failed to list playbooks: {response.status_code}")
        logger.error(f"Response: {response.text}")
        return False

def test_execute_playbook():
    logger.info("Testing playbook execution")
    response = requests.get(f"{SERVER_URL}/catalog/list")
    if response.status_code != 200:
        logger.error(f"Failed to list playbooks: {response.status_code}")
        logger.error(f"Response: {response.text}")
        return False

    playbooks = response.json().get("entries", [])
    test_playbook_version = None
    for playbook in playbooks:
        if playbook.get("resource_path") == "test_playbook":
            test_playbook_version = playbook.get("resource_version")
            break

    if not test_playbook_version:
        logger.error("Test playbook not found in catalog")
        return False

    logger.info(f"Using test playbook version: {test_playbook_version}")

    response = requests.post(
        f"{SERVER_URL}/agent/execute",
        json={
            "path": "test_playbook",
            "version": test_playbook_version,
            "input_payload": {"additional_message": "Testing execution"}
        }
    )

    if response.status_code == 200:
        result = response.json()
        logger.info("Playbook executed successfully")
        logger.info(f"Response: {result}")
        if result.get("status") == "success":
            return True
        else:
            logger.error(f"Execution failed: {result.get('error')}")
            return False
    else:
        logger.error(f"Failed to execute playbook: {response.status_code}")
        logger.error(f"Response: {response.text}")
        return False

def test_execute_playbook_async():
    logger.info("Testing asynchronous playbook execution")
    response = requests.get(f"{SERVER_URL}/catalog/list")
    if response.status_code != 200:
        logger.error(f"Failed to list playbooks: {response.status_code}")
        logger.error(f"Response: {response.text}")
        return False

    playbooks = response.json().get("entries", [])
    test_playbook_version = None
    for playbook in playbooks:
        if playbook.get("resource_path") == "test_playbook":
            test_playbook_version = playbook.get("resource_version")
            break

    if not test_playbook_version:
        logger.error("Test playbook not found in catalog")
        return False

    logger.info(f"Using test playbook version: {test_playbook_version}")
    response = requests.post(
        f"{SERVER_URL}/agent/execute-async",
        json={
            "path": "test_playbook",
            "version": test_playbook_version,
            "input_payload": {"additional_message": "Testing async execution"}
        }
    )

    if response.status_code == 200:
        result = response.json()
        logger.info("Playbook execution started asynchronously")
        logger.info(f"Response: {result}")

        event_id = result.get("event_id")
        if not event_id:
            logger.error("No event ID returned")
            return False

        max_retries = 10
        retry_interval = 1

        for i in range(max_retries):
            response = requests.get(f"{SERVER_URL}/events/{event_id}")

            if response.status_code == 200:
                event = response.json()
                state = event.get("state")

                if state in ["COMPLETED", "FAILED", "ERROR"]:
                    logger.info(f"Execution completed with state: {state}")
                    return state == "COMPLETED"

            logger.info(f"Waiting for execution to complete (attempt {i+1}/{max_retries})...")
            time.sleep(retry_interval)

        logger.error("Execution did not complete in time")
        return False
    else:
        logger.error(f"Failed to start async execution: {response.status_code}")
        logger.error(f"Response: {response.text}")
        return False

def test_get_event_by_query_param():
    logger.info("Testing event retrieval using event_id path endpoint...")
    response = requests.get(f"{SERVER_URL}/catalog/list")
    if response.status_code != 200:
        logger.error(f"Failed to list playbooks: {response.status_code}")
        logger.error(f"Response: {response.text}")
        return False

    playbooks = response.json().get("entries", [])
    test_playbook_version = None
    for playbook in playbooks:
        if playbook.get("resource_path") == "test_playbook":
            test_playbook_version = playbook.get("resource_version")
            break

    if not test_playbook_version:
        logger.error("Test playbook not found in catalog")
        return False

    logger.info(f"Using test playbook version: {test_playbook_version}")
    response = requests.post(
        f"{SERVER_URL}/agent/execute-async",
        json={
            "path": "test_playbook",
            "version": test_playbook_version,
            "input_payload": {"additional_message": "Testing event query"}
        }
    )

    if response.status_code == 200:
        result = response.json()
        logger.info("Playbook execution started asynchronously")
        logger.info(f"Response: {result}")
        event_id = result.get("event_id")
        if not event_id:
            logger.error("No event ID returned")
            return False
        time.sleep(1)

        response = requests.get(f"{SERVER_URL}/events/{event_id}")

        if response.status_code == 200:
            event = response.json()
            logger.info("Event retrieved successfully using event_id path endpoint")
            logger.info(f"Response: {event}")
            return True
        else:
            logger.error(f"Failed to retrieve event using event_id path endpoint: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
    else:
        logger.error(f"Failed to start async execution: {response.status_code}")
        logger.error(f"Response: {response.text}")
        return False

def test_get_resource_with_path_segments():
    logger.info("Testing resource retrieval with path segments")
    test_playbook = """
apiVersion: 0.1.0
kind: Playbook
name: test_playbook_segments
path: test/segments/playbook
spec:
  steps:
    - name: echo
      type: echo
      input:
        message: "Hello, World!"
    """

    playbook_base64 = base64.b64encode(test_playbook.encode()).decode()

    response = requests.post(
        f"{SERVER_URL}/catalog/register",
        json={"content_base64": playbook_base64}
    )

    if response.status_code == 200:
        result = response.json()
        logger.info("Playbook with path segments uploaded successfully")
        logger.info(f"Response: {result}")

        path = result.get("resource_path")
        version = result.get("resource_version")

        if not path or not version:
            logger.error("No path or version returned")
            return False

        response = requests.get(f"{SERVER_URL}/catalog/{path}/{version}")

        if response.status_code == 200:
            resource = response.json()
            logger.info("Resource retrieved successfully with path segments")
            logger.info(f"Response: {resource}")
            return True
        else:
            logger.error(f"Failed to retrieve resource with path segments: {response.status_code}")
            logger.error(f"Response: {response.text}")
            return False
    else:
        logger.error(f"Failed to upload playbook with path segments: {response.status_code}")
        logger.error(f"Response: {response.text}")
        return False

# Integration tests
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# Mock the dependencies before importing
with patch('noetl.server.get_pgdb_connection') as mock_pgdb:
    mock_pgdb.return_value = "mock://connection"
    from noetl.server import CatalogService, EventService

class TestServerAPIIntegration(unittest.TestCase):
    def setUp(self):
        # Mock database connections
        self.psycopg_connect_patcher = patch('noetl.server.psycopg.connect')
        self.mock_connect = self.psycopg_connect_patcher.start()

        self.conn_mock = Mock()
        self.cursor_mock = Mock()
        self.conn_mock.cursor.return_value = MagicMock()
        self.conn_mock.cursor.return_value.__enter__.return_value = self.cursor_mock
        self.mock_connect.return_value = self.conn_mock

        self.addCleanup(self.psycopg_connect_patcher.stop)

        # Initialize services
        self.catalog_service = CatalogService()
        self.event_service = EventService()

    def test_catalog_service_integration(self):
        """Test CatalogService with realistic scenarios"""
        # Test successful resource registration - fix mock setup
        self.cursor_mock.fetchone.side_effect = [(0,), (0,)]  # COUNT queries return integers
        self.cursor_mock.fetchall.return_value = []  # No existing versions

        test_playbook = """
apiVersion: 0.1.0
kind: Playbook
name: test_integration_playbook
path: test_integration_playbook
description: Integration test playbook
steps:
  - name: log_step
    action: log
    input:
      message: "Integration test message"
"""

        result = self.catalog_service.register_resource(test_playbook)

        # Verify the result structure
        self.assertIsInstance(result, dict)
        self.assertIn('status', result)
        self.assertIn('resource_path', result)
        self.assertIn('resource_version', result)
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['resource_path'], 'test_integration_playbook')

    def test_catalog_list_entries(self):
        """Test listing catalog entries"""
        mock_entries = [
            ('playbook1', 'playbook', '0.1.0', '{}', '2023-01-01'),
            ('playbook2', 'playbook', '0.2.0', '{}', '2023-01-02'),
        ]
        self.cursor_mock.fetchall.return_value = mock_entries

        entries = self.catalog_service.list_entries()

        self.assertIsInstance(entries, list)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]['resource_path'], 'playbook1')
        self.assertEqual(entries[1]['resource_path'], 'playbook2')

    def test_catalog_list_entries_filtered(self):
        """Test listing catalog entries with resource type filter"""
        mock_entries = [
            ('playbook1', 'playbook', '0.1.0', '{}', '2023-01-01'),
        ]
        self.cursor_mock.fetchall.return_value = mock_entries

        entries = self.catalog_service.list_entries(resource_type='playbook')

        self.assertIsInstance(entries, list)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]['resource_type'], 'playbook')

    def test_event_service_emit(self):
        """Test EventService emit functionality"""
        self.cursor_mock.fetchone.return_value = (0,)  # Return count as tuple

        event_data = {
            "event_type": "TEST_EVENT",
            "status": "CREATED",
            "message": "Test event message"
        }

        result = self.event_service.emit(event_data)

        # Verify event_id was added
        self.assertIn('event_id', result)
        self.assertEqual(result['event_type'], 'TEST_EVENT')
        self.assertEqual(result['status'], 'CREATED')

    def test_catalog_version_management(self):
        """Test version increment logic"""
        test_cases = [
            ('0.1.0', '0.1.1'),
            ('1.2.3', '1.2.4'),
            ('0.0.1', '0.0.2'),
            ('10.20.30', '10.20.31')
        ]

        for input_version, expected_output in test_cases:
            with self.subTest(input_version=input_version):
                result = self.catalog_service.increment_version(input_version)
                self.assertEqual(result, expected_output)

    def test_catalog_fetch_with_fallback(self):
        """Test fetch entry with path fallback logic"""
        # First call returns None (path not found), second call finds filename
        self.cursor_mock.fetchone.side_effect = [
            None,  # First query with full path fails
            ('filename.yaml', 'playbook', '0.1.0', 'content', '{}', '{}')  # Second query with filename succeeds
        ]

        result = self.catalog_service.fetch_entry('some/path/to/filename.yaml', '0.1.0')

        self.assertIsNotNone(result)
        self.assertEqual(result['resource_path'], 'filename.yaml')
        self.assertEqual(result['resource_version'], '0.1.0')

    def test_catalog_error_handling(self):
        """Test error handling in catalog operations"""
        # Test database connection error
        self.mock_connect.side_effect = Exception("Database connection failed")

        version = self.catalog_service.get_latest_version('test_resource')
        self.assertEqual(version, '0.1.0')  # Should return default on error

        # Reset the mock
        self.mock_connect.side_effect = None
        self.mock_connect.return_value = self.conn_mock

    def test_catalog_duplicate_version_handling(self):
        """Test handling of duplicate versions during registration"""
        # Simulate version collision scenario
        self.cursor_mock.fetchone.side_effect = [
            (1,),     # Count query - has existing entries
            ('0.1.0',), # Latest version query
            (1,),     # Check if incremented version exists (collision)
            (0,),     # Check if next incremented version exists (success)
        ]
        self.cursor_mock.fetchall.return_value = [('0.1.0',)]

        test_playbook = """
apiVersion: 0.1.0
kind: Playbook
name: collision_test
path: collision_test
steps:
  - name: test_step
    action: log
"""

        result = self.catalog_service.register_resource(test_playbook)

        # Should succeed with incremented version
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['resource_path'], 'collision_test')
        # Version should be incremented beyond the collision
        self.assertIn('resource_version', result)

    def test_event_service_error_handling(self):
        """Test error handling in event service"""
        # Simulate database error
        self.mock_connect.side_effect = Exception("Database error")

        event_data = {"event_type": "TEST", "message": "test"}

        with self.assertRaises(Exception):
            self.event_service.emit(event_data)

        # Reset the mock
        self.mock_connect.side_effect = None
        self.mock_connect.return_value = self.conn_mock


class TestServerIntegrationScenarios(unittest.TestCase):
    """Integration tests for complex scenarios"""

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

    def test_full_workflow_scenario(self):
        """Test a complete workflow: register -> fetch -> list"""
        # Setup mocks for registration
        self.cursor_mock.fetchone.side_effect = [(0,), (0,)]
        self.cursor_mock.fetchall.return_value = []

        # 1. Register a resource
        playbook_content = """
apiVersion: 0.1.0
kind: Playbook
name: workflow_test
path: workflow_test
description: Full workflow test
steps:
  - name: init
    action: log
    input:
      message: "Workflow started"
"""

        register_result = self.catalog_service.register_resource(playbook_content)
        self.assertEqual(register_result['status'], 'success')

        # 2. Fetch the registered resource - Create new cursor mock for fetch
        fetch_cursor_mock = Mock()
        mock_fetch_result = (
            'workflow_test', 'playbook', '0.1.1',
            playbook_content, '{}', '{}'
        )
        fetch_cursor_mock.fetchone.return_value = mock_fetch_result

        # Replace the cursor mock temporarily for fetch operation
        with patch.object(self.conn_mock, 'cursor') as mock_cursor_method:
            mock_cursor_method.return_value.__enter__.return_value = fetch_cursor_mock

            fetch_result = self.catalog_service.fetch_entry('workflow_test', '0.1.1')
            self.assertIsNotNone(fetch_result)
            self.assertEqual(fetch_result['resource_path'], 'workflow_test')

        # 3. List all entries - Create new cursor mock for list
        list_cursor_mock = Mock()
        mock_list_result = [
            ('workflow_test', 'playbook', '0.1.1', '{}', '2023-01-01')
        ]
        list_cursor_mock.fetchall.return_value = mock_list_result

        # Replace the cursor mock temporarily for list operation
        with patch.object(self.conn_mock, 'cursor') as mock_cursor_method:
            mock_cursor_method.return_value.__enter__.return_value = list_cursor_mock

            list_result = self.catalog_service.list_entries()
            self.assertEqual(len(list_result), 1)
            self.assertEqual(list_result[0]['resource_path'], 'workflow_test')


def main():
    logger.info("Starting NoETL server API tests")

    clean_database()

    server_process, server_log_path = start_server()
    if not server_process:
        logger.error("Failed to start server, aborting tests")
        return 1

    try:
        upload_success = test_upload_playbook()
        if not upload_success:
            logger.error("Playbook upload test failed")
            return 1

        list_success = test_list_playbooks()
        if not list_success:
            logger.error("Playbook listing test failed")
            return 1

        execute_success = test_execute_playbook()
        if not execute_success:
            logger.error("Playbook execution test failed")
            return 1

        async_execute_success = test_execute_playbook_async()
        if not async_execute_success:
            logger.error("Asynchronous playbook execution test failed")
            return 1

        event_query_success = test_get_event_by_query_param()
        if not event_query_success:
            logger.error("Event query parameter test failed")
            return 1

        path_segments_success = test_get_resource_with_path_segments()
        if not path_segments_success:
            logger.error("Resource path segments test failed")
            return 1

        logger.info("All tests passed successfully!")
        return 0

    finally:
        stop_server(server_process, server_log_path)
        clean_database()

if __name__ == "__main__":
    sys.exit(main())
