"""
VictoriaLogs HTTP Handler for Python logging.

This module provides a custom logging handler that streams logs directly to VictoriaLogs
using its JSON line insert API with batching, retry logic, and async processing.
"""

import json
import logging
import queue
import threading
import time
from datetime import datetime
from typing import Any, Dict, Optional
import socket
import os

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False
    requests = None


class VictoriaLogsHandler(logging.Handler):
    """
    A logging handler that streams logs to VictoriaLogs via HTTP.
    
    Features:
    - Batching: Accumulates logs and sends them in batches
    - Async sending: Uses a background thread to avoid blocking main thread
    - Retry logic: Retries failed requests with exponential backoff
    - Graceful degradation: Falls back to stderr if VictoriaLogs is unavailable
    
    Args:
        url: VictoriaLogs endpoint (default: http://localhost:9428)
        batch_size: Number of logs to batch before sending (default: 10)
        flush_interval: Maximum seconds to wait before flushing batch (default: 5.0)
        max_queue_size: Maximum logs to queue before dropping (default: 10000)
        retry_attempts: Number of retry attempts for failed sends (default: 3)
        source: Source identifier for logs (default: hostname)
        extra_fields: Additional fields to add to all log entries
        fallback_to_stderr: Log to stderr if VictoriaLogs unavailable (default: True)
    """
    
    def __init__(
        self,
        url: str = "http://localhost:9428",
        batch_size: int = 10,
        flush_interval: float = 5.0,
        max_queue_size: int = 10000,
        retry_attempts: int = 3,
        source: Optional[str] = None,
        extra_fields: Optional[Dict[str, Any]] = None,
        fallback_to_stderr: bool = True,
    ):
        super().__init__()
        
        if not HAS_REQUESTS:
            raise ImportError("requests library required for VictoriaLogsHandler. Install with: pip install requests")
        
        self.url = f"{url.rstrip('/')}/insert/jsonline"
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.max_queue_size = max_queue_size
        self.retry_attempts = retry_attempts
        self.source = source or socket.gethostname()
        self.extra_fields = extra_fields or {}
        self.fallback_to_stderr = fallback_to_stderr
        
        # Queue for batching logs
        self._queue = queue.Queue(maxsize=max_queue_size)
        self._batch = []
        self._last_flush = time.time()
        self._lock = threading.Lock()
        self._stopped = False
        
        # Background thread for async sending
        self._worker_thread = threading.Thread(target=self._worker, daemon=True)
        self._worker_thread.start()
        
        # Stats
        self.logs_sent = 0
        self.logs_dropped = 0
        self.send_failures = 0
    
    def emit(self, record: logging.LogRecord) -> None:
        """
        Emit a log record by adding it to the queue.
        """
        try:
            # Format the log record
            log_entry = self._format_log_entry(record)
            
            # Try to add to queue (non-blocking)
            try:
                self._queue.put_nowait(log_entry)
            except queue.Full:
                self.logs_dropped += 1
                if self.fallback_to_stderr:
                    print(f"VictoriaLogs queue full, dropped log: {record.getMessage()}", file=os.sys.stderr)
        except Exception as e:
            self.handleError(record)
    
    def _format_log_entry(self, record: logging.LogRecord) -> Dict[str, Any]:
        """
        Format a log record into a VictoriaLogs JSON entry.
        """
        # Get timestamp in milliseconds
        timestamp = int(record.created * 1000)
        
        # Format the message
        message = self.format(record)
        
        # Build log entry
        log_entry = {
            "_time": timestamp,
            "_msg": message,
            "source": self.source,
            "level": record.levelname,
            "logger": record.name,
            "thread": record.threadName,
            "process": record.process,
            "pathname": record.pathname,
            "lineno": record.lineno,
            "funcName": record.funcName,
        }
        
        # Add scope if present
        if hasattr(record, "scope"):
            log_entry["scope"] = record.scope
        
        # Add exception info if present
        if record.exc_info:
            log_entry["exception"] = self.formatter.formatException(record.exc_info) if self.formatter else str(record.exc_info)
        
        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in [
                "msg", "args", "levelname", "levelno", "pathname",
                "filename", "module", "exc_info", "exc_text", "stack_info",
                "lineno", "funcName", "created", "msecs", "relativeCreated",
                "thread", "threadName", "process", "processName", "name",
                "scope", "getMessage", "message"
            ]:
                log_entry[key] = self._serialize_value(value)
        
        # Add configured extra fields
        log_entry.update(self.extra_fields)
        
        return log_entry
    
    def _serialize_value(self, value: Any) -> Any:
        """
        Serialize a value for JSON encoding.
        """
        if isinstance(value, (str, int, float, bool, type(None))):
            return value
        elif isinstance(value, (list, tuple)):
            return [self._serialize_value(v) for v in value]
        elif isinstance(value, dict):
            return {k: self._serialize_value(v) for k, v in value.items()}
        elif isinstance(value, datetime):
            return value.isoformat()
        else:
            return str(value)
    
    def _worker(self) -> None:
        """
        Background worker that batches and sends logs to VictoriaLogs.
        """
        while not self._stopped:
            try:
                # Try to get a log entry with timeout
                try:
                    log_entry = self._queue.get(timeout=0.1)
                    with self._lock:
                        self._batch.append(log_entry)
                except queue.Empty:
                    pass
                
                # Check if we should flush the batch
                with self._lock:
                    should_flush = (
                        len(self._batch) >= self.batch_size or
                        (len(self._batch) > 0 and time.time() - self._last_flush >= self.flush_interval)
                    )
                    
                    if should_flush:
                        batch_to_send = self._batch[:]
                        self._batch = []
                        self._last_flush = time.time()
                    else:
                        batch_to_send = None
                
                # Send batch if needed
                if batch_to_send:
                    self._send_batch(batch_to_send)
            
            except Exception as e:
                # Don't let worker thread crash
                if self.fallback_to_stderr:
                    print(f"VictoriaLogs worker error: {e}", file=os.sys.stderr)
    
    def _send_batch(self, batch: list) -> None:
        """
        Send a batch of logs to VictoriaLogs with retry logic.
        """
        if not batch:
            return
        
        # Convert batch to JSON lines format
        data = "\n".join(json.dumps(entry) for entry in batch) + "\n"
        
        headers = {
            'Content-Type': 'application/stream+json'
        }
        
        # Retry logic with exponential backoff
        for attempt in range(self.retry_attempts):
            try:
                response = requests.post(
                    self.url,
                    headers=headers,
                    data=data,
                    timeout=5.0
                )
                response.raise_for_status()
                
                # Success!
                self.logs_sent += len(batch)
                return
            
            except requests.exceptions.RequestException as e:
                if attempt == self.retry_attempts - 1:
                    # Final attempt failed
                    self.send_failures += 1
                    if self.fallback_to_stderr:
                        print(f"VictoriaLogs send failed after {self.retry_attempts} attempts: {e}", file=os.sys.stderr)
                        print(f"Failed to send {len(batch)} log entries", file=os.sys.stderr)
                else:
                    # Wait before retry (exponential backoff)
                    time.sleep(0.1 * (2 ** attempt))
    
    def flush(self) -> None:
        """
        Flush any pending logs immediately.
        """
        with self._lock:
            if self._batch:
                batch_to_send = self._batch[:]
                self._batch = []
                self._last_flush = time.time()
                self._send_batch(batch_to_send)
    
    def close(self) -> None:
        """
        Close the handler and flush any pending logs.
        """
        self._stopped = True
        self.flush()
        
        # Wait for worker thread to finish (with timeout)
        if self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5.0)
        
        super().close()
    
    def get_stats(self) -> Dict[str, int]:
        """
        Get handler statistics.
        """
        return {
            "logs_sent": self.logs_sent,
            "logs_dropped": self.logs_dropped,
            "send_failures": self.send_failures,
            "queue_size": self._queue.qsize(),
            "batch_size": len(self._batch),
        }


# Convenience function to add VictoriaLogs handler to a logger
def add_victorialogs_handler(
    logger: logging.Logger,
    url: str = "http://localhost:9428",
    batch_size: int = 10,
    flush_interval: float = 5.0,
    level: int = logging.DEBUG,
    formatter: Optional[logging.Formatter] = None,
    **kwargs
) -> VictoriaLogsHandler:
    """
    Add a VictoriaLogs handler to a logger.
    
    Args:
        logger: Logger to add handler to
        url: VictoriaLogs endpoint
        batch_size: Batch size for sending logs
        flush_interval: Flush interval in seconds
        level: Minimum log level to send
        formatter: Optional custom formatter
        **kwargs: Additional arguments for VictoriaLogsHandler
    
    Returns:
        The created VictoriaLogsHandler instance
    """
    handler = VictoriaLogsHandler(
        url=url,
        batch_size=batch_size,
        flush_interval=flush_interval,
        **kwargs
    )
    handler.setLevel(level)
    
    if formatter:
        handler.setFormatter(formatter)
    
    logger.addHandler(handler)
    return handler
