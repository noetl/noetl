"""
NoETL System API Endpoints - FastAPI routes for system monitoring operations.

Provides REST endpoints for:
- System and process status monitoring
- Thread inspection
- Memory profiling with Memray
"""

from typing import List, Dict, Any
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from noetl.core.logger import setup_logger
from .schema import ThreadInfo, ReportResponse, StatusResponse
from .service import SystemService

logger = setup_logger(__name__, include_location=True)
router = APIRouter()


@router.get("/status", response_model=StatusResponse, summary="Get System and Process Status")
def get_server_status():
    """
    Get current system and process resource utilization.
    
    Returns comprehensive metrics including:
    - System: CPU, memory, network I/O
    - Process: CPU, memory, threads, disk I/O
    
    **Response**:
    ```json
    {
        "system": {
            "cpu_percent": 45.2,
            "memory_percent": 62.5,
            "net_io_sent_mb": 1024.5,
            "net_io_recv_mb": 2048.3
        },
        "process": {
            "pid": 12345,
            "cpu_percent": 15.3,
            "user_cpu_time": 45.2,
            "system_cpu_time": 12.1,
            "memory_rss_mb": 256.5,
            "memory_vms_mb": 512.0,
            "memory_shared_mb": 128.0,
            "num_threads": 8,
            "io_read_mb": 100.5,
            "io_write_mb": 50.2
        }
    }
    ```
    """
    try:
        return SystemService.get_system_status()
    except Exception as e:
        logger.exception(f"Error getting server status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/threads", response_model=List[ThreadInfo], summary="List Active Threads")
def get_thread_info():
    """
    Get information about all active threads in the process.
    
    Returns thread details including:
    - Thread ID and name
    - Alive status
    - Full stack trace for debugging
    
    **Response**:
    ```json
    [
        {
            "thread_id": 12345,
            "name": "MainThread",
            "is_alive": true,
            "stack_trace": [
                "  File \"/path/to/file.py\", line 42, in function_name\\n    code_line\\n"
            ]
        }
    ]
    ```
    """
    try:
        return SystemService.get_thread_info()
    except Exception as e:
        logger.exception(f"Error getting thread info: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profiler/memory/start", response_model=ReportResponse, summary="Start Memory Profiler")
def start_memory_profiling():
    """
    Start a memory profiling session using Memray.
    
    Creates a binary profiling file that can be analyzed with Memray tools.
    Only one profiling session can be active at a time.
    
    **Requirements**:
    - Memray must be installed: `pip install memray`
    
    **Response**:
    ```json
    {
        "status": "success",
        "message": "Memray profiling session started.",
        "file_path": "/tmp/noetl_dumps/memray-report-20251012_100000.bin"
    }
    ```
    
    **Errors**:
    - 503: Memray is not installed
    - 409: A profiling session is already in progress
    """
    try:
        return SystemService.start_memory_profiling()
    except ValueError as e:
        if "not installed" in str(e):
            raise HTTPException(status_code=503, detail=str(e))
        else:
            raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.exception(f"Error starting memory profiling: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/profiler/memory/stop", summary="Stop profiler and download .bin report")
def stop_and_download_memray_profile(background_tasks: BackgroundTasks):
    """
    Stop the active memory profiling session and download the report file.
    
    The report file is automatically deleted after download to save disk space.
    Analyze the .bin file using Memray CLI tools:
    - `memray flamegraph report.bin`
    - `memray table report.bin`
    - `memray stats report.bin`
    
    **Response**:
    - Binary file download (application/octet-stream)
    
    **Errors**:
    - 503: Memray is not installed
    - 404: No active profiling session to stop
    - 500: Report file not found
    """
    try:
        report_path, response = SystemService.stop_memory_profiling()
        
        # Schedule file cleanup after download
        background_tasks.add_task(SystemService.cleanup_file, report_path)
        
        return FileResponse(
            path=report_path,
            filename=report_path.name,
            media_type="application/octet-stream"
        )
    except ValueError as e:
        if "not installed" in str(e):
            raise HTTPException(status_code=503, detail=str(e))
        else:
            raise HTTPException(status_code=404, detail=str(e))
    except FileNotFoundError as e:
        raise HTTPException(status_code=500, detail=str(e))
    except Exception as e:
        logger.exception(f"Error stopping memory profiling: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/profiler/status", response_model=Dict[str, Any], summary="Get profiler status")
def get_profiler_status():
    """
    Get current memory profiler status.
    
    **Response**:
    ```json
    {
        "memray_available": true,
        "profiling_active": false,
        "file_path": null,
        "start_time": null
    }
    ```
    """
    try:
        return SystemService.get_profiling_status()
    except Exception as e:
        logger.exception(f"Error getting profiler status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ============================================================================
# Database Schema Management (for CLI: noetl db init/validate)
# ============================================================================

@router.post("/db/init", response_model=Dict[str, Any], summary="Initialize Database Schema")
async def init_database():
    """
    Initialize the NoETL database schema.
    
    Creates all required tables, indexes, and functions if they don't exist.
    Safe to run multiple times (uses IF NOT EXISTS).
    
    **Response**:
    ```json
    {
        "status": "ok",
        "message": "Database schema initialized successfully"
    }
    ```
    """
    try:
        result = await SystemService.init_database_schema()
        return result
    except Exception as e:
        logger.exception(f"Error initializing database schema: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/db/validate", response_model=Dict[str, Any], summary="Validate Database Schema")
async def validate_database():
    """
    Validate that the NoETL database schema is properly configured.
    
    Checks for required tables, columns, indexes, and functions.
    
    **Response**:
    ```json
    {
        "status": "ok",
        "valid": true,
        "tables": ["catalog", "credential", "event", "queue", "keychain"],
        "missing": []
    }
    ```
    """
    try:
        result = await SystemService.validate_database_schema()
        return result
    except Exception as e:
        logger.exception(f"Error validating database schema: {e}")
        raise HTTPException(status_code=500, detail=str(e))
