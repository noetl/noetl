"""
Mock HTTP server for testing paginated API endpoints.

Provides realistic pagination patterns for integration testing.
"""

from fastapi import FastAPI, Query
import uvicorn
import sys
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

app = FastAPI()

# Configuration
ITEMS_PER_PAGE = 10
TOTAL_ITEMS = 35  # 4 pages total

# Track request attempts per page for flaky endpoint
flaky_attempts = defaultdict(int)


@app.get('/api/v1/assessments')
def get_assessments(page: int = Query(default=1), pageSize: int = Query(default=ITEMS_PER_PAGE)):
    """
    Page-number based pagination endpoint.
    
    Query params:
    - page: Page number (1-based, default: 1)
    - pageSize: Items per page (default: 10)
    
    Returns:
    {
        "data": [...],
        "paging": {
            "hasMore": bool,
            "page": int,
            "pageSize": int,
            "total": int
        }
    }
    """
    # Calculate pagination
    start_idx = (page - 1) * pageSize
    end_idx = start_idx + pageSize
    
    # Generate fake data
    all_items = [
        {'id': i, 'name': f'Assessment {i}', 'score': 50 + (i % 50)}
        for i in range(1, TOTAL_ITEMS + 1)
    ]
    
    # Slice for current page
    page_items = all_items[start_idx:end_idx]
    has_more = end_idx < TOTAL_ITEMS
    
    return {
        'data': page_items,
        'paging': {
            'hasMore': has_more,
            'page': page,
            'pageSize': pageSize,
            'total': TOTAL_ITEMS
        }
    }


@app.get('/api/v1/users')
def get_users(offset: int = Query(default=0), limit: int = Query(default=ITEMS_PER_PAGE)):
    """
    Offset-based pagination endpoint.
    Query params:
    - offset: Starting index (default: 0)
    - limit: Items per page (default: 10)
    
    Returns:
    {
        "users": [...],
        "has_more": bool,
        "offset": int,
        "limit": int,
        "total": int
    }
    """
    # Generate fake data
    all_users = [
        {'id': i, 'username': f'user{i}', 'email': f'user{i}@example.com'}
        for i in range(1, TOTAL_ITEMS + 1)
    ]
    
    # Slice for current page
    page_users = all_users[offset:offset + limit]
    has_more = (offset + limit) < TOTAL_ITEMS
    
    return {
        'users': page_users,
        'has_more': has_more,
        'offset': offset,
        'limit': limit,
        'total': TOTAL_ITEMS
    }


@app.get('/api/v1/events')
def get_events(cursor: str = Query(default=None), limit: int = Query(default=ITEMS_PER_PAGE)):
    """
    Cursor-based pagination endpoint.
    Query params:
    - cursor: Continuation token (base64-encoded page number)
    - limit: Items per page (default: 10)
    
    Returns:
    {
        "events": [...],
        "next_cursor": str|null,
        "limit": int
    }
    """
    import base64
    
    # Decode cursor to get page number
    if cursor:
        try:
            page = int(base64.b64decode(cursor).decode('utf-8'))
        except Exception:
            page = 1
    else:
        page = 1
    
    # Calculate pagination
    start_idx = (page - 1) * limit
    end_idx = start_idx + limit
    
    # Generate fake data
    all_events = [
        {
            'id': i,
            'type': 'user_action',
            'timestamp': f'2024-01-{(i % 28) + 1:02d}T12:00:00Z',
            'data': {'action': f'event_{i}'}
        }
        for i in range(1, TOTAL_ITEMS + 1)
    ]
    
    # Slice for current page
    page_events = all_events[start_idx:end_idx]
    
    # Generate next cursor
    next_cursor = None
    if end_idx < TOTAL_ITEMS:
        next_page = page + 1
        next_cursor = base64.b64encode(str(next_page).encode('utf-8')).decode('utf-8')
    
    return {
        'events': page_events,
        'next_cursor': next_cursor,
        'limit': limit
    }


@app.get('/api/v1/flaky')
def get_flaky(page: int = Query(default=1), fail_on: str = Query(default='')):
    """
    Flaky endpoint for retry testing.
    Query params:
    - page: Page number (1-based)
    - fail_on: Comma-separated page numbers to fail on FIRST attempt only
    
    Returns error for specified pages on first attempt, success on retry.
    """
    from fastapi import HTTPException
    
    fail_pages = [int(p) for p in fail_on.split(',') if p.strip()]
    
    # Track attempts for this page
    flaky_attempts[page] += 1
    
    # Fail only on first attempt
    if page in fail_pages and flaky_attempts[page] == 1:
        raise HTTPException(status_code=500, detail="Simulated failure")
    
    # Success response
    page_size = ITEMS_PER_PAGE
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size
    
    all_items = [
        {'id': i, 'value': f'item_{i}'}
        for i in range(1, TOTAL_ITEMS + 1)
    ]
    
    page_items = all_items[start_idx:end_idx]
    has_more = end_idx < TOTAL_ITEMS
    
    return {
        'data': page_items,
        'paging': {
            'hasMore': has_more,
            'page': page,
            'pageSize': page_size
        }
    }


@app.post('/api/v1/flaky/reset')
def reset_flaky():
    """Reset the flaky endpoint attempt counters."""
    global flaky_attempts
    flaky_attempts.clear()
    return {'status': 'reset', 'message': 'Flaky endpoint counters cleared'}


@app.get('/health')
def health():
    """Health check endpoint."""
    return {'status': 'ok'}


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5555
    logger.info(f"Starting mock pagination API on port {port}")
    logger.info(f"Total items: {TOTAL_ITEMS}, Items per page: {ITEMS_PER_PAGE}")
    logger.info("\nAvailable endpoints:")
    logger.info("  GET /api/v1/assessments?page=N&pageSize=M  - Page number pagination")
    logger.info("  GET /api/v1/users?offset=N&limit=M         - Offset pagination")
    logger.info("  GET /api/v1/events?cursor=TOKEN&limit=M    - Cursor pagination")
    logger.info("  GET /api/v1/flaky?page=N&fail_on=2,3       - Retry testing")
    logger.info("  GET /health                                - Health check")
    uvicorn.run(app, host='0.0.0.0', port=port, log_level='info')
