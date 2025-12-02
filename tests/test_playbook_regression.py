"""
NoETL Playbook Regression Test Suite
====================================

Comprehensive test framework that executes all playbooks and validates outputs
against expected results to catch regressions when adding new features.

Usage:
    pytest tests/test_playbook_regression.py -v
    pytest tests/test_playbook_regression.py -v -k "hello_world"
    pytest tests/test_playbook_regression.py -v --category=basic
    pytest tests/test_playbook_regression.py -v --update-expected
"""

import asyncio
import json
import os
import re
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
import pytest
import yaml


# === Configuration ===
PROJECT_ROOT = Path(__file__).parent.parent
FIXTURES_DIR = PROJECT_ROOT / "tests" / "fixtures"
EXPECTED_RESULTS_DIR = FIXTURES_DIR / "expected_results"
TEST_CONFIG_FILE = FIXTURES_DIR / "playbook_test_config.yaml"
NOETL_HOST = os.getenv("NOETL_HOST", "localhost")
NOETL_PORT = int(os.getenv("NOETL_PORT", "8082"))
NOETL_BASE_URL = f"http://{NOETL_HOST}:{NOETL_PORT}"


# === Test Configuration Loader ===
class PlaybookTestConfig:
    """Loads and manages playbook test configuration."""
    
    def __init__(self, config_file: Path):
        with open(config_file) as f:
            self.config = yaml.safe_load(f)
        
        self.global_config = self.config.get("config", {})
        self.playbooks = self.config.get("playbooks", [])
        self.setup_tasks = self.config.get("setup_tasks", {})
    
    def get_enabled_playbooks(self, category: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get list of enabled playbooks, optionally filtered by category."""
        playbooks = [p for p in self.playbooks if p.get("enabled", True)]
        
        if category:
            playbooks = [p for p in playbooks if p.get("category") == category]
        
        return playbooks
    
    def get_playbook_config(self, name: str) -> Optional[Dict[str, Any]]:
        """Get configuration for a specific playbook."""
        for playbook in self.playbooks:
            if playbook.get("name") == name:
                return playbook
        return None
    
    def get_required_credentials(self) -> List[str]:
        """Get list of all required credentials."""
        return self.global_config.get("required_credentials", [])


# === NoETL API Client ===
class NoETLClient:
    """Client for interacting with NoETL API."""
    
    def __init__(self, base_url: str):
        self.base_url = base_url
        self.client = httpx.AsyncClient(timeout=300.0)
    
    async def health_check(self) -> bool:
        """Check if NoETL server is healthy."""
        try:
            response = await self.client.get(f"{self.base_url}/api/health")
            return response.status_code == 200
        except Exception:
            return False
    
    async def register_playbook(self, playbook_path: str) -> Dict[str, Any]:
        """Register a playbook in the catalog."""
        response = await self.client.post(
            f"{self.base_url}/api/catalog/register",
            json={"path": playbook_path}
        )
        response.raise_for_status()
        return response.json()
    
    async def execute_playbook(
        self,
        playbook_path: str,
        payload: Optional[Dict[str, Any]] = None,
        merge: bool = True
    ) -> Dict[str, Any]:
        """Execute a playbook and return execution result."""
        request_data = {
            "path": playbook_path,
            "merge": merge
        }
        
        if payload:
            request_data["payload"] = payload
        
        response = await self.client.post(
            f"{self.base_url}/api/execution/execute",
            json=request_data
        )
        response.raise_for_status()
        return response.json()
    
    async def get_execution_status(self, execution_id: int) -> Dict[str, Any]:
        """Get execution status and events."""
        response = await self.client.get(
            f"{self.base_url}/api/execution/{execution_id}/status"
        )
        response.raise_for_status()
        return response.json()
    
    async def get_execution_events(self, execution_id: int) -> List[Dict[str, Any]]:
        """Get all events for an execution."""
        response = await self.client.get(
            f"{self.base_url}/api/execution/{execution_id}/events"
        )
        response.raise_for_status()
        return response.json()
    
    async def wait_for_completion(
        self,
        execution_id: int,
        timeout: int = 300,
        poll_interval: float = 2.0
    ) -> Dict[str, Any]:
        """Wait for execution to complete and return final status."""
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            status = await self.get_execution_status(execution_id)
            
            execution_status = status.get("status")
            if execution_status in ["completed", "failed", "error"]:
                return status
            
            await asyncio.sleep(poll_interval)
        
        raise TimeoutError(f"Execution {execution_id} did not complete within {timeout}s")
    
    async def close(self):
        """Close the HTTP client."""
        await self.client.aclose()


# === Test Result Validator ===
class PlaybookValidator:
    """Validates playbook execution results against expected outputs."""
    
    @staticmethod
    def normalize_result(result: Any) -> Any:
        """Normalize result for comparison (remove timestamps, execution IDs, etc.)."""
        if isinstance(result, dict):
            normalized = {}
            for key, value in result.items():
                # Skip dynamic fields
                if key in ["execution_id", "timestamp", "created_at", "updated_at"]:
                    continue
                normalized[key] = PlaybookValidator.normalize_result(value)
            return normalized
        
        elif isinstance(result, list):
            return [PlaybookValidator.normalize_result(item) for item in result]
        
        else:
            return result
    
    @staticmethod
    def validate_execution_status(
        actual_status: str,
        expected_status: str
    ) -> tuple[bool, str]:
        """Validate execution status matches expected."""
        if actual_status == expected_status:
            return True, ""
        return False, f"Expected status '{expected_status}', got '{actual_status}'"
    
    @staticmethod
    def validate_step_count(
        events: List[Dict[str, Any]],
        min_steps: int
    ) -> tuple[bool, str]:
        """Validate minimum number of steps were executed."""
        step_events = [e for e in events if e.get("event_type") == "action_completed"]
        actual_count = len(step_events)
        
        if actual_count >= min_steps:
            return True, ""
        return False, f"Expected at least {min_steps} steps, got {actual_count}"
    
    @staticmethod
    def validate_required_steps(
        events: List[Dict[str, Any]],
        required_steps: List[str]
    ) -> tuple[bool, str]:
        """Validate all required steps were executed."""
        executed_steps = {
            e.get("step_name") for e in events
            if e.get("event_type") == "action_completed"
        }
        
        missing_steps = set(required_steps) - executed_steps
        if not missing_steps:
            return True, ""
        return False, f"Missing required steps: {missing_steps}"
    
    @staticmethod
    def validate_error_pattern(
        events: List[Dict[str, Any]],
        error_pattern: str
    ) -> tuple[bool, str]:
        """Validate error message matches expected pattern."""
        error_events = [e for e in events if e.get("event_type") == "action_failed"]
        
        if not error_events:
            return False, "Expected error but execution succeeded"
        
        pattern = re.compile(error_pattern, re.IGNORECASE)
        for event in error_events:
            error_msg = event.get("error_message", "")
            if pattern.search(error_msg):
                return True, ""
        
        return False, f"No error matched pattern '{error_pattern}'"


# === Test Fixtures ===
@pytest.fixture(scope="session")
def test_config():
    """Load test configuration."""
    return PlaybookTestConfig(TEST_CONFIG_FILE)


@pytest.fixture(scope="session")
async def noetl_client():
    """Create NoETL API client."""
    client = NoETLClient(NOETL_BASE_URL)
    
    # Verify server is running
    if not await client.health_check():
        pytest.fail(f"NoETL server not available at {NOETL_BASE_URL}")
    
    yield client
    
    await client.close()


@pytest.fixture(scope="session", autouse=True)
async def setup_environment(test_config):
    """Setup test environment - register credentials, create tables, etc."""
    print("\n=== Setting up test environment ===")
    
    # For K8s environment, credentials should already be registered
    # via `task register-test-credentials`
    
    # Run setup tasks (like create_tables) once
    client = NoETLClient(NOETL_BASE_URL)
    
    for task_name, task_config in test_config.setup_tasks.items():
        if not task_config.get("run_once", True):
            continue
        
        print(f"Running setup task: {task_name}")
        playbook_path = task_config["playbook"]
        
        # Register and execute setup playbook
        await client.register_playbook(playbook_path)
        
        payload = {}
        if "pg_k8s" in task_config.get("credentials", []):
            payload["pg_auth"] = "pg_k8s"
        
        result = await client.execute_playbook(playbook_path, payload)
        execution_id = result.get("execution_id")
        
        if execution_id:
            status = await client.wait_for_completion(execution_id, timeout=60)
            if status.get("status") != "completed":
                pytest.fail(f"Setup task {task_name} failed: {status}")
    
    await client.close()
    
    print("=== Test environment ready ===\n")


# === Pytest Hooks for Custom Options ===
def pytest_addoption(parser):
    """Add custom pytest command-line options."""
    parser.addoption(
        "--category",
        action="store",
        default=None,
        help="Filter tests by category (basic, data_transfer, control_flow, etc.)"
    )
    parser.addoption(
        "--update-expected",
        action="store_true",
        default=False,
        help="Update expected result files with actual results"
    )


def pytest_generate_tests(metafunc):
    """Generate test cases from configuration file."""
    if "playbook_config" in metafunc.fixturenames:
        config = PlaybookTestConfig(TEST_CONFIG_FILE)
        category = metafunc.config.getoption("--category")
        
        playbooks = config.get_enabled_playbooks(category)
        
        # Generate test IDs
        test_ids = [p["name"] for p in playbooks]
        
        metafunc.parametrize("playbook_config", playbooks, ids=test_ids)


# === Main Test Function ===
@pytest.mark.asyncio
async def test_playbook_execution(
    playbook_config: Dict[str, Any],
    noetl_client: NoETLClient,
    request
):
    """
    Execute a playbook and validate results against expected output.
    
    This test:
    1. Registers the playbook
    2. Executes it with required credentials
    3. Waits for completion
    4. Validates execution status and events
    5. Compares results with expected output (if exists)
    """
    playbook_name = playbook_config["name"]
    playbook_path = playbook_config["path"]
    validation = playbook_config.get("validation", {})
    
    print(f"\n=== Testing playbook: {playbook_name} ===")
    
    # Step 1: Register playbook
    await noetl_client.register_playbook(playbook_path)
    
    # Step 2: Prepare execution payload with credentials
    payload = {}
    required_creds = playbook_config.get("requires_credentials", [])
    
    if "pg_k8s" in required_creds:
        payload["pg_auth"] = "pg_k8s"
    if "gcs_hmac_local" in required_creds:
        payload["gcs_auth"] = "gcs_hmac_local"
    
    # Step 3: Execute playbook
    exec_result = await noetl_client.execute_playbook(playbook_path, payload)
    execution_id = exec_result.get("execution_id")
    
    assert execution_id, f"Failed to get execution_id for {playbook_name}"
    print(f"Execution ID: {execution_id}")
    
    # Step 4: Wait for completion
    timeout = playbook_config.get("timeout", 300)
    final_status = await noetl_client.wait_for_completion(execution_id, timeout)
    
    # Step 5: Get execution events
    events = await noetl_client.get_execution_events(execution_id)
    
    # Step 6: Validate execution status
    expected_status = validation.get("execution_status", "completed")
    actual_status = final_status.get("status")
    
    is_valid, error_msg = PlaybookValidator.validate_execution_status(
        actual_status, expected_status
    )
    assert is_valid, error_msg
    
    # Step 7: Additional validations
    if "min_steps" in validation:
        is_valid, error_msg = PlaybookValidator.validate_step_count(
            events, validation["min_steps"]
        )
        assert is_valid, error_msg
    
    if "required_steps" in validation:
        is_valid, error_msg = PlaybookValidator.validate_required_steps(
            events, validation["required_steps"]
        )
        assert is_valid, error_msg
    
    if validation.get("expect_error") and "error_pattern" in validation:
        is_valid, error_msg = PlaybookValidator.validate_error_pattern(
            events, validation["error_pattern"]
        )
        assert is_valid, error_msg
    
    # Step 8: Compare with expected results (if file exists)
    expected_file = EXPECTED_RESULTS_DIR / playbook_config.get("expected_result_file", f"{playbook_name}.json")
    
    actual_result = {
        "execution_id": execution_id,
        "status": actual_status,
        "events": PlaybookValidator.normalize_result(events),
        "final_status": PlaybookValidator.normalize_result(final_status)
    }
    
    # Update expected results if flag is set
    if request.config.getoption("--update-expected"):
        expected_file.parent.mkdir(parents=True, exist_ok=True)
        with open(expected_file, "w") as f:
            json.dump(actual_result, f, indent=2)
        print(f"Updated expected results: {expected_file}")
    
    # Compare with expected if file exists
    elif expected_file.exists():
        with open(expected_file) as f:
            expected_result = json.load(f)
        
        # Normalize both for comparison (remove execution_id, timestamps)
        normalized_actual = PlaybookValidator.normalize_result(actual_result)
        normalized_expected = PlaybookValidator.normalize_result(expected_result)
        
        # Compare status
        assert normalized_actual["status"] == normalized_expected["status"], \
            f"Status mismatch: expected {normalized_expected['status']}, got {normalized_actual['status']}"
        
        # Compare event count
        actual_event_count = len(normalized_actual["events"])
        expected_event_count = len(normalized_expected["events"])
        assert actual_event_count == expected_event_count, \
            f"Event count mismatch: expected {expected_event_count}, got {actual_event_count}"
        
        print(f"✓ Results match expected output ({expected_file.name})")
    
    else:
        print(f"⚠ No expected result file found: {expected_file}")
        print("  Run with --update-expected to create baseline")
    
    print(f"✓ Playbook {playbook_name} test passed")


# === Utility Functions for Manual Testing ===
async def run_single_playbook_test(playbook_name: str):
    """Run a single playbook test (for debugging)."""
    config = PlaybookTestConfig(TEST_CONFIG_FILE)
    client = NoETLClient(NOETL_BASE_URL)
    
    playbook_config = config.get_playbook_config(playbook_name)
    if not playbook_config:
        print(f"Playbook '{playbook_name}' not found in configuration")
        return
    
    try:
        # Mock request object for update-expected flag
        class MockRequest:
            class MockConfig:
                @staticmethod
                def getoption(name):
                    return False
            config = MockConfig()
        
        await test_playbook_execution(playbook_config, client, MockRequest())
    finally:
        await client.close()


if __name__ == "__main__":
    # Example: Run single playbook test
    import sys
    
    if len(sys.argv) > 1:
        playbook_name = sys.argv[1]
        asyncio.run(run_single_playbook_test(playbook_name))
    else:
        print("Usage: python test_playbook_regression.py <playbook_name>")
        print("Or use pytest: pytest tests/test_playbook_regression.py -v")
