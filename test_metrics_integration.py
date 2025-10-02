#!/usr/bin/env python3
"""
Test script to verify metrics collection and reporting functionality.
"""

import asyncio
import json
import httpx
import time
import os
from typing import Dict, Any

async def test_worker_metrics():
    """Test worker metrics collection and reporting."""
    print("Testing worker metrics collection...")
    
    try:
        # Import worker and create instance
        from noetl.worker.worker import ScalableQueueWorkerPool
        
        # Set environment variables for testing
        os.environ["NOETL_WORKER_POOL_NAME"] = "test-worker"
        os.environ["NOETL_SERVER_URL"] = "http://localhost:8082"
        os.environ["NOETL_WORKER_METRICS_INTERVAL"] = "10"  # Short interval for testing
        
        # Create worker pool
        worker_pool = ScalableQueueWorkerPool(
            server_url="http://localhost:8082/api",
            max_workers=2,
            check_interval=5.0,
            worker_poll_interval=1.0
        )
        
        # Test metrics collection method
        await worker_pool._report_worker_metrics("test-worker")
        print("✓ Worker metrics collection successful")
        
    except Exception as e:
        print(f"✗ Worker metrics test failed: {e}")

async def test_server_metrics_api():
    """Test server metrics API endpoints."""
    print("Testing server metrics API...")
    
    server_url = "http://localhost:8082"
    
    try:
        async with httpx.AsyncClient() as client:
            # Test self-report endpoint
            print("Testing self-report endpoint...")
            resp = await client.post(f"{server_url}/api/metrics/self-report")
            if resp.status_code == 200:
                print("✓ Self-report endpoint working")
            else:
                print(f"✗ Self-report failed: {resp.status_code} - {resp.text}")
            
            # Test manual metrics report
            print("Testing metrics report endpoint...")
            test_payload = {
                "component_name": "test-component",
                "component_type": "test",
                "metrics": [
                    {
                        "metric_name": "test_metric",
                        "metric_type": "gauge",
                        "metric_value": 42.0,
                        "timestamp": "2024-01-01T12:00:00Z",
                        "labels": {"test": "true"},
                        "help_text": "Test metric",
                        "unit": "count"
                    }
                ]
            }
            
            resp = await client.post(f"{server_url}/api/metrics/report", json=test_payload)
            if resp.status_code == 200:
                result = resp.json()
                print(f"✓ Metrics report successful: {result}")
            else:
                print(f"✗ Metrics report failed: {resp.status_code} - {resp.text}")
            
            # Test query endpoint
            print("Testing metrics query endpoint...")
            resp = await client.get(f"{server_url}/api/metrics/query?component_name=test-component")
            if resp.status_code == 200:
                result = resp.json()
                print(f"✓ Metrics query successful: found {len(result.get('metrics', []))} metrics")
            else:
                print(f"✗ Metrics query failed: {resp.status_code} - {resp.text}")
            
            # Test Prometheus endpoint
            print("Testing Prometheus metrics endpoint...")
            resp = await client.get(f"{server_url}/api/metrics/prometheus")
            if resp.status_code == 200:
                prometheus_text = resp.text
                print(f"✓ Prometheus endpoint working: {len(prometheus_text.splitlines())} lines")
                print("Sample Prometheus output:")
                print(prometheus_text[:500] + "..." if len(prometheus_text) > 500 else prometheus_text)
            else:
                print(f"✗ Prometheus endpoint failed: {resp.status_code} - {resp.text}")
                
    except Exception as e:
        print(f"✗ Server metrics API test failed: {e}")

async def test_database_schema():
    """Test that metric table exists and is accessible."""
    print("Testing database schema...")
    
    try:
        from noetl.core.common import get_async_db_connection
        
        async with get_async_db_connection() as conn:
            async with conn.cursor() as cur:
                # Check if metric table exists
                await cur.execute("""
                    SELECT COUNT(*) FROM information_schema.tables 
                    WHERE table_schema = 'noetl' AND table_name = 'metric'
                """)
                result = await cur.fetchone()
                
                if result and result[0] > 0:
                    print("✓ Metric table exists")
                    
                    # Check table structure
                    await cur.execute("""
                        SELECT column_name, data_type 
                        FROM information_schema.columns 
                        WHERE table_schema = 'noetl' AND table_name = 'metric'
                        ORDER BY ordinal_position
                    """)
                    columns = await cur.fetchall()
                    print(f"✓ Metric table has {len(columns)} columns:")
                    for col_name, col_type in columns:
                        print(f"  - {col_name}: {col_type}")
                        
                    # Check if we can insert and retrieve a test metric
                    await cur.execute("""
                        SELECT COUNT(*) FROM noetl.metric 
                        WHERE metric_name = 'test_integration_metric'
                    """)
                    result = await cur.fetchone()
                    existing_count = result[0] if result else 0
                    print(f"✓ Can query metric table: found {existing_count} test metrics")
                    
                else:
                    print("✗ Metric table does not exist")
                    
    except Exception as e:
        print(f"✗ Database schema test failed: {e}")

async def main():
    """Run all tests."""
    print("=== NoETL Metrics Integration Test ===\n")
    
    await test_database_schema()
    print()
    
    await test_server_metrics_api()
    print()
    
    await test_worker_metrics()
    print()
    
    print("=== Test Complete ===")

if __name__ == "__main__":
    asyncio.run(main())