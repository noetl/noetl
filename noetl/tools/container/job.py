"""
Kubernetes Job management for container tasks.

Handles Job creation, monitoring, log retrieval, and cleanup.
"""

import time
from typing import Dict, Optional, Tuple, List
from kubernetes import client
from kubernetes.client.rest import ApiException
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def create_job(
    batch_v1: client.BatchV1Api,
    namespace: str,
    job_name: str,
    image: str,
    command: List[str],
    env_vars: List[client.V1EnvVar],
    configmap_name: Optional[str] = None,
    service_account: str = 'default',
    backoff_limit: int = 0,
    active_deadline_seconds: int = 600,
    resources: Optional[Dict] = None
) -> client.V1Job:
    """
    Create a Kubernetes Job for container task execution.

    Args:
        batch_v1: Kubernetes BatchV1Api client
        namespace: Target namespace
        job_name: Job name
        image: Container image
        command: Container command
        env_vars: Environment variables
        configmap_name: Optional ConfigMap name to mount
        service_account: ServiceAccount to use
        backoff_limit: Job retry limit
        active_deadline_seconds: Job timeout
        resources: Resource requests/limits

    Returns:
        Created Job object
    """
    # Build container spec
    container = client.V1Container(
        name='main',
        image=image,
        command=command,
        env=env_vars,
        image_pull_policy='IfNotPresent'
    )

    # Add resource limits if specified
    if resources:
        limits = resources.get('limits', {})
        requests = resources.get('requests', {})
        container.resources = client.V1ResourceRequirements(
            limits=limits,
            requests=requests
        )

    # Add ConfigMap volume mount if provided
    volumes = []
    volume_mounts = []
    
    if configmap_name:
        volumes.append(
            client.V1Volume(
                name='scripts',
                config_map=client.V1ConfigMapVolumeSource(
                    name=configmap_name
                )
            )
        )
        volume_mounts.append(
            client.V1VolumeMount(
                name='scripts',
                mount_path='/workspace'
            )
        )
        container.volume_mounts = volume_mounts

    # Build pod spec
    pod_spec = client.V1PodSpec(
        containers=[container],
        restart_policy='Never',
        service_account_name=service_account,
        volumes=volumes if volumes else None
    )

    # Build job spec
    job_spec = client.V1JobSpec(
        template=client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(
                labels={
                    'app': 'noetl',
                    'component': 'container-task',
                    'job-name': job_name
                }
            ),
            spec=pod_spec
        ),
        backoff_limit=backoff_limit,
        active_deadline_seconds=active_deadline_seconds
    )

    # Create job object
    job = client.V1Job(
        api_version='batch/v1',
        kind='Job',
        metadata=client.V1ObjectMeta(
            name=job_name,
            namespace=namespace,
            labels={
                'app': 'noetl',
                'component': 'container-task'
            }
        ),
        spec=job_spec
    )

    try:
        created = batch_v1.create_namespaced_job(namespace, job)
        logger.info(f"Created Job {job_name} in namespace {namespace}")
        return created
    except ApiException as e:
        logger.error(f"Failed to create Job: {e}")
        raise


def wait_for_job_completion(
    batch_v1: client.BatchV1Api,
    v1: client.CoreV1Api,
    namespace: str,
    job_name: str,
    timeout_seconds: int = 600,
    poll_interval: int = 2
) -> Tuple[bool, Optional[str], str]:
    """
    Wait for a Kubernetes Job to complete.

    Args:
        batch_v1: Kubernetes BatchV1Api client
        v1: Kubernetes CoreV1Api client
        namespace: Target namespace
        job_name: Job name
        timeout_seconds: Maximum time to wait
        poll_interval: Seconds between status checks

    Returns:
        Tuple of (success, pod_name, message)
    """
    start_time = time.time()
    
    logger.info(f"Waiting for Job {job_name} to complete (timeout: {timeout_seconds}s)")
    
    while True:
        elapsed = time.time() - start_time
        if elapsed > timeout_seconds:
            return False, None, f"Job timed out after {timeout_seconds} seconds"

        try:
            # Get job status
            job = batch_v1.read_namespaced_job(job_name, namespace)
            
            if job.status.succeeded:
                logger.info(f"Job {job_name} succeeded")
                pod_name = _get_job_pod_name(v1, namespace, job_name)
                return True, pod_name, "Job completed successfully"
            
            if job.status.failed:
                logger.error(f"Job {job_name} failed")
                pod_name = _get_job_pod_name(v1, namespace, job_name)
                message = "Job failed"
                
                # Try to get failure reason from pod
                if pod_name:
                    try:
                        pod = v1.read_namespaced_pod(pod_name, namespace)
                        if pod.status.container_statuses:
                            container_status = pod.status.container_statuses[0]
                            if container_status.state.terminated:
                                reason = container_status.state.terminated.reason
                                message = f"Job failed: {reason}"
                    except Exception as e:
                        logger.warning(f"Could not retrieve pod failure reason: {e}")
                
                return False, pod_name, message

        except ApiException as e:
            if e.status == 404:
                return False, None, "Job not found"
            logger.warning(f"Error checking job status: {e}")

        time.sleep(poll_interval)


def _get_job_pod_name(v1: client.CoreV1Api, namespace: str, job_name: str) -> Optional[str]:
    """
    Get the pod name for a job.

    Args:
        v1: Kubernetes CoreV1Api client
        namespace: Target namespace
        job_name: Job name

    Returns:
        Pod name or None if not found
    """
    try:
        pods = v1.list_namespaced_pod(
            namespace,
            label_selector=f'job-name={job_name}'
        )
        
        if pods.items:
            return pods.items[0].metadata.name
        
        return None
    except ApiException as e:
        logger.warning(f"Failed to get pod for job {job_name}: {e}")
        return None


def get_pod_logs(
    v1: client.CoreV1Api,
    namespace: str,
    pod_name: str,
    container: str = 'main'
) -> str:
    """
    Retrieve logs from a pod.

    Args:
        v1: Kubernetes CoreV1Api client
        namespace: Target namespace
        pod_name: Pod name
        container: Container name

    Returns:
        Pod logs as string
    """
    try:
        logs = v1.read_namespaced_pod_log(
            pod_name,
            namespace,
            container=container
        )
        return logs
    except ApiException as e:
        logger.warning(f"Failed to retrieve logs from pod {pod_name}: {e}")
        return f"Failed to retrieve logs: {e}"


def delete_job(
    batch_v1: client.BatchV1Api,
    namespace: str,
    job_name: str,
    propagation_policy: str = 'Background'
) -> None:
    """
    Delete a Kubernetes Job and its pods.

    Args:
        batch_v1: Kubernetes BatchV1Api client
        namespace: Target namespace
        job_name: Job name
        propagation_policy: Deletion propagation policy
    """
    try:
        batch_v1.delete_namespaced_job(
            job_name,
            namespace,
            propagation_policy=propagation_policy
        )
        logger.debug(f"Deleted Job {job_name} from namespace {namespace}")
    except ApiException as e:
        if e.status == 404:
            logger.debug(f"Job {job_name} not found (already deleted)")
        else:
            logger.warning(f"Failed to delete Job: {e}")
