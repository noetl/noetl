"""
PostgreSQL-specific authentication functions.
"""

from typing import Dict, Optional

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def get_postgres_auth(resolved_auth: Dict[str, Dict], use_auth: Optional[str] = None) -> Optional[Dict]:
    """
    Get postgres authentication from resolved auth map.
    
    Args:
        resolved_auth: Resolved auth map from resolve_auth_map
        use_auth: Specific alias to use, or None to auto-detect
        
    Returns:
        Postgres auth dict or None if not found
    """
    postgres_auths = {alias: spec for alias, spec in resolved_auth.items() 
                     if spec.get('type') == 'postgres'}
    
    if not postgres_auths:
        return None
        
    if use_auth:
        return postgres_auths.get(use_auth)
    elif len(postgres_auths) == 1:
        return list(postgres_auths.values())[0]
    else:
        # Multiple postgres auths found, need explicit selection
        logger.warning(f"AUTH: Multiple postgres auths found: {list(postgres_auths.keys())}. Use 'use_auth' to specify.")
        return None
