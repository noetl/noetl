# Running Multiple NoETL Workers pool

### Quick Start Scripts

Use the provided scripts for easy management:

- Start three workers at once
```bash
./bin/start_multiple_workers.sh
```

- Stop workers
```bash
./bin/stop_multiple_workers.sh
```
supports running multiple worker pool instances simultaneously, allowing to distribute workloads across different worker pools optimized for specific tasks (e.g., CPU-intensive vs GPU-intensive workloads).

## Overview

Each worker instance pool runs as a separate process with its own unique PID file, enabling independent management and monitoring of different worker pools.

## Prerequisites

- NoETL installed and configured
- NoETL server running and accessible
- Environment variables properly configured

## Quick Start with Pre-configured Files

A pre-configured environment files and scripts created in the root folder of the project:

### Pre-configured Environment Files

The following environment files are ready to use:

- **`.env.worker-cpu-01`** - CPU worker configuration
- **`.env.worker-cpu-02`** - Second CPU worker configuration  
- **`.env.worker-gpu-01`** - GPU worker configuration

### Quick Start Scripts

Use the provided scripts for easy management:
- Start all three workers at once
```bash
./bin/start_multiple_workers.sh
```

- Stop all workers
```bash
./bin/stop_multiple_workers.sh
```

### Manual Start (Alternative)

Or start workers individually:

```bash
# Start CPU Worker 01
NOETL_WORKER_POOL_NAME=worker-cpu-01 . .env.worker-cpu-01 && make worker-start

# Start CPU Worker 02
NOETL_WORKER_POOL_NAME=worker-cpu-02 . .env.worker-cpu-02 && make worker-start

# Start GPU Worker 01
NOETL_WORKER_POOL_NAME=worker-gpu-01 . .env.worker-gpu-01 && make worker-start
```

### Using Environment Files

Create separate environment files for each worker:

**`.env.worker-cpu`**
```bash
NOETL_WORKER_POOL_NAME=worker-cpu-01
NOETL_WORKER_POOL_RUNTIME=cpu
NOETL_DEBUG=true
```

**`.env.worker-gpu`**
```bash
NOETL_WORKER_POOL_NAME=worker-gpu-01
NOETL_WORKER_POOL_RUNTIME=gpu
NOETL_DEBUG=true
```

Then start each worker with its specific environment file:

```bash
# Start CPU worker
NOETL_WORKER_POOL_NAME=worker-cpu-01 . .env.worker-cpu && make worker-start

# Start GPU worker
NOETL_WORKER_POOL_NAME=worker-gpu-01 . .env.worker-gpu && make worker-start
```

## Worker Management

### Checking Running Workers

Each worker creates a unique PID file in `~/.noetl/`:

```bash
ls -la ~/.noetl/
# Output:
# -rw-r--r--  1 user  staff     5 Aug 27 11:36 noetl_worker_worker_cpu_01.pid
# -rw-r--r--  1 user  staff     5 Aug 27 11:36 noetl_worker_worker_gpu_01.pid
```

### Stopping Workers

#### Interactive Stop

To stop workers interactively:

```bash
make worker-stop
```

This will display a menu of running workers:

```
Stopping NoETL workers...
Running workers:
  1. worker_cpu_01 (PID: 75337)
  2. worker_gpu_01 (PID: 75819)
Enter the number of the worker to stop:
```

Select the worker by entering its number.

#### Direct Stop by Name

To stop a specific worker directly:

```bash
noetl worker stop --name worker-cpu-01
```

#### Force Stop

To force stop a worker without confirmation:

```bash
noetl worker stop --name worker-gpu-01 --force
```

## Worker Configuration

### Worker Pool Names

Worker pool names should follow this convention:
- Use lowercase letters, numbers, and underscores only
- Avoid hyphens (they are converted to underscores internally)
- Examples: `worker_cpu_01`, `gpu_worker`, `batch_processor`

### Runtime Types

Common runtime types:
- `cpu`: For CPU-intensive tasks
- `gpu`: For GPU-accelerated tasks
- `qpu`: For QPU-processing workloads

### Environment Variables

Key environment variables for workers:

| Variable | Description | Example |
|----------|-------------|---------|
| `NOETL_WORKER_POOL_NAME` | Unique name for the worker pool | `worker-cpu-01` |
| `NOETL_WORKER_POOL_RUNTIME` | Runtime type (cpu, gpu, etc.) | `cpu` |
| `NOETL_DEBUG` | Enable debug logging | `true` |
| `NOETL_HOST` | Server API host | `localhost` |
| `NOETL_PORT` | Server API port | `8083` |
| `NOETL_PLAYBOOK_PATH` | Path to playbook file | `./playbooks/my-playbook.yaml` |

## Monitoring Multiple Workers

### Process Monitoring

Check running worker processes:

```bash
ps aux | grep "noetl worker start" | grep -v grep
```

### Log Files

Each worker creates its own separate log file:

- **CPU Worker 01**: `logs/worker_worker_cpu_01.log`
- **CPU Worker 02**: `logs/worker_worker_cpu_02.log`
- **GPU Worker 01**: `logs/worker_worker_gpu_01.log`

### API Monitoring

Workers register themselves with the NoETL server API. You can check worker status via the API:  

- Check all worker pools
```bash
curl http://localhost:8083/api/worker/pools
```

- Or check via the web interface
```bash
open http://localhost:8083/docs
```

## Best Practices

### 1. Unique Naming
Always use unique worker pool names to avoid conflicts and enable proper management.

### 2. Resource Allocation
- CPU workers: Allocate based on available CPU cores
- GPU workers: Ensure GPU resources are available and properly configured
- Monitor resource usage to optimize worker distribution

### 3. Environment Isolation
Use separate environment files for different worker types to maintain configuration isolation.

### 4. Log Management
Consider implementing log rotation for long-running worker instances.

### 5. Health Monitoring
Regularly check worker status and restart failed workers as needed.

## Troubleshooting

### Orphaned Worker Processes
If you have worker processes running without corresponding PID files:

```bash
pkill -9 -f "noetl worker start"
rm -f ~/.noetl/noetl_worker_*.pid
```

### Worker Not Responding
- Use `noetl worker stop --name <worker-name> --force` to force stop
- Check system resources and logs for issues

## Example Setup

The pre-configured environment files provide a complete setup for three workers: two CPU workers and one GPU worker. Simply use:

- Quick start all workers
```bash
./bin/start_multiple_workers.sh
```

- Check running workers
```bash
ls ~/.noetl/noetl_worker_*.pid
ps aux | grep "noetl worker" | grep -v grep
```

### Manual Setup (Alternative)

If you prefer to create environment files:

- Create environment files
```bash
cat > .env.worker-cpu-01 << EOF
NOETL_WORKER_POOL_NAME=worker-cpu-01
NOETL_WORKER_POOL_RUNTIME=cpu
NOETL_DEBUG=false
NOETL_HOST=localhost
NOETL_PORT=8083
EOF

cat > .env.worker-cpu-02 << EOF
NOETL_WORKER_POOL_NAME=worker-cpu-02
NOETL_WORKER_POOL_RUNTIME=cpu
NOETL_DEBUG=false
NOETL_HOST=localhost
NOETL_PORT=8083
EOF

cat > .env.worker-gpu-01 << EOF
NOETL_WORKER_POOL_NAME=worker-gpu-01
NOETL_WORKER_POOL_RUNTIME=gpu
NOETL_DEBUG=false
NOETL_HOST=localhost
NOETL_PORT=8083
EOF
```

- Start all workers
```bash
NOETL_WORKER_POOL_NAME=worker-cpu-01 . .env.worker-cpu-01 && make worker-start
NOETL_WORKER_POOL_NAME=worker-cpu-02 . .env.worker-cpu-02 && make worker-start
NOETL_WORKER_POOL_NAME=worker-gpu-01 . .env.worker-gpu-01 && make worker-start
```

- Check running workers
```bash
ls ~/.noetl/noetl_worker_*.pid
ps aux | grep "noetl worker" | grep -v grep
```

- Check worker-specific log files
```bash
ls logs/worker_*.log
```