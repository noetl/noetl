"""
Kubernetes ConfigMap management for container tasks.

Handles creation and deletion of ConfigMaps containing scripts and files
to be mounted into container jobs.
"""

from typing import Dict
from kubernetes import client
from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)


def create_configmap(
    v1: client.CoreV1Api,
    namespace: str,
    name: str,
    data: Dict[str, str]
) -> client.V1ConfigMap:
    """
    Create a Kubernetes ConfigMap with script/file data.

    Args:
        v1: Kubernetes CoreV1Api client
        namespace: Target namespace
        name: ConfigMap name
        data: Dictionary mapping filename to content

    Returns:
        Created ConfigMap object

    Raises:
        ApiException: If creation fails
    """
    configmap = client.V1ConfigMap(
        metadata=client.V1ObjectMeta(
            name=name,
            namespace=namespace,
            labels={
                'app': 'noetl',
                'component': 'container-task'
            }
        ),
        data=data
    )

    try:
        created = v1.create_namespaced_config_map(namespace, configmap)
        logger.info(f"Created ConfigMap {name} in namespace {namespace}")
        return created
    except client.rest.ApiException as e:
        logger.error(f"Failed to create ConfigMap: {e}")
        raise


def delete_configmap(
    v1: client.CoreV1Api,
    namespace: str,
    name: str
) -> None:
    """
    Delete a Kubernetes ConfigMap.

    Args:
        v1: Kubernetes CoreV1Api client
        namespace: Target namespace
        name: ConfigMap name
    """
    try:
        v1.delete_namespaced_config_map(name, namespace)
        logger.debug(f"Deleted ConfigMap {name} from namespace {namespace}")
    except client.rest.ApiException as e:
        if e.status == 404:
            logger.debug(f"ConfigMap {name} not found (already deleted)")
        else:
            logger.warning(f"Failed to delete ConfigMap: {e}")
