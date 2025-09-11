"""
Server orchestration services (skeleton).
Composes core runtime, storage, messaging and plugins.
"""

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)

