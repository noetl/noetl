"""
HTTP response processing for HTTP plugin.

Handles response parsing and data extraction.
"""

from typing import Dict, Any
import httpx

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def process_response(response: httpx.Response) -> Dict[str, Any]:
    """
    Process HTTP response and extract data.
    
    Args:
        response: httpx Response object
        
    Returns:
        Dictionary containing response metadata and data
    """
    response_data = {
        'status_code': response.status_code,
        'headers': dict(response.headers),
        'url': str(response.url),
        'elapsed': response.elapsed.total_seconds() if hasattr(response, 'elapsed') else None
    }
    
    logger.debug(f"HTTP: Response metadata={response_data}")
    
    try:
        response_content_type = response.headers.get('Content-Type', '').lower()
        logger.debug(f"HTTP: Response Content-Type={response_content_type}")
        
        if 'application/json' in response_content_type:
            response_data['data'] = response.json()
            logger.debug(f"HTTP: Parsed JSON response data")
        else:
            response_data['data'] = response.text
            logger.debug(f"HTTP: Using text response data")
    except Exception as e:
        logger.warning(f"HTTP: Failed to parse response content: {str(e)}")
        response_data['data'] = response.text
    
    return response_data


def create_mock_response(
    endpoint: str,
    method: str,
    params: Any,
    payload: Any,
    data: Any,
    mocked_reason: str = "local_domain"
) -> Dict[str, Any]:
    """
    Create a mock response for testing or local development.
    
    Args:
        endpoint: Target endpoint
        method: HTTP method
        params: Request parameters
        payload: Request payload
        data: Request data map
        mocked_reason: Reason for mocking
        
    Returns:
        Mock response dictionary
    """
    return {
        'status_code': 200,
        'headers': {},
        'url': str(endpoint),
        'elapsed': 0,
        'data': {
            'mocked': True,
            'reason': mocked_reason,
            'endpoint': str(endpoint),
            'method': method,
            'params': params,
            'payload': payload,
            'data': data
        }
    }
