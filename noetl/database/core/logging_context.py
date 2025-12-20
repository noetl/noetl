import logging
import contextvars
from contextlib import contextmanager

# Context variable for extra log parameters
log_context = contextvars.ContextVar("log_context", default={})

# Custom filter to inject context into log records
class ContextFilter(logging.Filter):
    def filter(self, record):
        context = log_context.get()
        for key, value in context.items():
            setattr(record, key, value)
        return True

# Context manager for temporarily setting log context
@contextmanager
def LoggingContext(logger: logging.Logger, **kwargs):
    """
    Context manager to add extra context to log records.
    example:
        with LoggingContext(logger, execution_id="1234", some_other="value"):
            logger.info("This log will have execution_id in its context")
    """
    current = log_context.get().copy()
    current.update(kwargs)
    token = log_context.set(current)
    try:
        yield
    finally:
        log_context.reset(token)
