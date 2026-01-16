"""
Snowflake authentication and connection parameter resolution.

This module handles:
- Unified auth system resolution
- Legacy credential fallback
- Connection parameter mapping and validation
- Jinja2 template rendering
"""

from typing import Dict, Tuple, Optional
from pydantic import BaseModel, Field
from jinja2 import Environment
from noetl.core.logger import setup_logger
from noetl.core.dsl.render import render_template
from noetl.worker.auth_resolver import resolve_auth
from noetl.worker.auth_compatibility import transform_credentials_to_auth, validate_auth_transition
from noetl.worker.secrets import fetch_credential_by_key

logger = setup_logger(__name__, include_location=True)


class SnowflakeFieldMapping(BaseModel):
    """
    Pydantic model for Snowflake field name mapping configuration.
    
    Maps alternative field names (source) to canonical field names (target).
    Supports both direct field names and prefixed alternatives (e.g., sf_*).
    """
    # Disable protected namespace warning for 'schema' field
    class Config:
        # Allow field names that shadow parent attributes
        pass
    
    # Connection parameters
    account: str = Field(default="account", description="Snowflake account identifier")
    user: str = Field(default="user", description="Username for authentication")
    password: str = Field(default="password", description="Password for authentication")
    private_key: str = Field(default="private_key", description="RSA private key for key-pair auth")
    private_key_passphrase: str = Field(default="private_key_passphrase", description="Private key passphrase")
    
    # Session parameters
    warehouse: str = Field(default="warehouse", description="Snowflake warehouse")
    database: str = Field(default="database", description="Database name")
    schema_name: str = Field(default="schema", description="Schema name")
    role: str = Field(default="role", description="User role")
    authenticator: str = Field(default="authenticator", description="Authentication method")
    
    # Alternative mappings (sf_ prefix)
    sf_account: str = Field(default="account", description="Alternative: sf_account -> account")
    sf_user: str = Field(default="user", description="Alternative: sf_user -> user")
    sf_password: str = Field(default="password", description="Alternative: sf_password -> password")
    sf_private_key: str = Field(default="private_key", description="Alternative: sf_private_key -> private_key")
    sf_private_key_passphrase: str = Field(default="private_key_passphrase", description="Alternative: sf_private_key_passphrase -> private_key_passphrase")
    sf_warehouse: str = Field(default="warehouse", description="Alternative: sf_warehouse -> warehouse")
    sf_database: str = Field(default="database", description="Alternative: sf_database -> database")
    sf_schema: str = Field(default="schema", description="Alternative: sf_schema -> schema")
    sf_role: str = Field(default="role", description="Alternative: sf_role -> role")
    sf_authenticator: str = Field(default="authenticator", description="Alternative: sf_authenticator -> authenticator")
    
    # Common alternatives
    username: str = Field(default="user", description="Alternative: username -> user")


# Global field mapping configuration
# The model_dump() method returns all field mappings as a dictionary
SNOWFLAKE_FIELD_MAPPING = SnowflakeFieldMapping().model_dump()


def resolve_snowflake_auth(
    task_config: Dict,
    task_with: Dict,
    jinja_env: Environment,
    context: Dict
) -> Tuple[Dict, Dict]:
    """
    Resolve Snowflake authentication and apply backwards compatibility transformations.
    
    Args:
        task_config: The task configuration
        task_with: The rendered 'with' parameters dictionary
        jinja_env: The Jinja2 environment for template rendering
        context: The context for rendering templates
        
    Returns:
        Tuple of (updated task_config, updated task_with)
    """
    # Apply backwards compatibility transformation for deprecated 'credentials' field
    validate_auth_transition(task_config, task_with)
    task_config, task_with = transform_credentials_to_auth(task_config, task_with)

    # Resolve unified auth system
    snowflake_auth = None
    try:
        auth_config = task_config.get('auth') or task_with.get('auth')
        if auth_config:
            logger.debug("SNOWFLAKE: Using unified auth system")
            mode, resolved_items = resolve_auth(auth_config, jinja_env, context)
            
            # For Snowflake, we expect single auth mode or use the first resolved item
            resolved_auth = None
            if resolved_items:
                resolved_auth = list(resolved_items.values())[0]
            
            if resolved_auth:
                logger.debug(f"SNOWFLAKE: Resolved auth service: '{resolved_auth.service}', payload keys: {list(resolved_auth.payload.keys()) if resolved_auth.payload else 'None'}")
                
                if resolved_auth.service == 'snowflake':
                    snowflake_auth = resolved_auth.payload
                    logger.debug(f"SNOWFLAKE: Using snowflake auth with fields: {list(snowflake_auth.keys())}")
                    
                    # Apply resolved auth to task_with using Pydantic model_dump()
                    for src_field, target_field in SNOWFLAKE_FIELD_MAPPING.items():
                        if src_field in snowflake_auth:
                            # Only set if not already explicitly set in task_with
                            if target_field not in task_with:
                                task_with[target_field] = snowflake_auth[src_field]
                                logger.debug(f"SNOWFLAKE: Mapped auth field '{src_field}' -> '{target_field}'")
                else:
                    logger.warning(f"SNOWFLAKE: Resolved auth service '{resolved_auth.service}' does not match expected 'snowflake'")
    
    except Exception as e:
        logger.error(f"SNOWFLAKE: Error resolving unified auth: {e}")
        # Continue with legacy credential fallback

    # Legacy credential fallback (deprecated)
    if not snowflake_auth:
        credential_key = task_config.get('credential') or task_with.get('credential')
        if credential_key:
            logger.warning(
                f"SNOWFLAKE: Using deprecated 'credential' field. "
                f"Please migrate to 'auth' field with unified authentication system."
            )
            try:
                credential_data = fetch_credential_by_key(credential_key)
                if credential_data:
                    # Use Pydantic model_dump() for legacy field mapping
                    for src_field, target_field in SNOWFLAKE_FIELD_MAPPING.items():
                        if src_field in credential_data:
                            if target_field not in task_with:
                                task_with[target_field] = credential_data[src_field]
                                logger.debug(f"SNOWFLAKE: Mapped legacy credential field '{src_field}' -> '{target_field}'")
                                
            except Exception as e:
                logger.error(f"SNOWFLAKE: Error fetching legacy credential '{credential_key}': {e}")
    
    return task_config, task_with


def validate_and_render_connection_params(
    task_with: Dict,
    jinja_env: Environment,
    context: Dict
) -> Tuple[str, str, Optional[str], Optional[str], Optional[str], str, str, str, str, str]:
    """
    Validate and render Snowflake connection parameters.
    
    Supports both password-based and key-pair authentication.
    
    Args:
        task_with: Task 'with' parameters containing connection details
        jinja_env: Jinja2 environment for template rendering
        context: Execution context for rendering
        
    Returns:
        Tuple of (account, user, password, private_key, private_key_passphrase, 
                  warehouse, database, schema, role, authenticator)
        
    Raises:
        ValueError: If required parameters are missing or invalid auth combination
    """
    # Required parameters
    account = task_with.get('account') or task_with.get('sf_account')
    user = task_with.get('user') or task_with.get('sf_user')
    
    # Authentication parameters (password OR private_key)
    password = task_with.get('password') or task_with.get('sf_password')
    private_key = task_with.get('private_key') or task_with.get('sf_private_key')
    private_key_passphrase = task_with.get('private_key_passphrase') or task_with.get('sf_private_key_passphrase')
    
    if not account:
        raise ValueError("Snowflake 'account' parameter is required")
    if not user:
        raise ValueError("Snowflake 'user' parameter is required")
    
    # Validate authentication method
    if not password and not private_key:
        raise ValueError(
            "Snowflake authentication requires either 'password' or 'private_key'. "
            "For key-pair auth, provide 'private_key' (and optionally 'private_key_passphrase'). "
            "For password auth, provide 'password'."
        )
    
    if password and private_key:
        logger.warning("Both 'password' and 'private_key' provided. Using key-pair authentication (private_key).")
        password = None  # Prefer key-pair auth
    
    # Optional parameters with defaults
    warehouse = task_with.get('warehouse') or task_with.get('sf_warehouse', 'COMPUTE_WH')
    database = task_with.get('database') or task_with.get('sf_database', '')
    schema = task_with.get('schema') or task_with.get('sf_schema', 'PUBLIC')
    role = task_with.get('role') or task_with.get('sf_role', '')
    authenticator = task_with.get('authenticator') or task_with.get('sf_authenticator', 'snowflake')
    
    # Render templates if they contain Jinja2 syntax
    if '{{' in str(account) or '{%' in str(account):
        account = render_template(str(account), jinja_env, context)
    if '{{' in str(user) or '{%' in str(user):
        user = render_template(str(user), jinja_env, context)
    if password and ('{{' in str(password) or '{%' in str(password)):
        password = render_template(str(password), jinja_env, context)
    if private_key and ('{{' in str(private_key) or '{%' in str(private_key)):
        private_key = render_template(str(private_key), jinja_env, context)
    if private_key_passphrase and ('{{' in str(private_key_passphrase) or '{%' in str(private_key_passphrase)):
        private_key_passphrase = render_template(str(private_key_passphrase), jinja_env, context)
    if '{{' in str(warehouse) or '{%' in str(warehouse):
        warehouse = render_template(str(warehouse), jinja_env, context)
    if database and ('{{' in str(database) or '{%' in str(database)):
        database = render_template(str(database), jinja_env, context)
    if schema and ('{{' in str(schema) or '{%' in str(schema)):
        schema = render_template(str(schema), jinja_env, context)
    if role and ('{{' in str(role) or '{%' in str(role)):
        role = render_template(str(role), jinja_env, context)
    if authenticator and ('{{' in str(authenticator) or '{%' in str(authenticator)):
        authenticator = render_template(str(authenticator), jinja_env, context)
    
    auth_method = "key-pair" if private_key else "password"
    logger.debug(f"Snowflake connection params validated: account={account}, warehouse={warehouse}, "
                f"database={database}, auth_method={auth_method}")
    
    return account, user, password, private_key, private_key_passphrase, warehouse, database, schema, role, authenticator
