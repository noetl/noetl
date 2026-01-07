"""
Pydantic models for PostgreSQL tool configuration validation.
"""

from typing import Optional
from pydantic import BaseModel, Field, field_validator


class PostgresPoolConfig(BaseModel):
    """
    Configuration for PostgreSQL connection pool.
    
    Validates pool parameters before applying them to AsyncConnectionPool.
    All parameters are optional and will use defaults if not specified.
    """
    
    name: Optional[str] = Field(
        default=None,
        description="Pool name for sharing across steps. If not specified, defaults to execution_id (pool per playbook). "
                    "Use explicit name to share pool across multiple steps: pool: {name: 'shared_pool'}"
    )
    
    timeout: Optional[float] = Field(
        default=None,
        description="Timeout in seconds for acquiring connection from pool. "
                    "None = default 10s, -1 = infinite wait, positive number = custom timeout"
    )
    
    min_size: Optional[int] = Field(
        default=None,
        ge=1,
        le=100,
        description="Minimum number of connections to maintain in pool (1-100, default 2)"
    )
    
    max_size: Optional[int] = Field(
        default=None,
        ge=1,
        le=1000,
        description="Maximum number of connections allowed in pool (1-1000, default 20)"
    )
    
    max_waiting: Optional[int] = Field(
        default=None,
        ge=0,
        le=10000,
        description="Maximum number of requests waiting for connection (0-10000, default 50)"
    )
    
    max_lifetime: Optional[float] = Field(
        default=None,
        ge=0,
        description="Maximum lifetime of a connection in seconds (default 3600 = 1 hour)"
    )
    
    max_idle: Optional[float] = Field(
        default=None,
        ge=0,
        description="Maximum idle time before connection is closed in seconds (default 300 = 5 min)"
    )
    
    @field_validator('timeout')
    @classmethod
    def validate_timeout(cls, v):
        """Validate timeout: None, -1 (infinite), or positive number."""
        if v is not None and v != -1 and v < 0:
            raise ValueError("timeout must be None (default), -1 (infinite), or positive number")
        return v
    
    @field_validator('max_size')
    @classmethod
    def validate_max_size_vs_min(cls, v, info):
        """Ensure max_size >= min_size if both specified."""
        if v is not None and 'min_size' in info.data and info.data['min_size'] is not None:
            if v < info.data['min_size']:
                raise ValueError(f"max_size ({v}) must be >= min_size ({info.data['min_size']})")
        return v
    
    model_config = {
        "extra": "forbid",  # Reject unknown fields
        "str_strip_whitespace": True,
    }


def validate_pool_config(pool_config: dict) -> dict:
    """
    Validate and normalize pool configuration.
    
    Args:
        pool_config: Dictionary with pool parameters from playbook
        
    Returns:
        Validated dictionary ready to pass to AsyncConnectionPool
        
    Raises:
        ValueError: If validation fails
        
    Example:
        >>> config = {"timeout": 60, "max_size": 50, "min_size": 5}
        >>> validated = validate_pool_config(config)
        >>> # Use validated config with pool
    """
    if not pool_config:
        return {}
    
    try:
        model = PostgresPoolConfig(**pool_config)
        # Return only non-None values
        return {k: v for k, v in model.model_dump().items() if v is not None}
    except Exception as e:
        raise ValueError(f"Invalid pool configuration: {e}")
