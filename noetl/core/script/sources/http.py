"""
HTTP/HTTPS script fetcher.
"""

from typing import Optional, Dict, Any
from jinja2 import Environment
import requests

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def fetch_from_http(
    endpoint: Optional[str],
    path: Optional[str],
    method: str,
    headers: Dict[str, str],
    timeout: int,
    context: Dict[str, Any],
    jinja_env: Environment
) -> str:
    """
    Fetch script content from HTTP/HTTPS endpoint.
    
    Args:
        endpoint: Full URL to fetch (takes precedence over path)
        path: Fallback path if endpoint not specified
        method: HTTP method (GET, POST, etc.)
        headers: Additional HTTP headers
        timeout: Request timeout in seconds
        context: Execution context for Jinja2 rendering
        jinja_env: Jinja2 environment
        
    Returns:
        Script content as string
        
    Raises:
        ValueError: Neither endpoint nor path specified
        ConnectionError: Network error or timeout
        FileNotFoundError: HTTP 404
        PermissionError: HTTP 401/403
        
    Security:
        - Validates SSL certificates by default
        - Supports custom headers for authentication
        - Configurable timeout to prevent hanging
    """
    try:
        # Determine URL
        url = endpoint
        if not url:
            if not path:
                raise ValueError("Either endpoint or path must be specified for http source")
            url = path
        
        # Render URL with Jinja2 if it contains templates
        if '{{' in url or '{%' in url:
            template = jinja_env.from_string(url)
            url = template.render(**context)
        
        # Render headers with Jinja2
        rendered_headers = {}
        for key, value in headers.items():
            if isinstance(value, str) and ('{{' in value or '{%' in value):
                template = jinja_env.from_string(value)
                rendered_headers[key] = template.render(**context)
            else:
                rendered_headers[key] = value
        
        # Make HTTP request
        logger.info(f"Fetching script from {url} (method: {method})")
        response = requests.request(
            method=method.upper(),
            url=url,
            headers=rendered_headers,
            timeout=timeout,
            verify=True  # SSL verification enabled by default
        )
        
        # Check response status
        if response.status_code == 404:
            raise FileNotFoundError(f"HTTP 404: Script not found at {url}")
        elif response.status_code in [401, 403]:
            raise PermissionError(f"HTTP {response.status_code}: Access denied to {url}")
        elif response.status_code >= 400:
            raise ConnectionError(f"HTTP {response.status_code}: Failed to fetch from {url}")
        
        # Return content
        content = response.text
        logger.info(f"Successfully fetched {len(content)} bytes from HTTP")
        return content
    
    except requests.exceptions.Timeout:
        logger.error(f"HTTP request timeout after {timeout}s: {url}")
        raise ConnectionError(f"Request timeout: {url}")
    
    except requests.exceptions.ConnectionError as e:
        logger.error(f"HTTP connection error: {e}")
        raise ConnectionError(f"Connection failed: {url}")
    
    except (FileNotFoundError, PermissionError):
        raise
    
    except Exception as e:
        logger.error(f"Error fetching script from HTTP: {e}")
        raise ConnectionError(f"Failed to fetch from {url}: {e}")
