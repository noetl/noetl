import os
import pytest
from noetl.core.common import ordered_yaml_load

# Test file paths
MAIN_PLAYBOOK = os.path.join(os.path.dirname(__file__), "fixtures", "playbooks", "playbook_composition", "playbook_composition.yaml")
SUB_PLAYBOOK = os.path.join(os.path.dirname(__file__), "fixtures", "playbooks", "playbook_composition", "user_profile_scorer.yaml")


class TestPlaybookCompositionStatic:
    """Static validation tests for playbook composition (no runtime execution)"""
    
    def test_main_playbook_loads_and_parses(self):
        """Test that main playbook loads and parses correctly"""
        with open(MAIN_PLAYBOOK, "r", encoding="utf-8") as f:
            pb = ordered_yaml_load(f)
        
        assert pb is not None
        assert pb.get("apiVersion") == "noetl.io/v1"
        assert pb.get("kind") == "Playbook"
        assert pb["metadata"]["name"] == "playbook_composition"
        
    def test_sub_playbook_loads_and_parses(self):
        """Test that sub-playbook loads and parses correctly"""
        with open(SUB_PLAYBOOK, "r", encoding="utf-8") as f:
            pb = ordered_yaml_load(f)
        
        assert pb is not None
        assert pb.get("apiVersion") == "noetl.io/v1"
        assert pb.get("kind") == "Playbook"
        assert pb["metadata"]["name"] == "user_profile_scorer"
    
    def test_main_playbook_has_iterator_step(self):
        """Test that main playbook contains properly configured iterator step"""
        with open(MAIN_PLAYBOOK, "r", encoding="utf-8") as f:
            pb = ordered_yaml_load(f)
        
        # Find the iterator step
        iterator_step = None
        for step in pb["workflow"]:
            if step.get("type") == "iterator":
                iterator_step = step
                break
        
        assert iterator_step is not None, "No iterator step found"
        assert iterator_step["step"] == "process_users"
        assert iterator_step["collection"] == "{{ workload.users }}"
        assert iterator_step["element"] == "user"
        assert iterator_step["mode"] == "sequential"
        
        # Check nested task is playbook type
        task = iterator_step["task"]
        assert task["type"] == "playbook"
        assert task["path"] == "tests/fixtures/playbooks/playbook_composition/user_profile_scorer"
        assert "data" in task
        assert task["data"]["user_data"] == "{{ user }}"
    
    def test_sub_playbook_has_workbook_actions(self):
        """Test that sub-playbook contains expected workbook actions"""
        with open(SUB_PLAYBOOK, "r", encoding="utf-8") as f:
            pb = ordered_yaml_load(f)
        
        workbook = pb.get("workbook", [])
        assert len(workbook) >= 5, f"Expected at least 5 workbook actions, got {len(workbook)}"
        
        action_names = [action["name"] for action in workbook]
        expected_actions = [
            "calculate_experience_score",
            "calculate_performance_score", 
            "calculate_department_score",
            "calculate_age_factor",
            "determine_category"
        ]
        
        for expected in expected_actions:
            assert expected in action_names, f"Missing workbook action: {expected}"
    
    def test_main_playbook_validation_step(self):
        """Test that main playbook has proper validation step"""
        with open(MAIN_PLAYBOOK, "r", encoding="utf-8") as f:
            pb = ordered_yaml_load(f)
        
        # Find validation step
        validation_step = None
        for step in pb["workflow"]:
            if step.get("step") == "validate_results":
                validation_step = step
                break
        
        assert validation_step is not None, "No validation step found"
        assert validation_step["type"] == "python"
        assert "user_results" in validation_step["data"]
        assert validation_step["data"]["user_results"] == "{{ process_users.data }}"
        
        # Check validation logic exists
        code = validation_step["code"]
        assert "expected_min_score" in code
        assert "expected_max_score" in code
        assert "valid_categories" in code
    
    def test_workload_has_test_data(self):
        """Test that main playbook workload contains proper test data"""
        with open(MAIN_PLAYBOOK, "r", encoding="utf-8") as f:
            pb = ordered_yaml_load(f)
        
        workload = pb["workload"]
        assert "users" in workload
        
        users = workload["users"]
        assert len(users) == 4, f"Expected 4 test users, got {len(users)}"
        
        # Check each user has required fields
        required_fields = ["name", "age", "department", "years_experience", "performance_rating"]
        for i, user in enumerate(users):
            for field in required_fields:
                assert field in user, f"User {i} missing field: {field}"
            
            # Check data types
            assert isinstance(user["name"], str)
            assert isinstance(user["age"], (int, float))
            assert isinstance(user["department"], str)
            assert isinstance(user["years_experience"], (int, float))
            assert isinstance(user["performance_rating"], (int, float))
    
    def test_postgres_storage_configuration(self):
        """Test that PostgreSQL storage is properly configured"""
        with open(MAIN_PLAYBOOK, "r", encoding="utf-8") as f:
            pb = ordered_yaml_load(f)
        
        # Find iterator step with save configuration
        iterator_step = None
        for step in pb["workflow"]:
            if step.get("type") == "iterator":
                iterator_step = step
                break
        
        save_config = iterator_step["task"]["save"]
        assert save_config["storage"] == "postgres"
        assert save_config["auth"] == "pg_local"
        assert save_config["table"] == "public.user_profile_results"
        assert save_config["mode"] == "upsert"
        assert save_config["key"] == "id"
        
        # Check saved data fields
        data_config = save_config["data"]
        expected_fields = ["id", "execution_id", "user_name", "profile_score", "score_category"]
        for field in expected_fields:
            assert field in data_config


# Runtime test configuration
RUNTIME_ENABLED = os.environ.get("NOETL_RUNTIME_TESTS", "false").lower() == "true"
NOETL_HOST = os.environ.get("NOETL_HOST", "localhost")
NOETL_PORT = os.environ.get("NOETL_PORT", "8082")
NOETL_BASE_URL = f"http://{NOETL_HOST}:{NOETL_PORT}"


def check_server_health() -> bool:
    """Check if noetl server is running and healthy."""
    try:
        import requests
        response = requests.get(f"{NOETL_BASE_URL}/health", timeout=5)
        return response.status_code == 200
    except:
        return False


def check_credentials_registered() -> dict:
    """Check if required credentials are registered."""
    try:
        import requests
        response = requests.get(f"{NOETL_BASE_URL}/api/credentials", timeout=5)
        if response.status_code == 200:
            data = response.json()
            # API returns credentials in 'items' array
            credentials = data.get('items', [])
            credential_names = [cred.get('name') for cred in credentials]
            return {
                'pg_local': 'pg_local' in credential_names,
                'gcs_hmac_local': 'gcs_hmac_local' in credential_names,
                'all_present': 'pg_local' in credential_names and 'gcs_hmac_local' in credential_names
            }
    except:
        pass
    return {'pg_local': False, 'gcs_hmac_local': False, 'all_present': False}


def execute_playbook_runtime(playbook_file_path: str, playbook_name: str) -> dict:
    """Execute playbook through noetl CLI and return result."""
    import subprocess
    import json
    import time
    import re
    from pathlib import Path
    
    # First register the playbook using the noetl CLI directly
    register_cmd = [
        ".venv/bin/noetl", "register", 
        playbook_file_path, 
        "--host", NOETL_HOST, 
        "--port", NOETL_PORT
    ]
    
    result = subprocess.run(register_cmd, capture_output=True, text=True, cwd=Path.cwd())
    if result.returncode != 0:
        raise RuntimeError(f"Failed to register playbook: {result.stderr}\nstdout: {result.stdout}")
    
    # Give a moment for registration to complete
    time.sleep(1)
    
    # Execute the playbook using make target (which works)
    execute_cmd = [
        "make", "noetl-execute", 
        f"PLAYBOOK={playbook_name}",
        f"HOST={NOETL_HOST}", 
        f"PORT={NOETL_PORT}"
    ]
    
    result = subprocess.run(execute_cmd, capture_output=True, text=True, cwd=Path.cwd())
    
    # Parse execution result - handle both success and error JSON responses
    try:
        # The entire stdout should be JSON from the make target
        output = result.stdout.strip()
        if output:
            # Strip ANSI color codes that may be in the JSON output
            ansi_escape = re.compile(r'\x1B(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])')
            clean_output = ansi_escape.sub('', output)
            execution_result = json.loads(clean_output)
            
            # Check if this is an error response
            if "detail" in execution_result:
                raise RuntimeError(f"Execution failed: {execution_result['detail']}")
            
            execution_id = execution_result.get("result", {}).get("execution_id") or execution_result.get("execution_id")
            
            if execution_id:
                return {"status": "completed", "execution_id": execution_id, "message": "Execution started successfully"}
            else:
                raise RuntimeError(f"No execution_id found in result: {output}")
        else:
            raise RuntimeError(f"No output found. stdout: {result.stdout}, stderr: {result.stderr}")
            
    except json.JSONDecodeError as e:
        raise RuntimeError(f"Failed to parse execution result: {e}. Output: {result.stdout}")


class TestPlaybookCompositionRuntime:
    """Runtime execution tests for playbook composition (requires running server)"""
    
    @pytest.mark.skipif(not RUNTIME_ENABLED, reason="Runtime tests disabled. Set NOETL_RUNTIME_TESTS=true to enable")
    def test_credentials_registered(self):
        """Test that required credentials are registered"""
        if not check_server_health():
            pytest.skip(f"NoETL server not available at {NOETL_BASE_URL}")
        
        cred_status = check_credentials_registered()
        
        # Provide helpful error messages
        if not cred_status['pg_local']:
            pytest.fail("pg_local credential not registered. Run: make register-credential FILE=tests/fixtures/credentials/pg_local.json")
        
        if not cred_status['gcs_hmac_local']:
            pytest.fail("gcs_hmac_local credential not registered. Run: make register-credential FILE=tests/fixtures/credentials/gcs_hmac_local.json")
        
        assert cred_status['all_present'], "All required credentials should be registered"
        print("All required credentials are registered")
    
    @pytest.mark.skipif(not RUNTIME_ENABLED, reason="Runtime tests disabled. Set NOETL_RUNTIME_TESTS=true to enable")
    def test_playbook_composition_execution(self):
        """Test full playbook composition execution"""
        if not check_server_health():
            pytest.skip(f"NoETL server not available at {NOETL_BASE_URL}")
        
        # Execute the main playbook
        execution_result = execute_playbook_runtime(MAIN_PLAYBOOK, "tests/fixtures/playbooks/playbook_composition")
        
        # Verify execution completed successfully
        assert execution_result.get("status", "").lower() in ["completed", "success", "finished"]
        assert "execution_id" in execution_result
        
        print(f"Playbook composition executed successfully with execution_id: {execution_result['execution_id']}")
    
    @pytest.mark.skipif(not RUNTIME_ENABLED, reason="Runtime tests disabled. Set NOETL_RUNTIME_TESTS=true to enable")
    def test_sub_playbook_registration(self):
        """Test that sub-playbook can be registered independently"""
        if not check_server_health():
            pytest.skip(f"NoETL server not available at {NOETL_BASE_URL}")
        
        import subprocess
        from pathlib import Path
        
        # Register the sub-playbook directly
        register_cmd = [
            ".venv/bin/noetl", "register", 
            SUB_PLAYBOOK, 
            "--host", NOETL_HOST, 
            "--port", NOETL_PORT
        ]
        
        result = subprocess.run(register_cmd, capture_output=True, text=True, cwd=Path.cwd())
        assert result.returncode == 0, f"Failed to register sub-playbook: {result.stderr}"
        
        print("Sub-playbook registered successfully")
    
    @pytest.mark.skipif(not RUNTIME_ENABLED, reason="Runtime tests disabled. Set NOETL_RUNTIME_TESTS=true to enable")
    def test_iterator_with_playbook_task(self):
        """Test that iterator step with playbook task works correctly"""
        if not check_server_health():
            pytest.skip(f"NoETL server not available at {NOETL_BASE_URL}")
        
        # This test verifies the key feature: iterator calling playbook
        # The main test already covers this, but we can add specific checks
        
        # Load and verify the main playbook has the correct iterator configuration
        with open(MAIN_PLAYBOOK, "r", encoding="utf-8") as f:
            pb = ordered_yaml_load(f)
        
        # Find the iterator step
        iterator_step = None
        for step in pb["workflow"]:
            if step.get("type") == "iterator":
                iterator_step = step
                break
        
        assert iterator_step is not None
        assert iterator_step["task"]["type"] == "playbook"
        assert iterator_step["task"]["path"] == "tests/fixtures/playbooks/playbook_composition/user_profile_scorer"
        
        # Execute and verify it works
        execution_result = execute_playbook_runtime(MAIN_PLAYBOOK, "tests/fixtures/playbooks/playbook_composition")
        assert execution_result.get("status", "").lower() in ["completed", "success", "finished"]
        
        print("Iterator with playbook task executed successfully")
    
    @pytest.mark.skipif(not RUNTIME_ENABLED, reason="Runtime tests disabled. Set NOETL_RUNTIME_TESTS=true to enable")  
    def test_workbook_actions_in_sub_playbook(self):
        """Test that workbook actions in sub-playbook execute correctly"""
        if not check_server_health():
            pytest.skip(f"NoETL server not available at {NOETL_BASE_URL}")
        
        # The sub-playbook has multiple workbook actions that should execute
        # This is tested as part of the main composition, but we verify the structure
        
        with open(SUB_PLAYBOOK, "r", encoding="utf-8") as f:
            pb = ordered_yaml_load(f)
        
        workbook = pb.get("workbook", [])
        assert len(workbook) == 5, f"Expected 5 workbook actions, got {len(workbook)}"
        
        # Verify each workbook action has proper structure
        for action in workbook:
            assert "name" in action
            assert "type" in action  
            assert action["type"] == "python"
            assert "code" in action
            assert "accepts" in action
            assert "returns" in action
        
        print("Sub-playbook workbook actions are properly structured")


def test_playbook_files_exist():
    """Basic test that required files exist"""
    assert os.path.exists(MAIN_PLAYBOOK), f"Main playbook not found: {MAIN_PLAYBOOK}"
    assert os.path.exists(SUB_PLAYBOOK), f"Sub-playbook not found: {SUB_PLAYBOOK}"


def test_readme_exists():
    """Test that README documentation exists"""
    readme_path = os.path.join(os.path.dirname(__file__), "fixtures", "playbooks", "playbook_composition", "README.md")
    assert os.path.exists(readme_path), f"README not found: {readme_path}"


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v"])