"""
DuckDB-specific authentication functions.
"""

from typing import Dict, List, Any

from noetl.core.logger import setup_logger
from noetl.core.utils.auth_normalize import as_mapping

logger = setup_logger(__name__, include_location=True)


def get_duckdb_secrets(resolved_auth: Dict[str, Dict]) -> List[str]:
    """
    Generate DuckDB CREATE SECRET statements from resolved auth map.
    
    Args:
        resolved_auth: Resolved auth map from resolve_auth_map
        
    Returns:
        List of SQL statements to create DuckDB secrets
    """
    statements = []
    
    for alias, spec in resolved_auth.items():
        auth_type = spec.get('type')
        secret_name = spec.get('secret_name', alias)
        
        if auth_type == 'postgres':
            parts = []
            if spec.get('db_host'):
                parts.append(f"HOST '{spec['db_host']}'")
            if spec.get('db_port'):
                parts.append(f"PORT {spec['db_port']}")  
            if spec.get('db_name'):
                parts.append(f"DATABASE '{spec['db_name']}'")
            if spec.get('db_user'):
                parts.append(f"USER '{spec['db_user']}'")
            if spec.get('db_password'):
                parts.append(f"PASSWORD '{spec['db_password']}'")
            if spec.get('sslmode'):
                parts.append(f"SSLMODE '{spec['sslmode']}'")
                
            if parts:
                statement = f"CREATE OR REPLACE SECRET {secret_name} (\n  TYPE postgres,\n  {',\n  '.join(parts)}\n);"
                statements.append(statement)
                
        elif auth_type == 'hmac':
            service = spec.get('service', 'gcs')
            if service == 'gcs':
                parts = []
                if spec.get('key_id'):
                    parts.append(f"KEY_ID '{spec['key_id']}'")
                if spec.get('secret_key'):
                    parts.append(f"SECRET '{spec['secret_key']}'")
                if spec.get('scope'):
                    parts.append(f"SCOPE '{spec['scope']}'")
                    
                if parts:
                    statement = f"CREATE OR REPLACE SECRET {secret_name} (\n  TYPE gcs,\n  {',\n  '.join(parts)}\n);"
                    statements.append(statement)
            elif service == 's3':
                parts = []
                if spec.get('key_id'):
                    parts.append(f"KEY_ID '{spec['key_id']}'")
                if spec.get('secret_key'):
                    parts.append(f"SECRET '{spec['secret_key']}'")
                if spec.get('region'):
                    parts.append(f"REGION '{spec['region']}'")
                if spec.get('endpoint'):
                    parts.append(f"ENDPOINT '{spec['endpoint']}'")
                if spec.get('scope'):
                    parts.append(f"SCOPE '{spec['scope']}'")
                    
                if parts:
                    statement = f"CREATE OR REPLACE SECRET {secret_name} (\n  TYPE s3,\n  {',\n  '.join(parts)}\n);"
                    statements.append(statement)
    
    return statements


def get_required_extensions(resolved_auth: Dict[str, Any]) -> List[str]:
    """
    Get list of DuckDB extensions required for the given auth map.
    
    Args:
        resolved_auth: Resolved auth map - can contain dicts or ResolvedAuthItem objects
        
    Returns:
        List of extension names to install/load
    """
    # Map auth types to required extensions
    EXTS_BY_TYPE = {
        "postgres": {"postgres"},
        "pg": {"postgres"},
        "mysql": {"mysql"},
        "hmac": {"httpfs"},          # for GCS/S3-style signed access
        "gcs": {"httpfs"},
        "s3": {"httpfs"},
        "azure": {"azure", "httpfs"},
    }
    
    extensions = set()
    
    if not resolved_auth:
        return list(extensions)

    for alias, item in resolved_auth.items():
        # Normalize item to dict regardless of input type
        normalized = as_mapping(item)
        
        # Try multiple fields to determine the auth type
        auth_type = (
            normalized.get("type") or 
            normalized.get("kind") or 
            normalized.get("engine") or 
            normalized.get("provider") or 
            normalized.get("service") or
            normalized.get("source")
        )
        
        if not auth_type:
            # Log debug message with class name for diagnostics
            item_type = type(item).__name__ if item is not None else "None"
            logger.debug(
                "Auth alias '%s' missing type/kind/provider; item=%r (%s)", 
                alias, item, item_type
            )
            continue
            
        auth_type_str = str(auth_type).lower()
        required_exts = EXTS_BY_TYPE.get(auth_type_str)
        
        if not required_exts:
            logger.debug(
                "No extension mapping for auth alias '%s' (type=%s); normalized=%r", 
                alias, auth_type_str, normalized
            )
            continue
            
        extensions.update(required_exts)
        logger.debug(
            "Auth alias '%s' type '%s' requires extensions: %s", 
            alias, auth_type_str, sorted(required_exts)
        )
    
    result = sorted(extensions)
    logger.debug("Total required extensions: %s", result)
    return result
