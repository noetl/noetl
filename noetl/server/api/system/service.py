"""
NoETL System API Service - Business logic for system monitoring operations.

Handles:
- System resource monitoring (CPU, memory, network)
- Process monitoring (CPU, memory, I/O, threads)
- Thread inspection
- Memory profiling with Memray
"""

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple

import psutil

from noetl.core.logger import setup_logger
from .schema import (
    SystemStatus,
    ProcessStatus,
    ThreadInfo,
    StatusResponse,
    ReportResponse
)

logger = setup_logger(__name__, include_location=True)

# Check Memray availability
try:
    import memray
    MEMRAY_AVAILABLE = True
except Exception:
    memray = None  # type: ignore
    MEMRAY_AVAILABLE = False

# Global state for memory profiling
MEMRAY_TRACKER: Any = None
MEMRAY_FILE_PATH: Optional[Path] = None
PROFILING_START_TIME: Optional[datetime] = None


class SystemService:
    """Service for system and process monitoring."""
    
    # Process instance
    _process = psutil.Process()
    
    @staticmethod
    def get_system_status() -> StatusResponse:
        """
        Get current system and process status.
        
        Returns:
            StatusResponse with system and process metrics
        """
        # Get process metrics
        with SystemService._process.oneshot():
            cpu_times = SystemService._process.cpu_times()
            mem_info = SystemService._process.memory_info()
            io_counters = SystemService._process.io_counters()
            
            process_status = ProcessStatus(
                pid=SystemService._process.pid,
                cpu_percent=SystemService._process.cpu_percent(interval=0.1),
                user_cpu_time=cpu_times.user,
                system_cpu_time=cpu_times.system,
                memory_rss_mb=mem_info.rss / (1024 * 1024),
                memory_vms_mb=mem_info.vms / (1024 * 1024),
                memory_shared_mb=mem_info.shared / (1024 * 1024),
                num_threads=SystemService._process.num_threads(),
                io_read_mb=io_counters.read_bytes / (1024 * 1024),
                io_write_mb=io_counters.write_bytes / (1024 * 1024),
            )
        
        # Get system metrics
        virtual_mem = psutil.virtual_memory()
        net_io = psutil.net_io_counters()
        
        system_status = SystemStatus(
            cpu_percent=psutil.cpu_percent(interval=None),
            memory_percent=virtual_mem.percent,
            net_io_sent_mb=net_io.bytes_sent / (1024 * 1024),
            net_io_recv_mb=net_io.bytes_recv / (1024 * 1024),
        )
        
        return StatusResponse(
            system=system_status,
            process=process_status
        )
    
    @staticmethod
    def get_thread_info() -> List[ThreadInfo]:
        """
        Get information about all active threads.
        
        Returns:
            List of ThreadInfo with thread details and stack traces
        """
        threads_info = []
        thread_id_map = {t.ident: t for t in threading.enumerate()}
        
        for thread_id, frame in sys._current_frames().items():
            thread = thread_id_map.get(thread_id)
            stack = traceback.format_stack(frame)
            
            threads_info.append(
                ThreadInfo(
                    thread_id=thread_id,
                    name=thread.name if thread else "Unknown",
                    is_alive=thread.is_alive() if thread else False,
                    stack_trace=stack
                )
            )
        
        return threads_info
    
    @staticmethod
    def start_memory_profiling() -> ReportResponse:
        """
        Start memory profiling session with Memray.
        
        Returns:
            ReportResponse with profiling session info
            
        Raises:
            ValueError: If Memray is not available or session already running
        """
        global MEMRAY_TRACKER, MEMRAY_FILE_PATH, PROFILING_START_TIME
        
        if not MEMRAY_AVAILABLE:
            raise ValueError("Memray is not installed. Install it to use memory profiler.")
        
        if MEMRAY_TRACKER:
            raise ValueError("A profiling session is already in progress.")
        
        # Create dump directory
        dump_dir = Path("/tmp/noetl_dumps")
        dump_dir.mkdir(exist_ok=True)
        
        # Generate file path
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = dump_dir / f"memray-report-{timestamp}.bin"
        
        MEMRAY_FILE_PATH = file_path
        PROFILING_START_TIME = datetime.now()
        
        # Start tracker
        MEMRAY_TRACKER = memray.Tracker(
            destination=memray.FileDestination(path=str(file_path), overwrite=True)
        )
        MEMRAY_TRACKER.__enter__()
        
        return ReportResponse(
            status="success",
            message="Memray profiling session started.",
            file_path=str(file_path)
        )
    
    @staticmethod
    def stop_memory_profiling() -> Tuple[Path, ReportResponse]:
        """
        Stop memory profiling session.
        
        Returns:
            Tuple of (report_path, ReportResponse)
            
        Raises:
            ValueError: If Memray is not available or no active session
            FileNotFoundError: If report file not found
        """
        global MEMRAY_TRACKER, MEMRAY_FILE_PATH, PROFILING_START_TIME
        
        if not MEMRAY_AVAILABLE:
            raise ValueError("Memray is not installed. Install it to use memory profiler.")
        
        if not MEMRAY_TRACKER or not MEMRAY_FILE_PATH:
            raise ValueError("No active profiling session to stop.")
        
        report_path = MEMRAY_FILE_PATH
        
        # Stop tracker
        MEMRAY_TRACKER.__exit__(None, None, None)
        MEMRAY_TRACKER = None
        MEMRAY_FILE_PATH = None
        PROFILING_START_TIME = None
        
        if not report_path.exists():
            raise FileNotFoundError("Memray .bin file not found.")
        
        response = ReportResponse(
            status="success",
            message="Memray profiling session stopped.",
            file_path=str(report_path)
        )
        
        return report_path, response
    
    @staticmethod
    def cleanup_file(path: Path):
        """
        Clean up a file (used in background tasks).
        
        Args:
            path: Path to file to delete
        """
        try:
            path.unlink()
            logger.debug(f"Deleted file: {path}")
        except Exception as e:
            logger.error(f"Failed to delete file {path}: {e}")
    
    @staticmethod
    def is_memray_available() -> bool:
        """Check if Memray is available."""
        return MEMRAY_AVAILABLE
    
    @staticmethod
    def get_profiling_status() -> Dict[str, Any]:
        """
        Get current profiling session status.
        
        Returns:
            Dictionary with profiling status information
        """
        return {
            "memray_available": MEMRAY_AVAILABLE,
            "profiling_active": MEMRAY_TRACKER is not None,
            "file_path": str(MEMRAY_FILE_PATH) if MEMRAY_FILE_PATH else None,
            "start_time": PROFILING_START_TIME.isoformat() if PROFILING_START_TIME else None
        }

    @staticmethod
    async def init_database_schema() -> Dict[str, Any]:
        """
        Verify database connectivity and schema readiness.
        
        Pure event sourcing - we don't modify schema, just validate it exists.
        Schema is managed externally (k8s init, migrations, etc).
        
        Returns:
            Dictionary with validation status
        """
        from noetl.core.db.pool import get_pool_connection
        from psycopg.rows import dict_row
        
        # Pure event sourcing: event table is the single source of truth
        # runtime table stores server and worker pool registrations
        required_tables = ["catalog", "credential", "event", "keychain", "runtime"]
        
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'noetl' 
                    AND table_type = 'BASE TABLE'
                """)
                rows = await cur.fetchall()
                existing_tables = {row['table_name'] for row in rows}
        
        found = [t for t in required_tables if t in existing_tables]
        missing = [t for t in required_tables if t not in existing_tables]
        
        if missing:
            logger.warning(f"Missing tables: {missing}. Run schema DDL manually.")
            return {
                "status": "warning",
                "message": f"Schema exists but missing tables: {missing}",
                "tables": found,
                "missing": missing
            }
        
        logger.info("Database schema validated successfully")
        return {
            "status": "ok",
            "message": "Database schema ready",
            "tables": found
        }

    @staticmethod
    async def validate_database_schema() -> Dict[str, Any]:
        """
        Validate that all required NoETL tables exist.
        
        Returns:
            Dictionary with validation results
        """
        from noetl.core.db.pool import get_pool_connection
        from psycopg.rows import dict_row
        
        # Pure event sourcing: event table is the single source of truth
        # runtime table stores server and worker pool registrations
        required_tables = ["catalog", "credential", "event", "keychain", "runtime"]
        
        async with get_pool_connection() as conn:
            async with conn.cursor(row_factory=dict_row) as cur:
                await cur.execute("""
                    SELECT table_name 
                    FROM information_schema.tables 
                    WHERE table_schema = 'noetl' 
                    AND table_type = 'BASE TABLE'
                """)
                rows = await cur.fetchall()
                existing_tables = {row['table_name'] for row in rows}
        
        found = [t for t in required_tables if t in existing_tables]
        missing = [t for t in required_tables if t not in existing_tables]
        
        valid = len(missing) == 0
        
        return {
            "status": "ok" if valid else "error",
            "valid": valid,
            "tables": found,
            "missing": missing,
            "all_tables": list(existing_tables)
        }
