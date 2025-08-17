import psutil
import threading
import traceback
import sys
try:
    import memray
    MEMRAY_AVAILABLE = True
except Exception:
    memray = None
    MEMRAY_AVAILABLE = False
from fastapi import APIRouter, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from datetime import datetime
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from noetl.logger import setup_logger

logger = setup_logger(__name__)

router = APIRouter()
process = psutil.Process()

MEMRAY_TRACKER: Optional[object] = None
MEMRAY_FILE_PATH: Optional[Path] = None
PROFILING_START_TIME: Optional[datetime] = None


class SystemStatus(BaseModel):
    cpu_percent: float = Field(..., description="System-wide CPU utilization percentage.")
    memory_percent: float = Field(..., description="System-wide memory utilization percentage.")
    net_io_sent_mb: float = Field(..., description="Total bytes sent over the network (MB).")
    net_io_recv_mb: float = Field(..., description="Total bytes received over the network (MB).")

class ProcessStatus(BaseModel):
    pid: int
    cpu_percent: float
    user_cpu_time: float
    system_cpu_time: float
    memory_rss_mb: float
    memory_vms_mb: float
    memory_shared_mb: float
    num_threads: int
    io_read_mb: float
    io_write_mb: float

class ThreadInfo(BaseModel):
    thread_id: int
    name: str
    is_alive: bool
    stack_trace: List[str]

class ReportResponse(BaseModel):
    status: str
    message: str
    file_path: str | None = None


@router.get("/status", response_model=Dict[str, Any], summary="Get System and Process Status")
def get_server_status():
    with process.oneshot():
        cpu_times = process.cpu_times()
        mem_info = process.memory_info()
        io_counters = process.io_counters()
        net_io = psutil.net_io_counters()

        process_status = ProcessStatus(
            pid=process.pid,
            cpu_percent=process.cpu_percent(interval=0.1),
            user_cpu_time=cpu_times.user,
            system_cpu_time=cpu_times.system,
            memory_rss_mb=mem_info.rss / (1024 * 1024),
            memory_vms_mb=mem_info.vms / (1024 * 1024),
            memory_shared_mb=mem_info.shared / (1024 * 1024),
            num_threads=process.num_threads(),
            io_read_mb=io_counters.read_bytes / (1024 * 1024),
            io_write_mb=io_counters.write_bytes / (1024 * 1024),
        )

    virtual_mem = psutil.virtual_memory()
    system_status = SystemStatus(
        cpu_percent=psutil.cpu_percent(interval=None),
        memory_percent=virtual_mem.percent,
        net_io_sent_mb=net_io.bytes_sent / (1024 * 1024),
        net_io_recv_mb=net_io.bytes_recv / (1024 * 1024),
    )
    return {"system": system_status, "process": process_status}


@router.get("/threads", response_model=List[ThreadInfo], summary="List Active Threads")
def get_thread_info():
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


@router.post("/profiler/memory/start", response_model=ReportResponse, summary="Start Memory Profiler")
def start_memory_profiling():
    global MEMRAY_TRACKER, MEMRAY_FILE_PATH, PROFILING_START_TIME
    if not MEMRAY_AVAILABLE:
        raise HTTPException(status_code=501, detail="Memray is not installed on this server.")

    if MEMRAY_TRACKER:
        raise HTTPException(status_code=409, detail="A profiling session is already in progress.")

    dump_dir = Path("/tmp/noetl_dumps")
    dump_dir.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    file_path = dump_dir / f"memray-report-{timestamp}.bin"

    MEMRAY_FILE_PATH = file_path
    PROFILING_START_TIME = datetime.now()

    MEMRAY_TRACKER = memray.Tracker(destination=memray.FileDestination(path=str(file_path), overwrite=True))
    MEMRAY_TRACKER.__enter__()

    return ReportResponse(
        status="success",
        message="Memray profiling session started.",
        file_path=str(file_path)
    )


def cleanup_file(path: Path):
    try:
        path.unlink()
    except Exception as e:
        logger.error(f"Failed to delete memray file: {e}")

@router.post("/profiler/memory/stop", summary="Stop profiler and download .bin report")
def stop_and_download_memray_profile(background_tasks: BackgroundTasks):
    global MEMRAY_TRACKER, MEMRAY_FILE_PATH, PROFILING_START_TIME

    if not MEMRAY_AVAILABLE:
        raise HTTPException(status_code=501, detail="Memray is not installed on this server.")

    if not MEMRAY_TRACKER or not MEMRAY_FILE_PATH:
        raise HTTPException(status_code=404, detail="No active profiling session to stop.")

    report_path = MEMRAY_FILE_PATH
    MEMRAY_TRACKER.__exit__(None, None, None)
    MEMRAY_TRACKER = None
    MEMRAY_FILE_PATH = None
    PROFILING_START_TIME = None

    if not report_path.exists():
        raise HTTPException(status_code=500, detail="Memray .bin file not found.")

    background_tasks.add_task(cleanup_file, report_path)

    return FileResponse(
        path=report_path,
        filename=report_path.name,
        media_type="application/octet-stream"
    )
