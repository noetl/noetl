"""
Snowflake authentication resolution module.

Handles authentication for Snowflake connections using:
- Unified authentication system (auth field)
- Legacy credential references (credential field)
- Direct connection parameters in task_with
"""

from typing import Dict, Tuple
from jinja2 import Environment

from noetl.core.logger import setup_logger
from noetl.core.auth import get_auth_data

logger = setup_logger(__name__, include_location=True)


def resolve_snowflake_auth(
    task_config: Dict,
    task_with: Dict,
    jinja_env: Environment,
    context: Dict
) -> Tuple[Dict, Dict]:
    """
    Resolve Snowflake authentication from task configuration.
    
    Authentication resolution follows this precedence:
    1. Unified auth system (task_config['auth'])
    2. Legacy credential reference (task_config['credential']) - deprecated
    3. Direct parameters in task_with
    
    Args:
        task_config: Task configuration dictionary
        task_with: Task 'with' parameters
        jinja_env: Jinja2 environment for template rendering
        context: Execution context
        
    Returns:
        Tuple of (updated_task_config, updated_task_with)
    """
    # Check for unified auth system
    auth_config = task_config.get('auth')
    if auth_config:
        logger.debug("Using unified auth system for Snowflake connection")
        auth_data = get_auth_data(auth_config, jinja_env, context)
        
        if auth_data:
            # Map auth data to Snowflake connection parameters
            task_with = {
                **task_with,
                'account': auth_data.get('account', task_with.get('account')),
                'user': auth_data.get('user', auth_data.get('username', task_with.get('user'))),
                'password': auth_data.get('password', task_with.get('password')),
                'warehouse': auth_data.get('warehouse', task_with.get('warehouse')),
                'database': auth_data.get('database', task_with.get('database')),
                'schema': auth_data.get('schema', task_with.get('schema')),
                'role': auth_data.get('role', task_with.get('role')),
            }
            logger.debug(f"Resolved auth for account: {task_with.get('account')}")
    
    # Check for legacy credential reference (deprecated)
    elif task_config.get('credential'):
        logger.warning(
            "The 'credential' field is deprecated. Please use 'auth' with the unified authentication system."
        )
        credential_key = task_config['credential']
        logger.debug(f"Fetching legacy credential: {credential_key}")
        
        # Fetch credential from database/cache
        from noetl.core.credential import get_credential_data
        credential_data = get_credential_data(credential_key)
        
        if credential_data:
            # Map credential data to connection parameters
            task_with = {
                **task_with,
                'account': credential_data.get('account', task_with.get('account')),
                'user': credential_data.get('user', credential_data.get('username', task_with.get('user'))),
                'password': credential_data.get('password', task_with.get('password')),
                'warehouse': credential_data.get('warehouse', task_with.get('warehouse')),
                'database': credential_data.get('database', task_with.get('database')),
                'schema': credential_data.get('schema', task_with.get('schema')),
                'role': credential_data.get('role', task_with.get('role')),
            }
    
    return task_config, task_with


def validate_and_render_connection_params(
    task_with: Dict,
    jinja_env: Environment,
    context: Dict
) -> Tuple[str, str, str, str, str, str, str, str]:
    """
    Validate and render Snowflake connection parameters.
    
    Args:
        task_with: Task 'with' parameters containing connection details
        jinja_env: Jinja2 environment for template rendering
        context: Execution context for rendering
        
    Returns:
        Tuple of (account, user, password, warehouse, database, schema, role, authenticator)
        
    Raises:
        ValueError: If required parameters are missing
    """
    # Required parameters
    account = task_with.get('account') or task_with.get('sf_account')
    user = task_with.get('user') or task_with.get('sf_user')
    password = task_with.get('password') or task_with.get('sf_password')
    
    if not account:
        raise ValueError("Snowflake 'account' parameter is required")
    if not user:
        raise ValueError("Snowflake 'user' parameter is required")
    if not password:
        raise ValueError("Snowflake 'password' parameter is required")
    
    # Optional parameters with defaults
    warehouse = task_with.get('warehouse') or task_with.get('sf_warehouse', 'COMPUTE_WH')
    database = task_with.get('database') or task_with.get('sf_database', '')
    schema = task_with.get('schema') or task_with.get('sf_schema', 'PUBLIC')
    role = task_with.get('role') or task_with.get('sf_role', '')
    authenticator = task_with.get('authenticator') or task_with.get('sf_authenticator', 'snowflake')
    
    # Render templates if they contain Jinja2 syntax
    if '{{' in str(account) or '{%' in str(account):
        account = jinja_env.from_string(str(account)).render(context)
    if '{{' in str(user) or '{%' in str(user):
        user = jinja_env.from_string(str(user)).render(context)
    if '{{' in str(password) or '{%' in str(password):
        password = jinja_env.from_string(str(password)).render(context)
    if '{{' in str(warehouse) or '{%' in str(warehouse):
        warehouse = jinja_env.from_string(str(warehouse)).render(context)
    if database and ('{{' in str(database) or '{%' in str(database)):
        database = jinja_env.from_string(str(database)).render(context)
    if schema and ('{{' in str(schema) or '{%' in str(schema)):
        schema = jinja_env.from_string(str(schema)).render(context)
    if role and ('{{' in str(role) or '{%' in str(role)):
        role = jinja_env.from_string(str(role)).render(context)
    
    logger.debug(f"Snowflake connection params validated: account={account}, warehouse={warehouse}, database={database}")
    
    return account, user, password, warehouse, database, schema, role, authenticator
