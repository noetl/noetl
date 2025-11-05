"""
Field normalization functions for different authentication types.
"""

from typing import Dict

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def normalize_postgres_fields(record: Dict) -> Dict:
    """
    Normalize postgres credential fields to standard names.
    
    Args:
        record: Raw credential record
        
    Returns:
        Normalized postgres fields
    """
    normalized = {}
    
    # Map common field variations to standard names
    field_mapping = {
        'host': 'db_host',
        'hostname': 'db_host', 
        'server': 'db_host',
        'port': 'db_port',
        'database': 'db_name',
        'db': 'db_name',
        'user': 'db_user',
        'username': 'db_user',
        'password': 'db_password',
        'ssl': 'sslmode',
        'sslmode': 'sslmode'
    }
    
    for key, value in record.items():
        mapped_key = field_mapping.get(key, key)
        if mapped_key.startswith('db_') or mapped_key == 'sslmode':
            normalized[mapped_key] = value
        elif key in field_mapping.values():
            normalized[key] = value
    
    return normalized


def normalize_hmac_fields(record: Dict, service: str) -> Dict:
    """
    Normalize HMAC credential fields for GCS/S3.
    
    Args:
        record: Raw credential record
        service: Service type (gcs or s3)
        
    Returns:
        Normalized HMAC fields
    """
    normalized = {'service': service}
    
    # Map common field variations
    field_mapping = {
        'access_key_id': 'key_id',
        'access_key': 'key_id',
        'secret_access_key': 'secret_key',
        'secret': 'secret_key'
    }
    
    for key, value in record.items():
        mapped_key = field_mapping.get(key, key)
        normalized[mapped_key] = value
    
    return normalized
