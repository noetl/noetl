"""
Mock HTTP server for testing paginated API endpoints.

Provides realistic pagination patterns for integration testing.
Includes heavy payload endpoints for load testing pipeline execution.
"""

from fastapi import FastAPI, Query, Response, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
import sys
import time
import random
import string
import hashlib
import asyncio
import os
from collections import defaultdict
import logging

logger = logging.getLogger(__name__)

app = FastAPI()

# Configuration
ITEMS_PER_PAGE = 10
TOTAL_ITEMS = 35  # 4 pages total
HEAVY_TOTAL_ITEMS = 100  # More items for heavy payload tests

# Track request attempts per page for flaky endpoint
flaky_attempts = defaultdict(int)
rate_limit_tracker = defaultdict(list)  # Track requests per second

# /api/v1/patient-records configuration (env var overrides)
PR_DELAY_MIN = float(os.getenv("PATIENT_RECORDS_DELAY_MIN", "2.0"))
PR_DELAY_MAX = float(os.getenv("PATIENT_RECORDS_DELAY_MAX", "4.0"))
PR_PAGE_MIN = int(os.getenv("PATIENT_RECORDS_PAGE_MIN", "2"))
PR_PAGE_MAX = int(os.getenv("PATIENT_RECORDS_PAGE_MAX", "5"))
PR_PAYLOAD_KB = int(os.getenv("PATIENT_RECORDS_PAYLOAD_KB", "100"))
PR_RATE_LIMIT = int(os.getenv("PATIENT_RECORDS_RATE_LIMIT", "50"))

# Sliding-window rate limit tracker for /api/v1/patient-records (global)
patient_records_rate_window: list[float] = []


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


# ============================================================================
# Heavy Payload Endpoints - For load testing pipeline execution
# ============================================================================

def generate_heavy_item(item_id: int, payload_kb: int = 10) -> dict:
    """Generate a single item with configurable payload size."""
    # Generate random payload data to simulate heavy response
    payload_chars = payload_kb * 1024  # Convert KB to bytes
    random_data = ''.join(random.choices(string.ascii_letters + string.digits, k=payload_chars))

    return {
        'id': item_id,
        'name': f'Heavy Assessment {item_id}',
        'score': 50 + (item_id % 50),
        'category': random.choice(['finance', 'technology', 'healthcare', 'education']),
        'metadata': {
            'created_at': f'2024-01-{(item_id % 28) + 1:02d}T12:00:00Z',
            'updated_at': f'2024-01-{(item_id % 28) + 1:02d}T14:30:00Z',
            'version': f'1.{item_id % 10}.0',
            'tags': [f'tag_{i}' for i in range(5)],
        },
        'description': f'This is a detailed description for assessment {item_id}. ' * 10,
        'payload': random_data,  # Heavy payload
    }


@app.get('/api/v1/heavy')
def get_heavy_items(
    page: int = Query(default=1),
    pageSize: int = Query(default=10),
    payload_kb: int = Query(default=10, description="Payload size per item in KB"),
):
    """
    Heavy payload pagination endpoint for load testing.

    Query params:
    - page: Page number (1-based, default: 1)
    - pageSize: Items per page (default: 10)
    - payload_kb: Size of random payload per item in KB (default: 10)

    Example: /api/v1/heavy?page=1&pageSize=5&payload_kb=100
    Returns 5 items, each with ~100KB of payload data (~500KB total response)
    """
    start_idx = (page - 1) * pageSize
    end_idx = start_idx + pageSize

    # Generate heavy items for current page
    page_items = [
        generate_heavy_item(i, payload_kb)
        for i in range(start_idx + 1, min(end_idx + 1, HEAVY_TOTAL_ITEMS + 1))
    ]

    has_more = end_idx < HEAVY_TOTAL_ITEMS

    response_size = len(str(page_items))
    logger.info(f"Heavy endpoint: page={page}, items={len(page_items)}, ~{response_size/1024:.1f}KB")

    return {
        'data': page_items,
        'paging': {
            'hasMore': has_more,
            'page': page,
            'pageSize': pageSize,
            'total': HEAVY_TOTAL_ITEMS
        },
        'meta': {
            'payload_kb_per_item': payload_kb,
            'estimated_response_kb': response_size // 1024
        }
    }


@app.get('/api/v1/heavy/stats')
def get_heavy_stats():
    """Get stats about heavy endpoint configuration."""
    return {
        'total_items': HEAVY_TOTAL_ITEMS,
        'default_payload_kb': 10,
        'max_recommended_payload_kb': 1000,
        'example_urls': [
            '/api/v1/heavy?page=1&pageSize=10&payload_kb=10',
            '/api/v1/heavy?page=1&pageSize=5&payload_kb=100',
            '/api/v1/heavy?page=1&pageSize=2&payload_kb=500',
        ]
    }


# ============================================================================
# Error Simulation Endpoints - For testing catch.cond error handling
# ============================================================================

@app.get('/api/v1/errors')
def get_with_errors(
    page: int = Query(default=1),
    error_type: str = Query(default=None, description="Error to simulate: 429, 500, 503, timeout, auth"),
    retry_after: int = Query(default=5, description="Retry-After header value for 429"),
):
    """
    Error simulation endpoint for testing catch.cond patterns.

    Query params:
    - page: Page number
    - error_type: Type of error to simulate (429, 500, 503, timeout, auth)
    - retry_after: Retry-After header value for rate limit errors

    Returns error responses for testing retry/skip/fail logic.
    """
    if error_type == '429':
        return JSONResponse(
            status_code=429,
            content={'error': 'Too Many Requests', 'message': 'Rate limit exceeded'},
            headers={'Retry-After': str(retry_after)}
        )

    elif error_type == '500':
        raise HTTPException(status_code=500, detail="Internal Server Error - simulated")

    elif error_type == '503':
        return JSONResponse(
            status_code=503,
            content={'error': 'Service Unavailable', 'message': 'Server temporarily unavailable'},
            headers={'Retry-After': str(retry_after)}
        )

    elif error_type == 'timeout':
        # Simulate a slow response (30 seconds)
        time.sleep(30)
        return {'data': [], 'simulated': 'timeout'}

    elif error_type == 'auth':
        raise HTTPException(status_code=401, detail="Unauthorized - invalid credentials")

    elif error_type == '403':
        raise HTTPException(status_code=403, detail="Forbidden - insufficient permissions")

    elif error_type == '404':
        raise HTTPException(status_code=404, detail="Not Found - resource does not exist")

    # No error - return normal response
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


@app.get('/api/v1/rate-limited')
def get_rate_limited(
    page: int = Query(default=1),
    requests_per_second: int = Query(default=2, description="Max requests per second"),
):
    """
    Rate-limited endpoint that enforces actual rate limiting.

    Query params:
    - page: Page number
    - requests_per_second: Maximum allowed requests per second (default: 2)

    Returns 429 with Retry-After header when rate limit exceeded.
    """
    now = time.time()
    key = 'rate_limited'

    # Clean old entries (older than 1 second)
    rate_limit_tracker[key] = [t for t in rate_limit_tracker[key] if now - t < 1]

    # Check rate limit
    if len(rate_limit_tracker[key]) >= requests_per_second:
        wait_time = 1 - (now - rate_limit_tracker[key][0])
        return JSONResponse(
            status_code=429,
            content={
                'error': 'Rate limit exceeded',
                'requests_in_window': len(rate_limit_tracker[key]),
                'limit': requests_per_second
            },
            headers={'Retry-After': str(max(1, int(wait_time) + 1))}
        )

    # Record this request
    rate_limit_tracker[key].append(now)

    # Return normal response
    page_size = ITEMS_PER_PAGE
    start_idx = (page - 1) * page_size
    end_idx = start_idx + page_size

    all_items = [
        {'id': i, 'value': f'item_{i}', 'rate_limited': True}
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
        },
        'rate_limit': {
            'requests_in_window': len(rate_limit_tracker[key]),
            'limit': requests_per_second
        }
    }


# ============================================================================
# Patient Records - FHIR-like endpoint for fetch-step load testing
# Replicates fetch_medications behavior: deep pagination, large payloads,
# simulated latency, and global rate limiting.
# ============================================================================

@app.get('/api/v1/patient-records')
async def get_patient_records(
    patientId: str = Query(..., description="Patient identifier"),
    page: int = Query(default=1, ge=1),
    pageSize: int = Query(default=10, ge=1),
    delay_min: float = Query(default=None, description="Override min delay seconds"),
    delay_max: float = Query(default=None, description="Override max delay seconds"),
    payload_kb: int = Query(default=None, description="Override response payload KB"),
    rate_limit: int = Query(default=None, description="Override global rate limit req/s"),
):
    """
    FHIR-like paginated endpoint for fetch-step load testing.

    Simulates deep pagination with large payloads to trigger GCS externalization,
    matching the behavior of fetch_medications in production playbooks.

    Response shape:
    {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": <int>,
        "entry": [{ "fullUrl": "...", "resource": { ... } }, ...],
        "link": [
            { "relation": "self", "url": "..." },
            { "relation": "next", "url": "..." }   # omitted on last page
        ]
    }

    Rate limit: 50 req/s globally (env: PATIENT_RECORDS_RATE_LIMIT).
    Returns 429 + Retry-After: 1 on breach.
    """
    global patient_records_rate_window

    eff_delay_min = delay_min if delay_min is not None else PR_DELAY_MIN
    eff_delay_max = delay_max if delay_max is not None else PR_DELAY_MAX
    eff_payload_kb = payload_kb if payload_kb is not None else PR_PAYLOAD_KB
    eff_rate_limit = rate_limit if rate_limit is not None else PR_RATE_LIMIT

    # --- Global rate limiting (sliding window, 1-second bucket) ---
    now = time.time()
    patient_records_rate_window = [t for t in patient_records_rate_window if now - t < 1.0]
    if len(patient_records_rate_window) >= eff_rate_limit:
        logger.warning(f"Rate limit hit: {len(patient_records_rate_window)} req in last 1s (limit={eff_rate_limit})")
        return JSONResponse(
            status_code=429,
            content={"error": "Too Many Requests", "message": "Rate limit exceeded"},
            headers={"Retry-After": "1"},
        )
    patient_records_rate_window.append(now)

    # --- Deterministic page count per patientId ---
    seed = int(hashlib.md5(patientId.encode()).hexdigest(), 16)
    rng = random.Random(seed)
    total_pages = rng.randint(PR_PAGE_MIN, PR_PAGE_MAX)

    if page > total_pages:
        return {
            "resourceType": "Bundle",
            "type": "searchset",
            "total": 0,
            "entry": [],
            "link": [{"relation": "self", "url": f"/api/v1/patient-records?patientId={patientId}&page={page}&pageSize={pageSize}"}],
        }

    # --- Server-side latency simulation ---
    await asyncio.sleep(random.uniform(eff_delay_min, eff_delay_max))

    # --- Build FHIR-like entries with ~payload_kb total response size ---
    # Reserve ~2 KB for JSON envelope overhead; spread remaining across entries.
    target_padding_bytes = max(0, eff_payload_kb * 1024 - 2048)
    padding_per_entry = max(0, target_padding_bytes // pageSize)

    entries = []
    for i in range(pageSize):
        entry_idx = (page - 1) * pageSize + i
        entry_id = f"{patientId}-p{page}-e{entry_idx}"
        entries.append({
            "fullUrl": f"urn:uuid:{entry_id}",
            "resource": {
                "resourceType": "MedicationStatement",
                "id": entry_id,
                "status": "active",
                "subject": {"reference": f"Patient/{patientId}"},
                "medicationCodeableConcept": {
                    "coding": [{
                        "system": "http://www.nlm.nih.gov/research/umls/rxnorm",
                        "code": str(1000 + entry_idx),
                        "display": f"Drug {entry_idx}",
                    }],
                    "text": f"Medication {entry_idx}",
                },
                "dosage": [{"text": f"{(entry_idx % 3 + 1) * 10}mg daily"}],
                "effectivePeriod": {"start": f"2024-01-{(entry_idx % 28) + 1:02d}"},
                "drugClass": f"Class-{entry_idx % 10}",
                "_padding": "x" * padding_per_entry,
            },
        })

    has_next = page < total_pages
    base_url = f"/api/v1/patient-records?patientId={patientId}&pageSize={pageSize}"
    links = [{"relation": "self", "url": f"{base_url}&page={page}"}]
    if has_next:
        links.append({"relation": "next", "url": f"{base_url}&page={page + 1}"})

    response_body = {
        "resourceType": "Bundle",
        "type": "searchset",
        "total": total_pages * pageSize,
        "entry": entries,
        "link": links,
    }

    logger.info(
        f"patient-records: patientId={patientId} page={page}/{total_pages} "
        f"entries={len(entries)} delay={eff_delay_min}-{eff_delay_max}s "
        f"target_kb={eff_payload_kb}"
    )

    return response_body


@app.get('/health')
def health():
    """Health check endpoint."""
    return {'status': 'ok'}


if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 5555
    print(f"Starting mock pagination API on port {port}")
    print(f"Total items: {TOTAL_ITEMS}, Items per page: {ITEMS_PER_PAGE}")
    print(f"Heavy items: {HEAVY_TOTAL_ITEMS}")
    print("\nAvailable endpoints:")
    print("  Pagination:")
    print("    GET /api/v1/assessments?page=N&pageSize=M     - Page number pagination")
    print("    GET /api/v1/users?offset=N&limit=M            - Offset pagination")
    print("    GET /api/v1/events?cursor=TOKEN&limit=M       - Cursor pagination")
    print("  Load Testing:")
    print("    GET /api/v1/heavy?page=N&payload_kb=100       - Heavy payload (configurable KB per item)")
    print("    GET /api/v1/heavy/stats                       - Heavy endpoint configuration")
    print("    GET /api/v1/patient-records?patientId=P&page=N&pageSize=M - FHIR-like, ~100KB, 2-4s delay, 50 req/s limit")
    print("  Error Simulation:")
    print("    GET /api/v1/flaky?page=N&fail_on=2,3          - Flaky endpoint (fails first attempt)")
    print("    GET /api/v1/errors?error_type=429|500|503     - Simulate specific errors")
    print("    GET /api/v1/rate-limited?requests_per_second=2 - Actual rate limiting")
    print("  Health:")
    print("    GET /health                                   - Health check")
    print("\nPatient records env vars:")
    print(f"  PATIENT_RECORDS_DELAY_MIN={PR_DELAY_MIN}  PATIENT_RECORDS_DELAY_MAX={PR_DELAY_MAX}")
    print(f"  PATIENT_RECORDS_PAGE_MIN={PR_PAGE_MIN}    PATIENT_RECORDS_PAGE_MAX={PR_PAGE_MAX}")
    print(f"  PATIENT_RECORDS_PAYLOAD_KB={PR_PAYLOAD_KB}")
    print(f"  PATIENT_RECORDS_RATE_LIMIT={PR_RATE_LIMIT}")
    uvicorn.run(app, host='0.0.0.0', port=port, log_level='info')
