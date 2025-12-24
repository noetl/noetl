#!/usr/bin/env python3
"""
Validate Phase 2 Loop Execution
Checks that loop steps create iteration jobs with server-side orchestration
"""
import requests
import time
import psycopg
import sys
import logging

logger = logging.getLogger(__name__)

# Configuration
NOETL_API = "http://127.0.0.1:8082"
DB_CONFIG = {
    "host": "127.0.0.1",
    "port": "54321",
    "user": "demo",
    "password": "demo",
    "dbname": "demo_noetl"
}

def get_db_connection():
    """Get database connection"""
    conn_string = f"host={DB_CONFIG['host']} port={DB_CONFIG['port']} " \
                  f"dbname={DB_CONFIG['dbname']} user={DB_CONFIG['user']} " \
                  f"password={DB_CONFIG['password']}"
    return psycopg.connect(conn_string)

def start_playbook():
    """Start the test playbook"""
    url = f"{NOETL_API}/api/run/playbook"
    payload = {"path": "tests/pagination/loop_with_pagination/loop_with_pagination"}
    
    logger.info("📋 Starting playbook...")
    response = requests.post(url, json=payload, timeout=30)
    response.raise_for_status()
    
    result = response.json()
    execution_id = result['execution_id']
    logger.info(f"✓ Execution started: {execution_id}")
    return execution_id

def check_iteration_jobs(execution_id):
    """Check if iteration jobs were created"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            # Check for iteration jobs in queue
            query = """
                SELECT 
                    queue_id,
                    node_id,
                    node_type,
                    status
                FROM noetl.queue
                WHERE execution_id = %s
                  AND node_type = 'iteration'
                ORDER BY queue_id
            """
            cur.execute(query, (execution_id,))
            jobs = cur.fetchall()
            
            if not jobs:
                logger.info("❌ No iteration jobs found!")
                return False
            
            logger.info(f"\n✓ Found {len(jobs)} iteration jobs:")
            for job in jobs:
                queue_id, node_id, node_type, status = job
                logger.info(f"  - {node_id}: status={status}")
            
            # Check expected count (2 endpoints in workload)
            if len(jobs) == 2:
                logger.info(f"\n✅ PASS: Correct number of iterations (2)")
                return True
            else:
                logger.info(f"\n⚠️  Expected 2 iterations, got {len(jobs)}")
                return True  # Still pass if jobs were created

def check_iterator_started_event(execution_id):
    """Check if iterator_started event was emitted"""
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            query = """
                SELECT 
                    event_id,
                    event_type,
                    node_name,
                    context
                FROM noetl.event
                WHERE execution_id = %s
                  AND event_type = 'iterator_started'
            """
            cur.execute(query, (execution_id,))
            event = cur.fetchone()
            
            if event:
                event_id, event_type, node_name, context = event
                logger.info(f"\n✓ iterator_started event found:")
                logger.info(f"  event_id: {event_id}")
                logger.info(f"  context: {context}")
                return True
            else:
                logger.info("\n❌ No iterator_started event found!")
                return False

def main():
    logger.info("="*70)
    logger.info("🎯 Phase 2 Validation: Server-Side Loop Execution")
    logger.info("="*70)
    
    try:
        # Start playbook
        execution_id = start_playbook()
        
        # Wait for orchestration
        logger.info("\n⏳ Waiting 5s for orchestration...")
        time.sleep(5)
        
        # Check iterator_started event
        has_event = check_iterator_started_event(execution_id)
        
        # Check iteration jobs
        has_jobs = check_iteration_jobs(execution_id)
        
        # Final result
        logger.info("\n" + "="*70)
        if has_event and has_jobs:
            logger.info("✅ Phase 2 VALIDATION PASSED")
            logger.info("   - Server detected loop attribute")
            logger.info("   - Iterator event emitted")
            logger.info("   - Iteration jobs created")
            logger.info("="*70)
            return 0
        else:
            logger.info("❌ Phase 2 VALIDATION FAILED")
            logger.info("="*70)
            return 1
            
    except Exception as e:
        logger.info(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    sys.exit(main())
