"""
Container task execution orchestration with Kubernetes Jobs.

Main entry point for executing container tasks with:
- Script and file loading from multiple sources (file, GCS, S3, HTTP)
- Kubernetes Job and ConfigMap creation
- Pod lifecycle monitoring and log streaming
- Environment variable and credential injection
- Resource limit management
- Cleanup after completion
"""

import uuid
import time
import base64
from typing import Dict, Optional, Callable, Any
from jinja2 import Environment
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def execute_container_task(
    task_config: Dict,
    context: Dict,
    jinja_env: Environment,
    task_with: Dict,
    log_event_callback: Optional[Callable] = None
) -> Dict:
    """
    Execute a container task as a Kubernetes Job.

    This function orchestrates the complete lifecycle of a container task:
    1. Load and encode scripts/files from various sources
    2. Create ConfigMap with scripts and files
    3. Create Kubernetes Job with environment variables and mounts
    4. Monitor Job execution and stream pod logs
    5. Report execution status and results
    6. Clean up resources if configured

    Args:
        task_config: The task configuration containing:
            - runtime: Kubernetes Job configuration (provider, namespace, image, command, etc.)
            - script: Script to execute (uri, source)
            - env: Environment variables to inject
            - auth: Optional authentication configuration
        context: The execution context containing:
            - execution_id: The execution identifier
            - Other context variables for Jinja2 rendering
        jinja_env: The Jinja2 environment for template rendering
        task_with: The rendered 'with' parameters (usually empty for container tasks)
        log_event_callback: Optional callback function to log events

    Returns:
        A dictionary containing the task execution result:
        - id: Task identifier (UUID)
        - status: 'success' or 'error'
        - data: Dictionary containing:
            - job_name: Kubernetes Job name
            - pod_name: Pod name that executed the job
            - exit_code: Container exit code
            - logs: Pod logs (stdout/stderr)
        - error: Error message (on error)

    Example:
        >>> result = execute_container_task(
        ...     task_config={
        ...         'runtime': {
        ...             'provider': 'kubernetes',
        ...             'namespace': 'noetl',
        ...             'image': 'postgres:16-alpine',
        ...             'command': ['/bin/bash', '/workspace/script.sh']
        ...         },
        ...         'script': {
        ...             'uri': './scripts/init.sh',
        ...             'source': {'type': 'file'}
        ...         },
        ...         'env': {'PGHOST': 'localhost'}
        ...     },
        ...     context={'execution_id': 'exec-123'},
        ...     jinja_env=Environment(),
        ...     task_with={}
        ... )
        >>> result['status']
        'success'
    """
    try:
        from kubernetes import client, config
        from kubernetes.client.rest import ApiException
    except ImportError:
        error_msg = "kubernetes library not installed. Install with: pip install kubernetes"
        logger.error(error_msg)
        return {
            'id': str(uuid.uuid4()),
            'status': 'error',
            'error': error_msg,
            'data': {}
        }

    task_id = str(uuid.uuid4())
    execution_id = context.get('execution_id', 'unknown')

    logger.info(f"Starting container task execution: task_id={task_id}, execution_id={execution_id}")

    try:
        # Load Kubernetes config (in-cluster or kubeconfig)
        try:
            config.load_incluster_config()
            logger.debug("Loaded in-cluster Kubernetes configuration")
        except config.ConfigException:
            config.load_kube_config()
            logger.debug("Loaded kubeconfig configuration")

        # Extract runtime configuration
        runtime = task_config.get('runtime', {})
        if not runtime:
            raise ValueError("Container task requires 'runtime' configuration")

        provider = runtime.get('provider', 'kubernetes')
        if provider != 'kubernetes':
            raise ValueError(f"Unsupported container provider: {provider}")

        namespace = runtime.get('namespace', 'default')
        image = runtime.get('image')
        if not image:
            raise ValueError("Container task requires 'runtime.image'")

        command = runtime.get('command', ['/bin/bash'])
        service_account = runtime.get('serviceAccountName', 'default')
        backoff_limit = runtime.get('backoffLimit', 0)
        active_deadline = runtime.get('activeDeadlineSeconds', 600)
        cleanup = runtime.get('cleanup', True)
        resources = runtime.get('resources', {})

        # Load script and files
        from noetl.plugin.tools.container.loader import load_script, load_files
        
        script_content = None
        if 'script' in task_config:
            script_config = task_config['script']
            script_content = load_script(script_config, context, jinja_env)
            logger.debug(f"Loaded script: {len(script_content)} bytes")

        files = {}
        if 'files' in runtime:
            files = load_files(runtime['files'], context, jinja_env)
            logger.debug(f"Loaded {len(files)} files")

        # Render environment variables
        env_config = task_config.get('env', {})
        env_vars = []
        for key, value in env_config.items():
            # Render value with Jinja2
            rendered_value = jinja_env.from_string(str(value)).render(context)
            env_vars.append(client.V1EnvVar(name=key, value=rendered_value))
            logger.debug(f"Added environment variable: {key}")

        # Create ConfigMap with script and files
        from noetl.plugin.tools.container.configmap import create_configmap
        
        configmap_name = f"noetl-job-{execution_id[:8]}-{task_id[:8]}"
        configmap_data = {}
        
        if script_content:
            # Use the last component of command as script filename if it's a script path
            script_filename = 'script.sh'
            if command and len(command) > 0:
                last_arg = command[-1]
                if last_arg.startswith('/workspace/'):
                    script_filename = last_arg.replace('/workspace/', '')
            configmap_data[script_filename] = script_content

        configmap_data.update(files)

        v1 = client.CoreV1Api()
        if configmap_data:
            create_configmap(v1, namespace, configmap_name, configmap_data)
            logger.info(f"Created ConfigMap: {configmap_name} with {len(configmap_data)} files")

        # Create Kubernetes Job
        from noetl.plugin.tools.container.job import create_job, wait_for_job_completion, get_pod_logs, delete_job

        job_name = f"noetl-{execution_id[:8]}-{task_id[:8]}"
        
        batch_v1 = client.BatchV1Api()
        create_job(
            batch_v1=batch_v1,
            namespace=namespace,
            job_name=job_name,
            image=image,
            command=command,
            env_vars=env_vars,
            configmap_name=configmap_name if configmap_data else None,
            service_account=service_account,
            backoff_limit=backoff_limit,
            active_deadline_seconds=active_deadline,
            resources=resources
        )
        logger.info(f"Created Kubernetes Job: {job_name}")

        # Wait for Job completion and get results
        success, pod_name, message = wait_for_job_completion(
            batch_v1=batch_v1,
            v1=v1,
            namespace=namespace,
            job_name=job_name,
            timeout_seconds=active_deadline
        )

        # Get pod logs
        logs = ""
        exit_code = None
        if pod_name:
            logs = get_pod_logs(v1, namespace, pod_name)
            
            # Get exit code from pod status
            try:
                pod = v1.read_namespaced_pod(pod_name, namespace)
                if pod.status.container_statuses:
                    container_status = pod.status.container_statuses[0]
                    if container_status.state.terminated:
                        exit_code = container_status.state.terminated.exit_code
            except Exception as e:
                logger.warning(f"Could not retrieve pod exit code: {e}")

        logger.info(f"Job completed: success={success}, exit_code={exit_code}")

        # Cleanup resources if configured
        if cleanup:
            try:
                delete_job(batch_v1, namespace, job_name)
                logger.debug(f"Deleted Job: {job_name}")
                
                if configmap_data:
                    v1.delete_namespaced_config_map(configmap_name, namespace)
                    logger.debug(f"Deleted ConfigMap: {configmap_name}")
            except Exception as e:
                logger.warning(f"Cleanup error: {e}")

        # Prepare result
        result_data = {
            'job_name': job_name,
            'pod_name': pod_name,
            'exit_code': exit_code,
            'logs': logs,
            'message': message
        }

        if success and exit_code == 0:
            logger.info(f"Container task completed successfully: {task_id}")
            return {
                'id': task_id,
                'status': 'success',
                'data': result_data
            }
        else:
            error_msg = f"Container task failed: {message}"
            if exit_code is not None:
                error_msg += f" (exit code: {exit_code})"
            logger.error(error_msg)
            logger.error(f"Pod logs:\n{logs}")
            return {
                'id': task_id,
                'status': 'error',
                'error': error_msg,
                'data': result_data
            }

    except Exception as e:
        logger.exception(f"Container task execution failed: {e}")
        return {
            'id': task_id,
            'status': 'error',
            'error': str(e),
            'traceback': str(e.__class__.__name__),
            'data': {}
        }
