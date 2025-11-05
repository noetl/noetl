"""
Catalog API package providing endpoints and storage service for catalog resources.
This package consolidates the former server API endpoints and storage DAO into a
single namespace. No endpoints are defined in this __init__; it only re-exports
public symbols for convenient imports and backward compatibility.
"""

from .endpoint import router
# , get_playbook_entry_from_catalog
from .service import CatalogService, get_catalog_service
#, CatalogEntry
from .schema import CatalogEntry

__all__ = [
    'router',
#    'get_playbook_entry_from_catalog',
    'CatalogService',
    'get_catalog_service',
#    'CatalogEntry',
    'CatalogEntry',
]
