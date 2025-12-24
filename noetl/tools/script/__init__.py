"""
Script execution tool - Run scripts as Kubernetes jobs.

Supports downloading scripts from:
- Google Cloud Storage (GCS)
- AWS S3
- HTTP endpoints
- Local filesystem

Executes scripts as Kubernetes jobs with resource limits, retries, and monitoring.
"""

import json
import time
from typing import Dict, Any, Optional, Callable
from kubernetes import client, config
from kubernetes.client.rest import ApiException

from noetl.core.logger import setup_logger
from noetl.tools.container.loader import load_script
from noetl.worker.keychain_resolver import populate_keychain_context

logger = setup_logger(__name__, include_location=True)


async def execute_script_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env,
    task_with: Dict[str, Any] = None,
    log_event_callback: Optional[Callable] = None
) -> Dict[str, Any]:
    """
    Execute a script as a Kubernetes job.
    
    Args:
        task_config: Task configuration with script source and job settings
        context: Execution context
        jinja_env: Jinja2 environment for template rendering
        task_with: Additional task parameters
        log_event_callback: Callback for logging events
        
    Returns:
        Job execution result with status, output, and metadata
        
    Example:
        task_config = {
            'script': {
                'uri': 'gs://bucket/script.py',
                'source': {'type': 'gcs', 'auth': 'gcp_cred'}
            },
            'args': {'input': 'data.csv'},
            'job': {
                'image': 'python:3.11-slim',
                'namespace': 'noetl',
                'resources': {
                    'requests': {'memory': '256Mi', 'cpu': '500m'},
                    'limits': {'memory': '512Mi', 'cpu': '1000m'}
                }
            }
        }
    """
    execution_id = context.get('execution_id', 'unknown')
    task_name = task_config.get('name', 'script_job')
    
    logger.info(f"Starting script execution as K8s job: {task_name}")
    
    # Populate keychain context before rendering templates
    catalog_id = context.get('catalog_id')
    if catalog_id:
        server_url = context.get('server_url', 'http://noetl.noetl.svc.cluster.local:8082')
        logger.critical(f"SCRIPT: About to populate keychain with task_config keys: {list(task_config.keys())}")
        logger.critical(f"SCRIPT: task_config.job keys: {list(task_config.get('job', {}).keys())}")
        logger.critical(f"SCRIPT: task_config.job.env: {task_config.get('job', {}).get('env', {})}")
        
        context = await populate_keychain_context(
            task_config=task_config,
            context=context,
            catalog_id=catalog_id,
            execution_id=execution_id,
            api_base_url=server_url
        )
        logger.critical(f"SCRIPT: Keychain context populated: {list(context.get('keychain', {}).keys())}")
        
        # Flatten keychain entries to top-level context for Jinja2 template access
        # This allows {{ gcp_sa.field }} instead of {{ keychain.gcp_sa.field }}
        keychain_data = context.get('keychain', {})
        for key, value in keychain_data.items():
            context[key] = value
            logger.critical(f"SCRIPT: Flattened keychain entry '{key}' with keys: {list(value.keys()) if isinstance(value, dict) else type(value)}")
        logger.critical(f"SCRIPT: Flattened {len(keychain_data)} keychain entries to top-level context")
    else:
        logger.warning("SCRIPT: No catalog_id in context, skipping keychain resolution")
    
    # Load script from configured source
    script_config = task_config.get('script')
    if not script_config:
        raise ValueError("'script' configuration is required")
    
    script_content = load_script(script_config, context, jinja_env)
    logger.info(f"Loaded script: {len(script_content)} bytes")
    
    # Get job configuration
    job_config = task_config.get('job', {})
    image = job_config.get('image', 'python:3.11-slim')
    namespace = job_config.get('namespace', 'noetl')
    ttl_seconds = job_config.get('ttlSecondsAfterFinished', 300)
    backoff_limit = job_config.get('backoffLimit', 3)
    resources = job_config.get('resources', {})
    
    # Get script arguments
    script_args = task_config.get('args', {})
    
    # Get environment variables from job config (for credentials/tokens from keychain)
    # IMPORTANT: Render env var values through Jinja2 to resolve keychain references
    env_vars_raw = job_config.get('env', {})
    env_vars = {}
    for key, value in env_vars_raw.items():
        if isinstance(value, str):
            # Render Jinja2 template to resolve {{ keychain.field }} references
            template = jinja_env.from_string(value)
            env_vars[key] = template.render(context)
        else:
            env_vars[key] = value
    
    logger.info(f"Rendered {len(env_vars)} environment variables for K8s job")
    
    # Generate unique job name
    job_name = f"script-{task_name.replace('_', '-')}-{execution_id}"[:63]
    
    # Load Kubernetes config
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()
    
    batch_v1 = client.BatchV1Api()
    core_v1 = client.CoreV1Api()
    
    # Create ConfigMap with script content
    configmap_name = f"{job_name}-script"
    configmap = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(name=configmap_name, namespace=namespace),
        data={"script.py": script_content}
    )
    
    # Delete existing ConfigMap if it exists (idempotent for retries)
    try:
        core_v1.delete_namespaced_config_map(name=configmap_name, namespace=namespace)
        logger.info(f"Deleted existing ConfigMap: {configmap_name}")
    except ApiException as e:
        if e.status != 404:
            logger.warning(f"Failed to delete ConfigMap (non-404): {e}")
    
    try:
        core_v1.create_namespaced_config_map(namespace=namespace, body=configmap)
        logger.info(f"Created ConfigMap: {configmap_name}")
    except ApiException as e:
        logger.error(f"Failed to create ConfigMap: {e}")
        raise
    
    # Create Secret for credentials/tokens if env_vars provided
    secret_name = None
    if env_vars:
        secret_name = f"{job_name}-secrets"
        # Convert all values to base64 strings as required by K8s secrets
        secret_data = {}
        for key, value in env_vars.items():
            if isinstance(value, str):
                secret_data[key] = value
            else:
                secret_data[key] = json.dumps(value)
        
        secret = client.V1Secret(
            metadata=client.V1ObjectMeta(name=secret_name, namespace=namespace),
            string_data=secret_data  # K8s will base64 encode automatically
        )
        
        # Delete existing Secret if it exists (idempotent for retries)
        try:
            core_v1.delete_namespaced_secret(name=secret_name, namespace=namespace)
            logger.info(f"Deleted existing Secret: {secret_name}")
        except ApiException as e:
            if e.status != 404:
                logger.warning(f"Failed to delete Secret (non-404): {e}")
        
        try:
            core_v1.create_namespaced_secret(namespace=namespace, body=secret)
            logger.info(f"Created Secret: {secret_name} with {len(env_vars)} environment variables")
        except ApiException as e:
            logger.error(f"Failed to create Secret: {e}")
            # Clean up ConfigMap
            core_v1.delete_namespaced_config_map(name=configmap_name, namespace=namespace)
            raise
    
    # Build container command with args
    # Install dependencies if needed, then run script
    args_json = json.dumps(script_args)
    install_deps = job_config.get('install_dependencies', [])
    
    if install_deps:
        deps_str = ' '.join(install_deps)
        container_command = [
            "sh", "-c",
            f"pip3 install --quiet {deps_str} && python3 /scripts/script.py '{args_json}'"
        ]
    else:
        container_command = [
            "sh", "-c",
            f"python3 /scripts/script.py '{args_json}'"
        ]
    
    # Build environment variables for container
    container_env = []
    if secret_name:
        # Mount all secret keys as environment variables
        for key in env_vars.keys():
            container_env.append(
                client.V1EnvVar(
                    name=key,
                    value_from=client.V1EnvVarSource(
                        secret_key_ref=client.V1SecretKeySelector(
                            name=secret_name,
                            key=key
                        )
                    )
                )
            )
    
    # Create Job
    container = client.V1Container(
        name="script-runner",
        image=image,
        command=container_command,
        env=container_env if container_env else None,
        volume_mounts=[
            client.V1VolumeMount(
                name="script-volume",
                mount_path="/scripts"
            )
        ]
    )
    
    # Only add resources if they are defined to avoid empty dict serialization issues
    if resources:
        requests = resources.get('requests')
        limits = resources.get('limits')
        if requests or limits:
            container.resources = client.V1ResourceRequirements(
                requests=requests if requests else None,
                limits=limits if limits else None
            )
    
    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"job": job_name}),
        spec=client.V1PodSpec(
            restart_policy="Never",
            containers=[container],
            volumes=[
                client.V1Volume(
                    name="script-volume",
                    config_map=client.V1ConfigMapVolumeSource(name=configmap_name)
                )
            ]
        )
    )
    
    job = client.V1Job(
        metadata=client.V1ObjectMeta(name=job_name, namespace=namespace),
        spec=client.V1JobSpec(
            template=template,
            backoff_limit=backoff_limit,
            ttl_seconds_after_finished=ttl_seconds
        )
    )
    
    # Delete existing Job if it exists (idempotent for retries)
    try:
        batch_v1.delete_namespaced_job(
            name=job_name, 
            namespace=namespace,
            propagation_policy='Foreground'  # Wait for pods to be deleted
        )
        logger.info(f"Deleted existing Job: {job_name}")
    except ApiException as e:
        if e.status != 404:
            logger.warning(f"Failed to delete Job (non-404): {e}")
    
    try:
        batch_v1.create_namespaced_job(namespace=namespace, body=job)
        logger.info(f"Created Job: {job_name}")
    except ApiException as e:
        logger.error(f"Failed to create Job: {e}")
        # Clean up ConfigMap and Secret
        core_v1.delete_namespaced_config_map(name=configmap_name, namespace=namespace)
        if secret_name:
            core_v1.delete_namespaced_secret(name=secret_name, namespace=namespace)
        raise
    
    # Wait for job completion
    start_time = time.time()
    timeout = job_config.get('timeout', 600)  # 10 minutes default
    
    while True:
        try:
            job_status = batch_v1.read_namespaced_job_status(name=job_name, namespace=namespace)
            
            if job_status.status.succeeded:
                logger.info(f"Job {job_name} completed successfully")
                break
            
            if job_status.status.failed:
                logger.error(f"Job {job_name} failed")
                break
            
            if time.time() - start_time > timeout:
                logger.error(f"Job {job_name} timed out after {timeout}s")
                break
            
            time.sleep(5)
            
        except ApiException as e:
            logger.error(f"Error checking job status: {e}")
            break
    
    # Get pod logs
    pod_list = core_v1.list_namespaced_pod(
        namespace=namespace,
        label_selector=f"job={job_name}"
    )
    
    pod_logs = ""
    pod_name = None
    if pod_list.items:
        pod_name = pod_list.items[0].metadata.name
        try:
            pod_logs = core_v1.read_namespaced_pod_log(name=pod_name, namespace=namespace)
        except ApiException as e:
            logger.warning(f"Could not fetch pod logs: {e}")
    
    execution_time = time.time() - start_time
    
    # Determine final status - check both job status and pod exit code
    job_status = batch_v1.read_namespaced_job_status(name=job_name, namespace=namespace)
    
    # Check pod exit code for actual script failure
    exit_code = None
    if pod_list.items:
        pod = pod_list.items[0]
        if pod.status.container_statuses:
            container_status = pod.status.container_statuses[0]
            if container_status.state.terminated:
                exit_code = container_status.state.terminated.exit_code
    
    # Job is failed if K8s job failed OR pod exited with non-zero code
    job_failed = job_status.status.failed or (exit_code is not None and exit_code != 0)
    status = "failed" if job_failed else "completed"
    
    result = {
        "status": status,
        "job_name": job_name,
        "namespace": namespace,
        "pod_name": pod_name,
        "execution_time": execution_time,
        "output": pod_logs,
        "succeeded": job_status.status.succeeded or 0,
        "failed": job_status.status.failed or 0,
        "exit_code": exit_code,
        "kubectl_logs": f"kubectl logs {pod_name} -n {namespace}" if pod_name else None,
        "kubectl_describe": f"kubectl describe job {job_name} -n {namespace}"
    }
    
    if status == "failed":
        error_msg = f"Script job {job_name} failed: exit_code={exit_code}, k8s_failed={job_status.status.failed}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    logger.info(f"Script job {job_name} finished: {status} ({execution_time:.2f}s, exit_code={exit_code})")
    
    return result
