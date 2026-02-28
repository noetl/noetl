"""
HTTP response processing for HTTP plugin.

Handles response parsing and data extraction.
"""

import os
from typing import Dict, Any, Optional
import httpx

from noetl.core.logger import setup_logger
from noetl.core.sanitize import sanitize_headers

logger = setup_logger(__name__, include_location=True)

# Allow opting out of sink-driven reference wrapping (useful for local/kind clusters
# where keeping full payloads inline is preferable for debugging).
SINK_REFERENCES_ENABLED = os.getenv("NOETL_SINK_REFERENCES_ENABLED", "true").lower() not in (
    "0",
    "false",
    "no",
    "off",
)


def process_response(response: httpx.Response) -> Dict[str, Any]:
    """
    Process HTTP response and extract data.
    
    Args:
        response: httpx Response object
        
    Returns:
        Dictionary containing response metadata and data
    """
    raw_headers = dict(response.headers)
    response_data = {
        'status_code': response.status_code,
        'headers': raw_headers,
        'url': str(response.url),
        'elapsed': response.elapsed.total_seconds() if hasattr(response, 'elapsed') else None
    }
    
    logger.debug(
        "HTTP: Response metadata status=%s url=%s elapsed=%s header_keys=%s",
        response.status_code,
        response_data["url"],
        response_data["elapsed"],
        list(sanitize_headers(raw_headers).keys()),
    )
    
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


def build_result_reference(
    response_data: Dict[str, Any],
    sink_config: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """
    Build result reference when sink is present.
    
    When a sink is configured for the step, return metadata and reference
    information instead of the full response data. The actual data is included
    in _internal_data for worker to execute the sink, but is removed before
    storing in events.
    
    Args:
        response_data: Full HTTP response data
        sink_config: Sink configuration from step
        
    Returns:
        Dictionary with data_reference, metadata, and _internal_data
    """
    if not sink_config or not SINK_REFERENCES_ENABLED:
        return response_data
    
    # Extract sink tool configuration
    sink_tool = sink_config.get('tool', {})
    if isinstance(sink_tool, str):
        sink_kind = sink_tool
        sink_table = None
    else:
        sink_kind = sink_tool.get('kind', 'unknown')
        sink_table = sink_tool.get('table')
    
    # Extract data summary from response
    data = response_data.get('data', {})
    
    # Calculate row count based on data structure
    row_count = 0
    key_range = None
    
    if isinstance(data, dict):
        # Handle nested data structures (e.g., {data: [...], paging: {...}})
        inner_data = data.get('data', [])
        if isinstance(inner_data, list):
            row_count = len(inner_data)
            # Extract ID range if items have id field
            if inner_data and isinstance(inner_data[0], dict) and 'id' in inner_data[0]:
                ids = [item.get('id') for item in inner_data if isinstance(item, dict) and 'id' in item]
                if ids:
                    key_range = {'min_id': min(ids), 'max_id': max(ids)}
    elif isinstance(data, list):
        row_count = len(data)
        # Extract ID range if items have id field
        if data and isinstance(data[0], dict) and 'id' in data[0]:
            ids = [item.get('id') for item in data if isinstance(item, dict) and 'id' in item]
            if ids:
                key_range = {'min_id': min(ids), 'max_id': max(ids)}
    else:
        row_count = 1
    
    logger.info(
        f"HTTP.BUILD_REFERENCE: Building result reference | "
        f"sink_type={sink_kind} | table={sink_table} | row_count={row_count}"
    )
    
    # Build reference structure
    reference = {
        'data_reference': {
            'sink_type': sink_kind,
            'table': sink_table,
            'row_count': row_count,
        },
        'metadata': {
            'url': response_data.get('url'),
            'status_code': response_data.get('status_code'),
            'elapsed': response_data.get('elapsed'),
            'content_length': len(str(data)) if data else 0
        },
        # Include actual data for worker to execute sink (removed before event storage)
        '_internal_data': data,
        # Also expose via 'data' field for backwards compatibility with case conditions
        # Worker will access _internal_data, but Jinja2 templates can use response.data.*
        'data': data
    }
    
    # Add key range if available
    if key_range:
        reference['data_reference']['key_range'] = key_range
    
    return reference
