#!/usr/bin/env python3
"""
Demo script showing how to use the VictoriaLogsHandler for streaming logs.

This demonstrates:
- Basic usage with default settings
- Custom configuration options
- Multiple loggers with different handlers
- Performance and statistics
"""

import logging
import time
from noetl.core.victorialogs_handler import VictoriaLogsHandler, add_victorialogs_handler
from noetl.core.logging_context import LoggingContext


def demo_basic_usage():
    """Basic usage example."""
    print("\n=== Basic Usage Demo ===\n")
    
    # Create logger
    logger = logging.getLogger("demo.basic")
    logger.setLevel(logging.DEBUG)
    
    # Add VictoriaLogs handler with default settings
    handler = add_victorialogs_handler(
        logger,
        url="http://localhost:9428",
        batch_size=5,  # Small batch for demo
        flush_interval=2.0,  # Quick flush for demo
    )
    
    # Log some messages
    logger.info("Application started")
    logger.debug("Debug information", extra={"user_id": 123, "action": "login"})
    logger.warning("Low disk space", extra={"disk": "/dev/sda1", "free_gb": 5})
    logger.error("Failed to connect to database", extra={"host": "db.example.com", "port": 5432})
    
    # Wait for flush
    time.sleep(2.5)
    
    # Check stats
    stats = handler.get_stats()
    print(f"Stats: {stats}")
    
    # Clean up
    handler.close()


def demo_with_context():
    """Demo with logging context."""
    print("\n=== Logging Context Demo ===\n")
    
    logger = logging.getLogger("demo.context")
    logger.setLevel(logging.DEBUG)
    
    # Add VictoriaLogs handler
    handler = add_victorialogs_handler(
        logger,
        url="http://localhost:9428",
        batch_size=3,
        flush_interval=1.0,
        extra_fields={
            "environment": "production",
            "service": "noetl-demo"
        }
    )
    
    # Use context for structured logging
    with LoggingContext(logger, request_id="req-123", user="john@example.com"):
        logger.info("Processing request")
        
        with LoggingContext(logger, operation="data_fetch"):
            logger.debug("Fetching data from source")
            time.sleep(0.5)
            logger.info("Data fetched successfully", extra={"rows": 1000})
        
        logger.info("Request completed")
    
    time.sleep(1.5)
    print(f"Stats: {handler.get_stats()}")
    handler.close()


def demo_exception_logging():
    """Demo exception logging."""
    print("\n=== Exception Logging Demo ===\n")
    
    logger = logging.getLogger("demo.exceptions")
    logger.setLevel(logging.DEBUG)
    
    handler = add_victorialogs_handler(
        logger,
        url="http://localhost:9428",
        batch_size=1,  # Send immediately
    )
    
    try:
        # Simulate an error
        result = 10 / 0
    except Exception as e:
        logger.exception("Division by zero error", extra={
            "operation": "calculate",
            "input_a": 10,
            "input_b": 0
        })
    
    time.sleep(1.0)
    print(f"Stats: {handler.get_stats()}")
    handler.close()


def demo_high_volume():
    """Demo high volume logging."""
    print("\n=== High Volume Demo ===\n")
    
    logger = logging.getLogger("demo.volume")
    logger.setLevel(logging.INFO)
    
    handler = add_victorialogs_handler(
        logger,
        url="http://localhost:9428",
        batch_size=50,  # Larger batch for performance
        flush_interval=5.0,
        max_queue_size=10000,
    )
    
    # Log many messages quickly
    start_time = time.time()
    num_logs = 500
    
    for i in range(num_logs):
        logger.info(f"Processing item {i}", extra={
            "item_id": i,
            "batch": i // 100,
            "status": "processed"
        })
    
    # Force flush
    handler.flush()
    
    elapsed = time.time() - start_time
    print(f"Logged {num_logs} messages in {elapsed:.2f} seconds")
    print(f"Rate: {num_logs/elapsed:.0f} logs/sec")
    print(f"Stats: {handler.get_stats()}")
    
    handler.close()


def demo_multiple_handlers():
    """Demo using multiple handlers (console + VictoriaLogs)."""
    print("\n=== Multiple Handlers Demo ===\n")
    
    logger = logging.getLogger("demo.multi")
    logger.setLevel(logging.DEBUG)
    
    # Add console handler
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter(
        '%(asctime)s [%(levelname)s] %(name)s: %(message)s'
    ))
    logger.addHandler(console_handler)
    
    # Add VictoriaLogs handler
    vl_handler = add_victorialogs_handler(
        logger,
        url="http://localhost:9428",
        batch_size=5,
        flush_interval=2.0,
    )
    
    # Logs will go to both console and VictoriaLogs
    logger.info("This log goes to both console and VictoriaLogs")
    logger.warning("Warning message visible in both places")
    
    time.sleep(2.5)
    print(f"\nVictoriaLogs Stats: {vl_handler.get_stats()}")
    
    vl_handler.close()


def demo_custom_formatter():
    """Demo with custom formatter."""
    print("\n=== Custom Formatter Demo ===\n")
    
    logger = logging.getLogger("demo.formatter")
    logger.setLevel(logging.DEBUG)
    
    # Create custom formatter
    formatter = logging.Formatter(
        '%(levelname)s | %(name)s | %(message)s'
    )
    
    handler = add_victorialogs_handler(
        logger,
        url="http://localhost:9428",
        batch_size=3,
        flush_interval=1.0,
        formatter=formatter,
        extra_fields={
            "app": "noetl",
            "version": "1.0.0"
        }
    )
    
    logger.info("Formatted log message")
    logger.debug("Debug with custom format")
    
    time.sleep(1.5)
    print(f"Stats: {handler.get_stats()}")
    handler.close()


if __name__ == "__main__":
    print("=" * 60)
    print("VictoriaLogsHandler Demo")
    print("=" * 60)
    print("\nMake sure VictoriaLogs is running at http://localhost:9428")
    print("You can start it with: docker run -p 9428:9428 victoriametrics/victoria-logs:latest")
    
    try:
        demo_basic_usage()
        demo_with_context()
        demo_exception_logging()
        demo_high_volume()
        demo_multiple_handlers()
        demo_custom_formatter()
        
        print("\n" + "=" * 60)
        print("All demos completed successfully!")
        print("=" * 60)
        
    except Exception as e:
        print(f"\nError running demo: {e}")
        print("Make sure VictoriaLogs is accessible at http://localhost:9428")
