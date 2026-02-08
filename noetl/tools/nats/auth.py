"""
NATS authentication and connection parameter resolution.

This module handles:
- Unified auth system resolution
- Connection parameter mapping and validation
"""

from typing import Dict, Tuple
from jinja2 import Environment
from noetl.core.logger import setup_logger
from noetl.worker.secrets import fetch_credential_by_key
from noetl.worker.auth_resolver import resolve_auth
from noetl.worker.auth_compatibility import transform_credentials_to_auth, validate_auth_transition

logger = setup_logger(__name__, include_location=True)


def resolve_nats_auth(
    task_config: Dict,
    task_with: Dict,
    jinja_env: Environment,
    context: Dict
) -> Tuple[Dict, Dict]:
    """
    Resolve NATS authentication and apply backwards compatibility transformations.

    Args:
        task_config: The task configuration
        task_with: The rendered 'with' parameters dictionary
        jinja_env: The Jinja2 environment for template rendering
        context: The context for rendering templates

    Returns:
        Tuple of (updated task_config, updated task_with)
    """
    # Apply backwards compatibility transformation
    validate_auth_transition(task_config, task_with)
    task_config, task_with = transform_credentials_to_auth(task_config, task_with)

    # Resolve unified auth system
    nats_auth = None
    try:
        auth_config = task_config.get('auth') or task_with.get('auth')
        if auth_config:
            logger.debug("NATS: Using unified auth system")
            mode, resolved_items = resolve_auth(auth_config, jinja_env, context)

            # For NATS, we expect single auth mode
            resolved_auth = None
            if resolved_items:
                resolved_auth = list(resolved_items.values())[0]

            if resolved_auth:
                logger.debug(
                    f"NATS: Resolved auth service: '{resolved_auth.service}', "
                    f"payload keys: {list(resolved_auth.payload.keys()) if resolved_auth.payload else 'None'}"
                )

                # Accept 'nats' service or generic credentials
                if resolved_auth.service in ('nats', None, ''):
                    nats_auth = resolved_auth.payload
                    logger.debug(f"NATS: Using auth with fields: {list(nats_auth.keys())}")

                    # Map auth fields to NATS connection parameters
                    field_mapping = {
                        # Direct field names
                        'nats_url': 'nats_url',
                        'url': 'nats_url',
                        'server': 'nats_url',
                        'servers': 'nats_url',
                        # Auth fields
                        'user': 'nats_user',
                        'username': 'nats_user',
                        'nats_user': 'nats_user',
                        'password': 'nats_password',
                        'nats_password': 'nats_password',
                        'token': 'nats_token',
                        'nats_token': 'nats_token',
                        # TLS fields
                        'tls_cert': 'tls_cert',
                        'tls_key': 'tls_key',
                        'tls_ca': 'tls_ca',
                    }

                    # Apply resolved auth to task_with (task_with takes precedence)
                    for auth_key, task_key in field_mapping.items():
                        if task_key not in task_with and nats_auth.get(auth_key) is not None:
                            task_with[task_key] = nats_auth[auth_key]
                            # Mask sensitive values
                            sensitive = ('password', 'token', 'key', 'secret')
                            val = '***' if any(t in auth_key.lower() for t in sensitive) else nats_auth[auth_key]
                            logger.debug(f"NATS: Mapped {auth_key}={val} -> {task_key}")
                else:
                    logger.warning(f"NATS: Expected 'nats' service, got '{resolved_auth.service}'")
    except Exception as e:
        logger.debug(f"NATS: Unified auth processing failed: {e}", exc_info=True)

    # Legacy fallback: resolve single auth/credential reference
    if not nats_auth:
        try:
            cred_ref = task_with.get('auth') or task_config.get('auth')
            if cred_ref and isinstance(cred_ref, str):
                logger.debug("NATS: Using legacy auth system")
                try:
                    data = fetch_credential_by_key(str(cred_ref))
                except Exception:
                    data = {}
                if isinstance(data, dict):
                    field_mapping = {
                        'url': 'nats_url',
                        'nats_url': 'nats_url',
                        'server': 'nats_url',
                        'user': 'nats_user',
                        'username': 'nats_user',
                        'password': 'nats_password',
                        'token': 'nats_token',
                    }
                    for src, dst in field_mapping.items():
                        if dst not in task_with and data.get(src) is not None:
                            task_with[dst] = data.get(src)
        except Exception:
            logger.debug("NATS: Failed to resolve legacy auth credential", exc_info=True)

    return task_config, task_with


def get_nats_connection_params(task_with: Dict) -> Dict:
    """
    Extract and validate NATS connection parameters from task_with.

    Args:
        task_with: The rendered 'with' parameters dictionary

    Returns:
        Dictionary with connection parameters

    Raises:
        ValueError: If required parameters are missing
    """
    nats_url = task_with.get('nats_url')
    if not nats_url:
        raise ValueError(
            "NATS URL is not configured. Use `auth: <credential_key>` or "
            "provide `nats_url` in the task configuration."
        )

    return {
        'url': nats_url,
        'user': task_with.get('nats_user'),
        'password': task_with.get('nats_password'),
        'token': task_with.get('nats_token'),
        'tls_cert': task_with.get('tls_cert'),
        'tls_key': task_with.get('tls_key'),
        'tls_ca': task_with.get('tls_ca'),
    }
