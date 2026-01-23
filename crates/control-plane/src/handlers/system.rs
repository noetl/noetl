//! System monitoring API handlers.
//!
//! Provides endpoints for system status, thread inspection, and resource monitoring.

use axum::{extract::State, Json};
use serde::Serialize;
use sysinfo::{Pid, System};

use crate::error::AppError;
use crate::state::AppState;

/// System resource utilization.
#[derive(Debug, Clone, Serialize)]
pub struct SystemStatus {
    /// CPU usage percentage (0-100).
    pub cpu_percent: f32,

    /// Memory usage percentage (0-100).
    pub memory_percent: f32,

    /// Total memory in MB.
    pub total_memory_mb: f64,

    /// Used memory in MB.
    pub used_memory_mb: f64,

    /// Available memory in MB.
    pub available_memory_mb: f64,
}

/// Process resource utilization.
#[derive(Debug, Clone, Serialize)]
pub struct ProcessStatus {
    /// Process ID.
    pub pid: u32,

    /// CPU usage percentage.
    pub cpu_percent: f32,

    /// Resident set size (physical memory) in MB.
    pub memory_rss_mb: f64,

    /// Virtual memory size in MB.
    pub memory_vms_mb: f64,

    /// Number of threads.
    pub num_threads: usize,

    /// Process start time (Unix timestamp).
    pub start_time: u64,

    /// Process uptime in seconds.
    pub uptime_seconds: u64,
}

/// Combined status response.
#[derive(Debug, Clone, Serialize)]
pub struct StatusResponse {
    /// System resource utilization.
    pub system: SystemStatus,

    /// Process resource utilization.
    pub process: ProcessStatus,
}

/// Thread information.
#[derive(Debug, Clone, Serialize)]
pub struct ThreadInfo {
    /// Thread ID.
    pub thread_id: u64,

    /// Thread name.
    pub name: String,

    /// Whether the thread is alive.
    pub is_alive: bool,
}

/// Get system and process status.
///
/// GET /api/status
///
/// Returns comprehensive metrics including system CPU/memory and process details.
pub async fn get_status(State(state): State<AppState>) -> Result<Json<StatusResponse>, AppError> {
    let mut sys = System::new_all();
    sys.refresh_all();

    // System status
    let cpu_percent = sys.global_cpu_usage();
    let total_memory = sys.total_memory();
    let used_memory = sys.used_memory();
    let available_memory = sys.available_memory();

    let system_status = SystemStatus {
        cpu_percent,
        memory_percent: (used_memory as f32 / total_memory as f32) * 100.0,
        total_memory_mb: total_memory as f64 / 1_048_576.0,
        used_memory_mb: used_memory as f64 / 1_048_576.0,
        available_memory_mb: available_memory as f64 / 1_048_576.0,
    };

    // Process status
    let pid = std::process::id();
    let process_status = if let Some(process) = sys.process(Pid::from_u32(pid)) {
        ProcessStatus {
            pid,
            cpu_percent: process.cpu_usage(),
            memory_rss_mb: process.memory() as f64 / 1_048_576.0,
            memory_vms_mb: process.virtual_memory() as f64 / 1_048_576.0,
            num_threads: 0, // Thread count not directly available in sysinfo
            start_time: process.start_time(),
            uptime_seconds: state.uptime_seconds(),
        }
    } else {
        ProcessStatus {
            pid,
            cpu_percent: 0.0,
            memory_rss_mb: 0.0,
            memory_vms_mb: 0.0,
            num_threads: 0,
            start_time: 0,
            uptime_seconds: state.uptime_seconds(),
        }
    };

    Ok(Json(StatusResponse {
        system: system_status,
        process: process_status,
    }))
}

/// Get active threads information.
///
/// GET /api/threads
///
/// Returns information about active threads in the process.
/// Note: Thread introspection in Rust is limited compared to Python.
pub async fn get_threads() -> Result<Json<Vec<ThreadInfo>>, AppError> {
    // In Rust, thread introspection is more limited than in Python
    // ThreadId doesn't expose a stable numeric ID, so we parse from Debug format
    let thread_id = format!("{:?}", std::thread::current().id());
    let thread_id_num: u64 = thread_id
        .trim_start_matches("ThreadId(")
        .trim_end_matches(')')
        .parse()
        .unwrap_or(0);

    let threads = vec![ThreadInfo {
        thread_id: thread_id_num,
        name: std::thread::current()
            .name()
            .unwrap_or("unknown")
            .to_string(),
        is_alive: true,
    }];

    Ok(Json(threads))
}

/// Profiler status response.
#[derive(Debug, Clone, Serialize)]
pub struct ProfilerStatusResponse {
    /// Whether profiling is currently active.
    pub is_profiling: bool,

    /// Current profiler type if active.
    pub profiler_type: Option<String>,

    /// Message about profiler status.
    pub message: String,
}

/// Get profiler status.
///
/// GET /api/profiler/status
///
/// Returns the current profiling status.
pub async fn get_profiler_status() -> Result<Json<ProfilerStatusResponse>, AppError> {
    // Memory profiling is not as easily integrated in Rust as Python's Memray
    // This is a placeholder for future implementation
    Ok(Json(ProfilerStatusResponse {
        is_profiling: false,
        profiler_type: None,
        message: "Memory profiling is not currently available in the Rust server".to_string(),
    }))
}

/// Start memory profiler response.
#[derive(Debug, Clone, Serialize)]
pub struct ProfilerStartResponse {
    /// Status of the operation.
    pub status: String,

    /// Message.
    pub message: String,
}

/// Start memory profiling.
///
/// POST /api/profiler/memory/start
///
/// Note: Memory profiling in Rust typically uses external tools like Valgrind or Heaptrack.
pub async fn start_memory_profiler() -> Result<Json<ProfilerStartResponse>, AppError> {
    Ok(Json(ProfilerStartResponse {
        status: "info".to_string(),
        message: "Memory profiling in Rust requires external tools (Valgrind, Heaptrack). \
                  Consider using RUST_BACKTRACE=1 and cargo-flamegraph for profiling."
            .to_string(),
    }))
}

/// Stop memory profiling.
///
/// POST /api/profiler/memory/stop
pub async fn stop_memory_profiler() -> Result<Json<ProfilerStartResponse>, AppError> {
    Ok(Json(ProfilerStartResponse {
        status: "info".to_string(),
        message: "Memory profiling is not currently active".to_string(),
    }))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_system_status_serialization() {
        let status = SystemStatus {
            cpu_percent: 45.5,
            memory_percent: 62.5,
            total_memory_mb: 16384.0,
            used_memory_mb: 10240.0,
            available_memory_mb: 6144.0,
        };

        let json = serde_json::to_string(&status).unwrap();
        assert!(json.contains("45.5"));
        assert!(json.contains("62.5"));
    }

    #[test]
    fn test_process_status_serialization() {
        let status = ProcessStatus {
            pid: 12345,
            cpu_percent: 15.3,
            memory_rss_mb: 256.5,
            memory_vms_mb: 512.0,
            num_threads: 8,
            start_time: 1704067200,
            uptime_seconds: 3600,
        };

        let json = serde_json::to_string(&status).unwrap();
        assert!(json.contains("12345"));
        assert!(json.contains("15.3"));
    }

    #[test]
    fn test_thread_info_serialization() {
        let info = ThreadInfo {
            thread_id: 1,
            name: "main".to_string(),
            is_alive: true,
        };

        let json = serde_json::to_string(&info).unwrap();
        assert!(json.contains("\"name\":\"main\""));
        assert!(json.contains("\"is_alive\":true"));
    }

    #[test]
    fn test_profiler_status_serialization() {
        let status = ProfilerStatusResponse {
            is_profiling: false,
            profiler_type: None,
            message: "Not profiling".to_string(),
        };

        let json = serde_json::to_string(&status).unwrap();
        assert!(json.contains("\"is_profiling\":false"));
    }
}
