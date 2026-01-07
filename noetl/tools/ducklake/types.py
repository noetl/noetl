"""Type definitions for DuckLake plugin."""

from typing import Dict, Any, Optional, Callable, List
from dataclasses import dataclass
from jinja2 import Environment as JinjaEnvironment

# Type aliases
ContextDict = Dict[str, Any]
LogEventCallback = Optional[Callable[[str, str], None]]


@dataclass
class DuckLakeConfig:
    """Configuration for DuckLake catalog and execution."""
    
    # Catalog configuration
    catalog_connection: str  # Postgres connection string for metastore
    catalog_name: str        # Name of the DuckLake catalog
    data_path: str          # Path to store data files
    
    # SQL commands
    commands: List[str]     # SQL commands to execute
    
    # Optional settings
    create_catalog: bool = True  # Auto-create catalog if it doesn't exist
    use_catalog: bool = True      # Run USE catalog before commands
    memory_limit: Optional[str] = None
    threads: Optional[int] = None
    
    def __post_init__(self):
        """Validate configuration after initialization."""
        if not self.catalog_connection:
            raise ValueError("catalog_connection is required")
        if not self.catalog_name:
            raise ValueError("catalog_name is required")
        if not self.data_path:
            raise ValueError("data_path is required")
        if not self.commands:
            raise ValueError("At least one command is required")
