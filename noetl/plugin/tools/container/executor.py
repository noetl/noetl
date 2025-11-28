"""Execute shell scripts in external containers (Kubernetes Jobs)."""

from __future__ import annotations

import datetime
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from jinja2 import Environment
from kubernetes import client, config
from kubernetes.client import ApiException
from kubernetes.config.config_exception import ConfigException

from noetl.core.dsl.render import render_template
from noetl.core.logger import setup_logger
from noetl.plugin.shared.script import resolve_script, validate_script_config

logger = setup_logger(__name__, include_location=True)

SCRIPT_FILENAME = "script.sh"
SCRIPT_MOUNT_PATH = "/workspace"
DEFAULT_TIMEOUT_SECONDS = 900
POLL_INTERVAL_SECONDS = 2


class ContainerExecutionError(RuntimeError):
    """Raised when the container runtime reports an execution failure."""


def _render_value(env: Environment, template_val: Any, context: Dict[str, Any]) -> Any:
    if template_val is None:
        return None
    return render_template(env, template_val, context)


def _render_dict(env: Environment, template_val: Any, context: Dict[str, Any], *, field: str) -> Dict[str, Any]:
    rendered = _render_value(env, template_val, context)
    if rendered is None:
        return {}
    if not isinstance(rendered, dict):
        raise ValueError(f"Rendered {field} configuration must be a dict")
    return rendered


def _sanitize_name(value: str, prefix: str) -> str:
    base = value or prefix
    base = base.lower()
    base = re.sub(r"[^a-z0-9-]", "-", base)
    base = re.sub(r"-+", "-", base).strip("-")
    if not base:
        base = prefix
    suffix = uuid.uuid4().hex[:8]
    name = f"{base}-{suffix}"
    return name[:63]


def _safe_label_value(value: Optional[str]) -> str:
    if not value:
        return "unknown"
    value = value.lower()
    value = re.sub(r"[^a-z0-9-.]", "-", value)
    value = re.sub(r"-+", "-", value).strip("-.")
    return value[:63] or "unknown"


def _normalize_relative_path(path: str) -> str:
    rel = (path or "").strip()
    rel = rel.lstrip("/")
    if not rel:
        raise ValueError("File mount path cannot be empty")
    rel_path = Path(rel)
    if any(part == ".." for part in rel_path.parts):
        raise ValueError("File mount path cannot traverse directories")
    return str(rel_path)


def _load_kube_clients() -> Tuple[client.CoreV1Api, client.BatchV1Api, str]:
    source = "incluster"
    try:
        config.load_incluster_config()
    except ConfigException:
        config.load_kube_config()
        source = "kubeconfig"
    return client.CoreV1Api(), client.BatchV1Api(), source


def _build_env(env_cfg: Dict[str, Any]) -> list[client.V1EnvVar]:
    env_vars: list[client.V1EnvVar] = []
    for key, value in env_cfg.items():
        env_vars.append(client.V1EnvVar(name=str(key), value="" if value is None else str(value)))
    return env_vars


def _build_resources(resources_cfg: Optional[Dict[str, Any]]) -> Optional[client.V1ResourceRequirements]:
    if not resources_cfg:
        return None
    limits = resources_cfg.get("limits") if isinstance(resources_cfg, dict) else None
    requests = resources_cfg.get("requests") if isinstance(resources_cfg, dict) else None
    return client.V1ResourceRequirements(limits=limits, requests=requests)


def _create_config_map(
    core_api: client.CoreV1Api,
    namespace: str,
    name: str,
    labels: Dict[str, str],
    data: Dict[str, str],
) -> None:
    metadata = client.V1ObjectMeta(name=name, labels=labels)
    config_map = client.V1ConfigMap(metadata=metadata, data=data)
    core_api.create_namespaced_config_map(namespace=namespace, body=config_map)


def _create_job(
    batch_api: client.BatchV1Api,
    namespace: str,
    job_name: str,
    labels: Dict[str, str],
    annotations: Dict[str, str],
    runtime_cfg: Dict[str, Any],
    env_vars: list[client.V1EnvVar],
    command: list[str],
    args: list[str],
    service_account: Optional[str],
    resources_cfg: Optional[client.V1ResourceRequirements],
    config_map_name: Optional[str],
    volume_items: list[client.V1KeyToPath],
    remote_files: list[Dict[str, str]],
    jinja_env: Environment,
    rendered_context: Dict[str, Any],
) -> None:
    # Create shared emptyDir volume for scripts
    script_volume = client.V1Volume(
        name="noetl-script",
        empty_dir=client.V1EmptyDirVolumeSource(),
    )
    volume_mount = client.V1VolumeMount(name="noetl-script", mount_path=SCRIPT_MOUNT_PATH, read_only=False)

    volumes = [script_volume]
    init_containers = []

    # If we have a ConfigMap with small files, mount it separately
    if config_map_name and volume_items:
        configmap_volume = client.V1Volume(
            name="noetl-configmap",
            config_map=client.V1ConfigMapVolumeSource(
                name=config_map_name,
                items=volume_items,
            ),
        )
        volumes.append(configmap_volume)

        # Init container to copy ConfigMap files to emptyDir
        init_containers.append(
            client.V1Container(
                name="copy-configmap",
                image="busybox:1.36",
                command=["sh", "-c"],
                args=[f"cp /configmap/* {SCRIPT_MOUNT_PATH}/ 2>/dev/null || true && find {SCRIPT_MOUNT_PATH} -type f -exec chmod 755 {{}} \\;"],
                volume_mounts=[
                    client.V1VolumeMount(name="noetl-configmap", mount_path="/configmap", read_only=True),
                    volume_mount,
                ],
            )
        )

    # Init container to download remote files
    if remote_files:
        # Generate access tokens for files that need authentication
        auth_env_vars = []
        download_commands = []
        
        for idx, file_info in enumerate(remote_files):
            url = file_info["url"]
            path = file_info["path"]
            mode = file_info.get("mode", "644")
            auth_cred = file_info.get("auth")
            
            if auth_cred:
                # Use Jinja2 token() function to generate access token
                token_template = f"{{{{ token('{auth_cred}') }}}}"
                try:
                    access_token = render_template(jinja_env, token_template, rendered_context)
                    env_var_name = f"AUTH_TOKEN_{idx}"
                    auth_env_vars.append(client.V1EnvVar(name=env_var_name, value=access_token))
                    # Use curl for better OAuth support (install curl first)
                    download_commands.append(
                        f"apk add --no-cache curl > /dev/null 2>&1 && curl -f -H 'Authorization: Bearer ${env_var_name}' -o {SCRIPT_MOUNT_PATH}/{path} '{url}' && chmod {mode} {SCRIPT_MOUNT_PATH}/{path}"
                    )
                except Exception as e:
                    logger.warning("Failed to generate token for credential '%s': %s", auth_cred, e)
                    # Fall back to unauthenticated download
                    download_commands.append(f"wget -O {SCRIPT_MOUNT_PATH}/{path} '{url}' && chmod {mode} {SCRIPT_MOUNT_PATH}/{path}")
            else:
                # No auth needed
                download_commands.append(f"wget -O {SCRIPT_MOUNT_PATH}/{path} '{url}' && chmod {mode} {SCRIPT_MOUNT_PATH}/{path}")
        
        download_script = " && ".join(download_commands)
        # Use alpine image which has better wget support for headers
        init_containers.append(
            client.V1Container(
                name="download-files",
                image="alpine:3.19",
                command=["sh", "-c"],
                args=[download_script],
                env=auth_env_vars if auth_env_vars else None,
                volume_mounts=[volume_mount],
            )
        )

    # Main container
    container = client.V1Container(
        name="noetl-script",
        image=runtime_cfg.get("image"),
        command=command,
        args=args,
        env=env_vars,
        volume_mounts=[volume_mount],
        resources=resources_cfg,
    )

    pod_spec = client.V1PodSpec(
        restart_policy=runtime_cfg.get("restartPolicy", "Never"),
        service_account_name=service_account,
        containers=[container],
        init_containers=init_containers if init_containers else None,
        volumes=volumes,
    )

    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels=labels, annotations=annotations),
        spec=pod_spec,
    )

    job_spec = client.V1JobSpec(
        template=template,
        backoff_limit=runtime_cfg.get("backoffLimit", 0),
        ttl_seconds_after_finished=runtime_cfg.get("ttlSecondsAfterFinished"),
        active_deadline_seconds=runtime_cfg.get("activeDeadlineSeconds"),
    )

    job = client.V1Job(
        metadata=client.V1ObjectMeta(name=job_name, labels=labels, annotations=annotations),
        spec=job_spec,
    )

    batch_api.create_namespaced_job(namespace=namespace, body=job)


def _wait_for_job_completion(
    batch_api: client.BatchV1Api,
    namespace: str,
    job_name: str,
    timeout_seconds: int,
) -> client.V1Job:
    deadline = time.time() + timeout_seconds
    last_job = None
    while time.time() < deadline:
        job = batch_api.read_namespaced_job_status(name=job_name, namespace=namespace)
        last_job = job
        status = job.status
        if status and getattr(status, "succeeded", 0):
            return job
        conditions = getattr(status, "conditions", None) or []
        for condition in conditions:
            if condition.type == "Failed" and condition.status == "True":
                raise ContainerExecutionError(f"Job failed: {condition.reason or condition.type} - {condition.message or ''}")
        failed_count = getattr(status, "failed", 0) or 0
        backoff_limit = getattr(job.spec, "backoff_limit", None)
        if backoff_limit is not None and failed_count > backoff_limit:
            raise ContainerExecutionError("Job reached backoff limit")
        time.sleep(POLL_INTERVAL_SECONDS)
    raise TimeoutError(f"Timed out after {timeout_seconds}s waiting for job {job_name}")


def _extract_exit_code(pod: Any) -> Optional[int]:
    statuses = getattr(pod.status, "container_statuses", None) or []
    for status in statuses:
        state = getattr(status, "state", None)
        terminated = getattr(state, "terminated", None) if state else None
        if terminated and getattr(terminated, "exit_code", None) is not None:
            return terminated.exit_code
    return None


def _collect_pod_logs(
    core_api: client.CoreV1Api,
    namespace: str,
    job_name: str,
) -> Tuple[str, Optional[int], Optional[str]]:
    logs: list[str] = []
    exit_code: Optional[int] = None
    last_pod_name: Optional[str] = None
    try:
        pods = core_api.list_namespaced_pod(namespace=namespace, label_selector=f"job-name={job_name}")
    except ApiException as exc:
        logger.warning("Failed to list pods for job %s: %s", job_name, exc)
        return "", None, None

    for pod in pods.items:
        pod_name = getattr(pod.metadata, "name", "unknown")
        last_pod_name = pod_name
        try:
            pod_log = core_api.read_namespaced_pod_log(name=pod_name, namespace=namespace, timestamps=True)
            if pod_log:
                logs.append(f"--- pod/{pod_name} ---\n{pod_log.strip()}\n")
        except ApiException as exc:
            logs.append(f"--- pod/{pod_name} (log unavailable: {exc.reason}) ---\n")
        exit_code = _extract_exit_code(pod)
    combined = "\n".join(logs).strip()
    return combined, exit_code, last_pod_name


def _cleanup_resources(
    core_api: client.CoreV1Api,
    batch_api: client.BatchV1Api,
    namespace: str,
    job_name: Optional[str],
    config_map_name: Optional[str],
) -> None:
    if job_name:
        try:
            batch_api.delete_namespaced_job(
                name=job_name,
                namespace=namespace,
                body=client.V1DeleteOptions(propagation_policy="Foreground"),
            )
        except ApiException as exc:
            if exc.status != 404:
                logger.warning("Failed to delete job %s: %s", job_name, exc)
    if config_map_name:
        try:
            core_api.delete_namespaced_config_map(name=config_map_name, namespace=namespace)
        except ApiException as exc:
            if exc.status != 404:
                logger.warning("Failed to delete configmap %s: %s", config_map_name, exc)


def _datetime_to_iso(value: Optional[datetime.datetime]) -> Optional[str]:
    if not value:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=datetime.timezone.utc)
    return value.astimezone(datetime.timezone.utc).isoformat()


def execute_container_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    args: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Execute a shell script inside a Kubernetes Job."""

    rendered_context = dict(context or {})
    rendered_context.setdefault("args", args or task_config.get("args", {}))

    runtime_cfg = task_config.get("runtime")
    if not runtime_cfg:
        raise ValueError("Container task requires a 'runtime' block with provider/image settings")
    runtime_cfg = _render_dict(jinja_env, runtime_cfg, rendered_context, field="runtime")

    provider = (runtime_cfg.get("provider") or "kubernetes").lower()
    if provider != "kubernetes":
        raise ValueError(f"Unsupported container provider '{provider}'. Only 'kubernetes' is available")

    script_cfg = task_config.get("script")
    if not script_cfg:
        raise ValueError("Container task requires a 'script' block")
    validate_script_config(script_cfg)

    script_body = resolve_script(script_cfg, rendered_context, jinja_env)
    if not script_body.endswith("\n"):
        script_body = f"{script_body}\n"

    namespace = runtime_cfg.get("namespace") or context.get("kubernetes", {}).get("namespace") or "default"
    image = runtime_cfg.get("image")
    if not image:
        raise ValueError("Container runtime must specify an 'image'")

    script_mount_path = runtime_cfg.get("scriptMountPath", SCRIPT_MOUNT_PATH)
    script_filename = runtime_cfg.get("scriptFilename", SCRIPT_FILENAME)
    script_path = runtime_cfg.get("scriptPath", f"{script_mount_path.rstrip('/')}/{script_filename}")
    script_key = runtime_cfg.get("scriptKey") or script_filename
    script_relative_path = runtime_cfg.get("scriptRelativePath")
    if script_relative_path:
        script_relative_path = _normalize_relative_path(script_relative_path)
        script_path = f"{script_mount_path.rstrip('/')}/{script_relative_path}"
    else:
        prefix = f"{script_mount_path.rstrip('/')}/"
        if script_path.startswith(prefix):
            script_relative_path = script_path[len(prefix):] or script_filename
        else:
            script_relative_path = script_filename
            script_path = f"{script_mount_path.rstrip('/')}/{script_relative_path}"

    command_cfg = runtime_cfg.get("command")
    if command_cfg is None:
        command = ["/bin/bash", script_path]
    elif isinstance(command_cfg, str):
        command = [command_cfg]
    else:
        command = list(command_cfg)

    args_cfg = runtime_cfg.get("args")
    if args_cfg is None:
        cmd_args: list[str] = []
    elif isinstance(args_cfg, str):
        cmd_args = [args_cfg]
    else:
        cmd_args = list(args_cfg)

    env_cfg = {}
    for source in (task_config.get("env"), runtime_cfg.get("env")):
        if isinstance(source, dict):
            env_cfg.update(source)
    env_cfg = _render_dict(jinja_env, env_cfg, rendered_context, field="env")

    timeout_seconds = int(runtime_cfg.get("timeoutSeconds", DEFAULT_TIMEOUT_SECONDS))
    cleanup = runtime_cfg.get("cleanup", True)
    service_account = runtime_cfg.get("serviceAccountName") or runtime_cfg.get("service_account")
    annotations = runtime_cfg.get("annotations") if isinstance(runtime_cfg.get("annotations"), dict) else {}

    task_name = task_config.get("name", "container")
    job_name = runtime_cfg.get("jobName") or _sanitize_name(task_name, "noetl-job")
    config_map_name = runtime_cfg.get("configMapName") or _sanitize_name(task_name, "noetl-script")

    execution_id = context.get("execution_id") or context.get("job_id")
    labels = {
        "noetl.io/component": "container",
        "noetl.io/step": _safe_label_value(task_name),
        "noetl.io/execution": _safe_label_value(str(execution_id) if execution_id else None),
    }

    start_time = datetime.datetime.now(datetime.timezone.utc)
    task_id = str(uuid.uuid4())

    # ConfigMap for small files
    config_map_data: Dict[str, str] = {}
    volume_items: list[client.V1KeyToPath] = []
    
    # Remote files that will be downloaded by init container
    remote_files: list[Dict[str, str]] = []
    
    delivered_files: list[Dict[str, Any]] = []

    def _register_file_inline(key_name: str, rel_path: str, content: str, mode: int) -> None:
        """Register a file to be embedded in ConfigMap."""
        file_path = f"{script_mount_path.rstrip('/')}/{rel_path}"
        content_size = len(content.encode('utf-8'))
        config_map_data[key_name] = content
        volume_items.append(client.V1KeyToPath(key=key_name, path=rel_path, mode=mode))
        delivered_files.append({
            "source": "configmap",
            "key": key_name,
            "path": file_path,
            "mode": mode,
            "size": content_size,
        })

    def _register_file_remote(rel_path: str, download_url: str, mode: int, auth_credential: Optional[str] = None) -> None:
        """Register a file to be downloaded by init container."""
        file_path = f"{script_mount_path.rstrip('/')}/{rel_path}"
        file_entry = {
            "url": download_url,
            "path": rel_path,
            "mode": oct(mode)[2:],  # Convert to octal string like "755"
        }
        if auth_credential:
            file_entry["auth"] = auth_credential
        remote_files.append(file_entry)
        delivered_files.append({
            "source": "remote",
            "url": download_url,
            "path": file_path,
            "mode": mode,
            "auth": auth_credential,
        })

    # Always inline the main script since it's usually small
    _register_file_inline(script_key, _normalize_relative_path(script_relative_path), script_body, 0o755)

    # For additional files, use init container download for remote URIs
    additional_files_cfg = runtime_cfg.get("files") or []
    logger.info("Processing %d additional files", len(additional_files_cfg))
    for idx, file_cfg in enumerate(additional_files_cfg):
        rendered_file_cfg = _render_value(jinja_env, file_cfg, rendered_context)
        if not isinstance(rendered_file_cfg, dict):
            raise ValueError("Each runtime file entry must be a mapping with uri/source fields")
        validate_script_config(rendered_file_cfg)
        
        source_uri = rendered_file_cfg.get("uri")
        is_remote = source_uri and (source_uri.startswith('http://') or source_uri.startswith('https://') or source_uri.startswith('gs://'))
        
        logger.info("Processing file %s: uri=%s, is_remote=%s", idx, source_uri, is_remote)
        
        default_name = rendered_file_cfg.get("filename") or rendered_file_cfg.get("name")
        if not default_name:
            uri = source_uri or f"file-{idx}"
            default_name = Path(uri).name or f"file-{idx}"
        
        rel_path = rendered_file_cfg.get("relativePath") or rendered_file_cfg.get("mountPath") or default_name
        rel_path = _normalize_relative_path(rel_path)
        mode = int(rendered_file_cfg.get("mode", 0o644))
        
        if is_remote:
            # Download via init container for remote files
            logger.info("Registering remote file: %s -> %s", source_uri, rel_path)
            download_url = source_uri
            if source_uri.startswith('gs://'):
                bucket_and_path = source_uri[5:]  # Remove 'gs://'
                download_url = f"https://storage.googleapis.com/{bucket_and_path}"
            
            # Extract auth credential if specified
            source_cfg = rendered_file_cfg.get('source', {})
            auth_credential = source_cfg.get('auth') if isinstance(source_cfg, dict) else None
            _register_file_remote(rel_path, download_url, mode, auth_credential)
        else:
            # Inline small local files in ConfigMap
            logger.info("Inlining file in ConfigMap: %s -> %s", source_uri, rel_path)
            file_body = resolve_script(rendered_file_cfg, rendered_context, jinja_env)
            if not file_body.endswith("\n"):
                file_body = f"{file_body}\n"
            key_name = rendered_file_cfg.get("configMapKey") or default_name
            _register_file_inline(key_name, rel_path, file_body, mode)

    # Log file distribution summary
    total_configmap_size = sum(len(v.encode('utf-8')) for v in config_map_data.values())
    logger.info("File distribution: ConfigMap=%d bytes (%d files), Remote=%d files", 
                total_configmap_size, len(config_map_data), len(remote_files))

    env_vars = _build_env(env_cfg)
    if not any(var.name == "NOETL_SCRIPT_PATH" for var in env_vars):
        env_vars.append(client.V1EnvVar(name="NOETL_SCRIPT_PATH", value=script_path))
    resources_cfg = _build_resources(runtime_cfg.get("resources"))

    core_api, batch_api, kube_source = _load_kube_clients()

    if log_event_callback:
        log_event_callback(
            "task_start",
            task_id,
            task_name,
            "container",
            "running",
            0,
            context,
            None,
            {"provider": provider, "namespace": namespace, "image": image},
            None,
        )

    job_created = False
    config_map_created = False
    config_map_name_or_none = None
    try:
        # Only create ConfigMap if we have small files to embed
        if config_map_data:
            _create_config_map(core_api, namespace, config_map_name, labels, config_map_data)
            config_map_created = True
            config_map_name_or_none = config_map_name
        
        _create_job(
            batch_api,
            namespace,
            job_name,
            labels,
            annotations,
            runtime_cfg,
            env_vars,
            command,
            cmd_args,
            service_account,
            resources_cfg,
            config_map_name_or_none,
            volume_items,
            remote_files,
            jinja_env,
            rendered_context,
        )
        job_created = True

        job_obj = _wait_for_job_completion(batch_api, namespace, job_name, timeout_seconds)
        logs, exit_code, pod_name = _collect_pod_logs(core_api, namespace, job_name)

        completion = datetime.datetime.now(datetime.timezone.utc)
        duration = (completion - start_time).total_seconds()
        data = {
            "job_name": job_name,
            "namespace": namespace,
            "provider": provider,
            "config_map": config_map_name_or_none,
            "exit_code": exit_code,
            "logs": logs,
            "pod_name": pod_name,
            "start_time": _datetime_to_iso(getattr(job_obj.status, "start_time", None)),
            "completion_time": _datetime_to_iso(getattr(job_obj.status, "completion_time", None)),
            "kube_auth": kube_source,
            "files": delivered_files,
        }
        if log_event_callback:
            log_event_callback(
                "task_success",
                task_id,
                task_name,
                "container",
                "success",
                duration,
                context,
                None,
                data,
                None,
            )
        return {
            "id": task_id,
            "status": "success",
            "data": data,
        }
    except Exception as exc:
        logs, exit_code, pod_name = _collect_pod_logs(core_api, namespace, job_name)
        completion = datetime.datetime.now(datetime.timezone.utc)
        duration = (completion - start_time).total_seconds()
        error_msg = str(exc)
        error_payload = {
            "job_name": job_name,
            "namespace": namespace,
            "config_map": config_map_name_or_none,
            "pod_name": pod_name,
            "exit_code": exit_code,
            "logs": logs,
            "kube_auth": kube_source,
            "files": delivered_files,
        }
        if log_event_callback:
            log_event_callback(
                "task_error",
                task_id,
                task_name,
                "container",
                "error",
                duration,
                context,
                None,
                {"error": error_msg, **error_payload},
                None,
            )
        return {
            "id": task_id,
            "status": "error",
            "error": error_msg,
            "data": error_payload,
        }
    finally:
        if cleanup:
            try:
                _cleanup_resources(
                    core_api,
                    batch_api,
                    namespace,
                    job_name if job_created else None,
                    config_map_name if config_map_created else None,
                )
            except Exception as cleanup_exc:  # pragma: no cover - defensive
                logger.warning("Cleanup failed for job %s: %s", job_name, cleanup_exc)


__all__ = ["execute_container_task"]
