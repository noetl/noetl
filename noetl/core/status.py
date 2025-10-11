"""
Status validation and normalization utilities for NoETL events.
"""

from typing import Union, Optional


# Define the canonical status values (uppercase) - comprehensive set for all scenarios
VALID_STATUSES = {
    'STARTED',
    'RUNNING', 
    'PAUSED',
    'PENDING',
    'FAILED',
    'COMPLETED'
}

# Status mapping for normalization to uppercase
STATUS_MAPPINGS = {
    # completed variants
    'complete': 'COMPLETED',
    'completed': 'COMPLETED',
    'success': 'COMPLETED', 
    'succeeded': 'COMPLETED',
    'done': 'COMPLETED',
    # failed variants  
    'error': 'FAILED',
    'failed': 'FAILED',
    'failure': 'FAILED',
    # running variants
    'run': 'RUNNING',
    'running': 'RUNNING',
    'in_progress': 'RUNNING',
    'in-progress': 'RUNNING', 
    'progress': 'RUNNING',
    # started variants
    'start': 'STARTED',
    'started': 'STARTED',
    'begin': 'STARTED',
    'beginning': 'STARTED',
    'initiated': 'STARTED',
    # pending variants
    'created': 'PENDING',
    'pending': 'PENDING',
    'queued': 'PENDING', 
    'init': 'PENDING',
    'initialized': 'PENDING',
    'new': 'PENDING',
    'waiting': 'PENDING',
    # paused variants
    'paused': 'PAUSED',
    'pause': 'PAUSED',
    'suspended': 'PAUSED',
    'stopped': 'PAUSED',
    'halted': 'PAUSED'
}


def normalize_status(raw_status: Union[str, None]) -> str:
    """
    Normalize a status string to one of the canonical uppercase values.
    
    Args:
        raw_status: The raw status string to normalize
        
    Returns:
        One of: 'STARTED', 'RUNNING', 'PAUSED', 'PENDING', 'FAILED', 'COMPLETED'
        
    Raises:
        ValueError: If the status cannot be normalized to a valid value
    """
    if not raw_status:
        return 'PENDING'
        
    # Convert to lowercase and strip whitespace for mapping
    normalized_key = str(raw_status).strip().lower()
    
    # Check if already a valid uppercase status
    if str(raw_status).strip().upper() in VALID_STATUSES:
        return str(raw_status).strip().upper()
        
    # Try to map from known variants
    if normalized_key in STATUS_MAPPINGS:
        return STATUS_MAPPINGS[normalized_key]
        
    # If we can't normalize it, raise an error
    raise ValueError(
        f"Invalid status '{raw_status}'. Must be one of {VALID_STATUSES} "
        f"or a known variant: {list(STATUS_MAPPINGS.keys())}"
    )


def validate_status(status: str) -> str:
    """
    Validate that a status is one of the canonical uppercase values.
    
    Args:
        status: The status to validate
        
    Returns:
        The validated status
        
    Raises:
        ValueError: If the status is not valid
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Must be one of {VALID_STATUSES}"
        )
    return status


def is_valid_status(status: str) -> bool:
    """
    Check if a status is valid without raising an exception.
    
    Args:
        status: The status to check
        
    Returns:
        True if the status is valid, False otherwise
    """
    return status in VALID_STATUSES

from typing import Union, Optional


# Define the canonical status values (uppercase) - comprehensive set for all scenarios
VALID_STATUSES = {
    'STARTED',
    'RUNNING', 
    'PAUSED',
    'PENDING',
    'FAILED',
    'COMPLETED'
}


def normalize_status(raw_status: Union[str, None]) -> str:
    """
    Normalize a status string to one of the canonical uppercase values.
    
    Args:
        raw_status: The raw status string to normalize
        
    Returns:
        One of: 'STARTED', 'RUNNING', 'PAUSED', 'PENDING', 'FAILED', 'COMPLETED'
        
    Raises:
        ValueError: If the status cannot be normalized to a valid value
    """
    if not raw_status:
        return 'PENDING'
        
    # Convert to lowercase and strip whitespace for mapping
    normalized_key = str(raw_status).strip().lower()
    
    # Check if already a valid uppercase status
    if str(raw_status).strip().upper() in VALID_STATUSES:
        return str(raw_status).strip().upper()
        
    # Try to map from known variants
    if normalized_key in STATUS_MAPPINGS:
        return STATUS_MAPPINGS[normalized_key]
        
    # If we can't normalize it, raise an error
    raise ValueError(
        f"Invalid status '{raw_status}'. Must be one of {VALID_STATUSES} "
        f"or a known variant: {list(STATUS_MAPPINGS.keys())}"
    )


def validate_status(status: str) -> str:
    """
    Validate that a status is one of the canonical uppercase values.
    
    Args:
        status: The status to validate
        
    Returns:
        The validated status
        
    Raises:
        ValueError: If the status is not valid
    """
    if status not in VALID_STATUSES:
        raise ValueError(
            f"Invalid status '{status}'. Must be one of {VALID_STATUSES}"
        )
    return status


def is_valid_status(status: str) -> bool:
    """
    Check if a status is valid without raising an exception.
    
    Args:
        status: The status to check
        
    Returns:
        True if the status is valid, False otherwise
    """
    return status in VALID_STATUSES