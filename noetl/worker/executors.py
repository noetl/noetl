from __future__ import annotations

from concurrent.futures import ProcessPoolExecutor
from typing import Optional

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def create_process_pool_executor(
    max_workers: Optional[int] = None,
) -> Optional[ProcessPoolExecutor]:
    """Attempt to create a process pool, falling back to None when unsupported."""
    try:
        return ProcessPoolExecutor(max_workers=max_workers)
    except (PermissionError, NotImplementedError, OSError) as exc:
        logger.warning("Process pool executor unavailable: %s", exc)
        return None
