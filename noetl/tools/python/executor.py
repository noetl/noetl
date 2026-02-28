"""
Python action executor for NoETL jobs.
"""

import asyncio
import uuid
import datetime
import os
import json
import inspect
import importlib.util
from typing import Dict, Any, Optional, Callable
try:
    from jinja2 import Environment, BaseLoader
except ImportError:
    Environment, BaseLoader = None, None

import ast
import base64
import tempfile
try:
    import httpx
except ImportError:
    httpx = None

from noetl.core.logger import setup_logger
from noetl.core.script import resolve_script
from noetl.worker.auth_resolver import resolve_auth

logger = setup_logger(__name__, include_location=True)

def _size_hint(value: Any) -> int:
    try:
        return len(json.dumps(value, default=str))
    except Exception:
        return len(str(value))


def _inject_auth_credentials(
    task_config: Dict[str, Any],
    args: Optional[Dict[str, Any]],
    context: Dict[str, Any]
) -> Dict[str, str]:
    """
    Inject authentication credentials as environment variables.
    
    Supports GCS, S3, and other cloud providers by setting appropriate
    environment variables that standard SDKs auto-discover.
    
    Returns dict of original environment values for restoration.
    """
    # Get auth config from task_config or args
    auth_config = task_config.get('auth') or (args or {}).get('auth')
    if not auth_config or auth_config == {}:
        return {}
    
    logger.debug(
        "PYTHON.AUTH: Resolving auth config keys=%s",
        list(auth_config.keys()) if isinstance(auth_config, dict) else type(auth_config).__name__,
    )
    
    # Create a Jinja environment for auth resolution
    jinja_env = Environment(autoescape=False)
    
    # Resolve credentials using the unified auth system
    try:
        mode, resolved_items = resolve_auth(auth_config, jinja_env, context)
        logger.debug(f"PYTHON.AUTH: Resolved auth mode={mode}, items={len(resolved_items)}")
    except Exception as e:
        logger.error(f"PYTHON.AUTH: Failed to resolve auth: {e}", exc_info=True)
        return {}
    
    original_env = {}
    
    # Inject credentials as environment variables based on auth service/type
    for alias, auth_item in resolved_items.items():
        service = auth_item.service or ''
        payload = auth_item.payload or {}
        
        logger.debug(f"PYTHON.AUTH: Processing {alias} (service={service})")
        
        if service in ('gcs', 'gcs_hmac', 'gcs_service_account'):
            # Google Cloud Storage credentials
            if 'service_account_json' in payload:
                # Write service account JSON to temp file
                import tempfile
                fd, path = tempfile.mkstemp(suffix='.json', prefix='gcs_sa_')
                os.write(fd, json.dumps(payload['service_account_json']).encode())
                os.close(fd)
                
                original_env['GOOGLE_APPLICATION_CREDENTIALS'] = os.environ.get('GOOGLE_APPLICATION_CREDENTIALS', '')
                os.environ['GOOGLE_APPLICATION_CREDENTIALS'] = path
                logger.debug("PYTHON.AUTH: Set GOOGLE_APPLICATION_CREDENTIALS temp file")
                
            elif service == 'gcs_hmac' and 'access_key_id' in payload:
                # HMAC credentials for GCS S3 compatibility
                original_env['AWS_ACCESS_KEY_ID'] = os.environ.get('AWS_ACCESS_KEY_ID', '')
                original_env['AWS_SECRET_ACCESS_KEY'] = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
                os.environ['AWS_ACCESS_KEY_ID'] = payload['access_key_id']
                os.environ['AWS_SECRET_ACCESS_KEY'] = payload['secret_access_key']
                logger.debug("PYTHON.AUTH: Set AWS_ACCESS_KEY_ID for GCS HMAC")
        
        elif service in ('s3', 's3_hmac', 'aws'):
            # AWS S3 credentials
            if 'access_key_id' in payload:
                original_env['AWS_ACCESS_KEY_ID'] = os.environ.get('AWS_ACCESS_KEY_ID', '')
                original_env['AWS_SECRET_ACCESS_KEY'] = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
                os.environ['AWS_ACCESS_KEY_ID'] = payload['access_key_id']
                os.environ['AWS_SECRET_ACCESS_KEY'] = payload['secret_access_key']
                
                if 'region' in payload:
                    original_env['AWS_DEFAULT_REGION'] = os.environ.get('AWS_DEFAULT_REGION', '')
                    os.environ['AWS_DEFAULT_REGION'] = payload['region']
                
                logger.debug("PYTHON.AUTH: Set AWS credentials")
        
        elif service in ('azure', 'azure_storage'):
            # Azure Storage credentials
            if 'connection_string' in payload:
                original_env['AZURE_STORAGE_CONNECTION_STRING'] = os.environ.get('AZURE_STORAGE_CONNECTION_STRING', '')
                os.environ['AZURE_STORAGE_CONNECTION_STRING'] = payload['connection_string']
                logger.debug("PYTHON.AUTH: Set AZURE_STORAGE_CONNECTION_STRING")
    
    return original_env


def _restore_environment(original_env: Dict[str, str]) -> None:
    """Restore original environment variables."""
    for key, value in original_env.items():
        if value:
            os.environ[key] = value
        else:
            os.environ.pop(key, None)


def _coerce_param(value: Any) -> Any:
    """Best-effort coercion of stringified literals into Python objects.
    - Parses dict/list literals using ast.literal_eval to handle single quotes.
    - Falls back to JSON when appropriate
    - Leaves other types as-is
    """
    try:
        if isinstance(value, str):
            s = value.strip()
            if (s.startswith('{') and s.endswith('}')) or (s.startswith('[') and s.endswith(']')):
                try:
                    return json.loads(s)
                except Exception:
                    try:
                        return ast.literal_eval(s)
                    except Exception:
                        return value
        return value
    except Exception:
        return value


def _build_call_kwargs(
    func_signature: inspect.Signature,
    provided_args: Dict[str, Any],
    context: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Resolve function arguments from rendered args and context."""
    context = context or {}
    if not isinstance(context, dict):
        context = {}

    context_input = context.get("input")
    if not isinstance(context_input, dict):
        context_input = {}
    context_data = context.get("data")
    if not isinstance(context_data, dict):
        context_data = {}

    used_keys = set()
    call_kwargs: Dict[str, Any] = {}

    def _lookup(name: str) -> Any:
        if name in provided_args:
            used_keys.add(name)
            return provided_args[name]
        if name in context_input:
            used_keys.add(name)
            return context_input[name]
        if name in context_data:
            used_keys.add(name)
            return context_data[name]
        if name in context:
            used_keys.add(name)
            return context[name]
        raise TypeError(
            f"Missing required argument '{name}' for python task. Provide it via args or context."
        )

    for param in func_signature.parameters.values():
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            raise TypeError("*args are not supported in python tasks")
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            continue  # handled later
        if param.name == "context":
            call_kwargs["context"] = context
            continue
        if param.kind == inspect.Parameter.KEYWORD_ONLY or param.kind == inspect.Parameter.POSITIONAL_OR_KEYWORD:
            if param.default != inspect.Parameter.empty:
                try:
                    call_kwargs[param.name] = _lookup(param.name)
                except TypeError:
                    call_kwargs[param.name] = param.default
            else:
                call_kwargs[param.name] = _lookup(param.name)

    # Handle **kwargs by merging remaining entries
    if any(
        param.kind == inspect.Parameter.VAR_KEYWORD
        for param in func_signature.parameters.values()
    ):
        merged_kwargs: Dict[str, Any] = {}
        for source in (context_input, context_data, provided_args, context):
            if isinstance(source, dict):
                for key, value in source.items():
                    if key not in call_kwargs and key not in merged_kwargs:
                        merged_kwargs[key] = value
        call_kwargs.update(merged_kwargs)

    return call_kwargs


def _build_call_kwargs(
    signature: inspect.Signature, provided_args: Dict[str, Any], context: Dict[str, Any]
) -> Dict[str, Any]:
    """Resolve function arguments from provided args and execution context."""
    if context is None:
        context = {}

    context_input = context.get("input") if isinstance(context, dict) else {}
    if not isinstance(context_input, dict):
        context_input = {}
    context_data = context.get("data") if isinstance(context, dict) else {}
    if not isinstance(context_data, dict):
        context_data = {}

    call_kwargs: Dict[str, Any] = {}
    var_kwargs = False

    def _resolve(name: str) -> Any:
        if name in provided_args:
            return provided_args[name]
        if name in context_input:
            return context_input[name]
        if name in context_data:
            return context_data[name]
        if isinstance(context, dict) and name in context:
            return context[name]
        raise TypeError(
            f"Missing required argument '{name}' for Python task. Provide it via args or context."
        )

    for param in signature.parameters.values():
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            raise TypeError("*args are not supported in python tasks")
        if param.kind == inspect.Parameter.VAR_KEYWORD:
            var_kwargs = True
            continue
        if param.name == "context":
            call_kwargs["context"] = context
            continue
        try:
            value = _resolve(param.name)
            call_kwargs[param.name] = value
        except TypeError as err:
            if param.default != inspect.Parameter.empty:
                continue
            raise err

    if var_kwargs:
        merged_kwargs: Dict[str, Any] = {}
        for source in (context_input, context_data, provided_args):
            for key, value in source.items():
                if key not in call_kwargs and key not in merged_kwargs:
                    merged_kwargs[key] = value
        call_kwargs.update(merged_kwargs)

    return call_kwargs


async def execute_python_task_async(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    args: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Execute a Python task asynchronously."""
    import time
    t_p_start = time.perf_counter()
    start_time = datetime.datetime.now()
    logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Entry at {start_time}")

    task_id = str(uuid.uuid4())
    task_name = task_config.get('name', 'unnamed_python_task')
    logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Task ID={task_id}, name={task_name}")
    
    # Inject credentials as environment variables if auth is provided
    original_env = {}
    if 'auth' in task_config or 'auth' in (args or {}):
        original_env = _inject_auth_credentials(task_config, args, context)
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Injected auth credentials into environment")

    # Extract args from task_config if not provided as parameter
    # This allows 'args' field in YAML to be used
    if not args:
        args = task_config.get('args', {})
        logger.debug(
            "PYTHON.EXECUTE_PYTHON_TASK: Extracted args from task_config (keys=%s)",
            list(args.keys()) if isinstance(args, dict) else [],
        )
    else:
        # Merge task_config args with provided args (provided args take precedence)
        config_args = task_config.get('args', {})
        if config_args:
            merged_args = {**config_args, **args}
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Merged config args with provided args")
            args = merged_args
    
    # Use args if provided, otherwise empty dict
    args = args or {}
    args_meta = {
        "arg_count": len(args) if isinstance(args, dict) else 0,
        "arg_keys": sorted(list(args.keys()))[:25] if isinstance(args, dict) else [],
    }

    try:
        logger.debug(
            "PYTHON.EXECUTE_PYTHON_TASK: config_keys=%s args_keys=%s context_key_count=%s",
            list(task_config.keys()),
            list(args.keys()) if isinstance(args, dict) else [],
            len((context or {}).keys()) if isinstance(context, dict) else 0,
        )

        # Get and decode the code (priority: script > code_b64 > code)
        code = None
        
        # Priority 1: External script
        if 'script' in task_config:
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Resolving external script")
            code = resolve_script(task_config['script'], context, jinja_env)
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Resolved script from {task_config['script']['source']['type']}, length={len(code)} chars")
        
        # Priority 2: Base64 encoded code
        elif 'code_b64' in task_config:
            code = base64.b64decode(task_config['code_b64']).decode('utf-8')
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Decoded base64 code, length={len(code)} chars")
        elif 'code_base64' in task_config:
            code = base64.b64decode(task_config['code_base64']).decode('utf-8')
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Decoded base64 code, length={len(code)} chars")
        
        # Priority 3: Inline code
        elif 'code' in task_config:
            code = task_config['code']
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Using inline code, length={len(code)} chars")

        if not code:
            if 'code' in task_config:
                raise ValueError("Empty code provided.")
            else:
                raise ValueError("No code provided. Expected 'script', 'code_b64', 'code_base64', or inline 'code' string in task configuration")

        # Prepend library imports if specified via 'libs'
        libs_config = task_config.get('libs')
        if libs_config:
            import_statements = []
            modules_to_validate = []
            
            if isinstance(libs_config, dict):
                # Dict format: {"pd": "pandas", "storage": "google.cloud.storage", "os": "os"}
                # Key is the alias (what you use in code), value is the module to import
                for alias, module_path in libs_config.items():
                    if isinstance(module_path, str):
                        if alias == module_path:
                            # Same name: import os
                            import_statements.append(f"import {module_path}")
                            modules_to_validate.append(module_path)
                        else:
                            # Different alias: import pandas as pd
                            import_statements.append(f"import {module_path} as {alias}")
                            modules_to_validate.append(module_path)
                    elif isinstance(module_path, dict):
                        # Extended format for "from X import Y"
                        # e.g., {"storage": {"from": "google.cloud", "import": "storage"}}
                        from_module = module_path.get('from')
                        import_name = module_path.get('import')
                        if from_module and import_name:
                            if alias == import_name:
                                # from google.cloud import storage
                                import_statements.append(f"from {from_module} import {import_name}")
                                modules_to_validate.append(f"{from_module}.{import_name}")
                            else:
                                # from google.cloud import storage as gcs
                                import_statements.append(f"from {from_module} import {import_name} as {alias}")
                                modules_to_validate.append(f"{from_module}.{import_name}")
                        else:
                            logger.warning(f"PYTHON.EXECUTE_PYTHON_TASK: Invalid dict format for '{alias}': {module_path}")
                    else:
                        logger.warning(f"PYTHON.EXECUTE_PYTHON_TASK: Unsupported config for '{alias}': {module_path}")
                
                # Validate all modules exist before execution
                # Skip validation if NOETL_SKIP_LIB_VALIDATION=true (for performance)
                if os.getenv("NOETL_SKIP_LIB_VALIDATION") != "true":
                    missing_modules = []
                    for module_name in modules_to_validate:
                        # Check top-level module first (e.g., 'google' for 'google.cloud.storage')
                        top_level = module_name.split('.')[0]
                        spec = importlib.util.find_spec(top_level)
                        if spec is None:
                            missing_modules.append(module_name)
                            logger.error(f"PYTHON.LIBS_VALIDATION: Module '{module_name}' not found (top-level '{top_level}' missing)")
                    
                    if missing_modules:
                        raise ImportError(
                            f"Required libraries not installed in noetl container: {', '.join(missing_modules)}. "
                            f"Add these packages to pyproject.toml dependencies or use pre-installed libraries."
                        )
                    
                    logger.info(f"PYTHON.LIBS_VALIDATION: All {len(modules_to_validate)} libraries validated successfully")
                
                # Prepend imports to code
                imports_block = '\n'.join(import_statements)
                code = f"{imports_block}\n\n{code}"
                logger.info(f"PYTHON.EXECUTE_PYTHON_TASK: Prepended {len(import_statements)} library imports")
                logger.debug("PYTHON.EXECUTE_PYTHON_TASK: Imports block prepared (len=%s)", len(imports_block))
            else:
                logger.warning(f"PYTHON.EXECUTE_PYTHON_TASK: 'libs' must be a dict, got {type(libs_config)}")

        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Python code length={len(code)} chars")

        event_id = None
        if log_event_callback:
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Writing task_start event log")
            event_id = log_event_callback(
                'task_start', task_id, task_name, 'python',
                'in_progress', 0, context, None,
                args_meta, None
            )
            logger.debug(f"PYTHON: Task start event_id={event_id} | setting up execution globals")
        
        # Import commonly used utilities from noetl.core.common
        from noetl.core.common import (
            get_val,
            make_serializable,
            now_utc,
            format_iso8601,
            deep_merge,
        )
        
        exec_globals = {
            '__builtins__': __builtins__,
            'context': context,
            'os': os,
            'json': json,
            'datetime': datetime,
            'uuid': uuid,
            # Add noetl.core.common utilities
            'get_val': get_val,
            'make_serializable': make_serializable,
            'now_utc': now_utc,
            'format_iso8601': format_iso8601,
            'deep_merge': deep_merge,
        }
        
        # Inject args into globals (render and coerce first)
        if args:
            rendered_args = {}
            for k, v in args.items():
                # Check if value is a TaskResultProxy object (has _data attribute)
                if hasattr(v, '_data'):
                    logger.info(f"PYTHON.INJECT: Unwrapping TaskResultProxy for key={k}")
                    rendered_args[k] = v._data
                # Check if value is dict or list (already resolved data structures)
                elif isinstance(v, (dict, list)):
                    logger.info(f"PYTHON.INJECT: Using dict/list directly for key={k}, type={type(v).__name__}")
                    rendered_args[k] = v
                elif isinstance(v, str):
                    # Check if this is a simple variable reference like "{{ result }}" or "{{ data }}"
                    # If so, try to get the actual value from context instead of string rendering
                    stripped = v.strip()
                    if stripped.startswith('{{') and stripped.endswith('}}'):
                        var_name = stripped[2:-2].strip()
                        # Simple variable reference without dots, filters, or operators
                        if ' ' not in var_name and '.' not in var_name and '|' not in var_name:
                            if var_name in (context or {}):
                                logger.debug(
                                    "PYTHON.INJECT: Using context value directly for key=%s from var=%s type=%s",
                                    k,
                                    var_name,
                                    type(context[var_name]).__name__,
                                )
                                rendered_args[k] = context[var_name]
                                continue
                    
                    # Otherwise, render as template
                    try:
                        logger.debug(f"PYTHON.INJECT: Rendering template for key={k}")
                        tmpl = jinja_env.from_string(v)
                        rendered = tmpl.render(context or {})
                        logger.debug(
                            "PYTHON.INJECT: Rendered result for key=%s type=%s size=%sB",
                            k,
                            type(rendered).__name__,
                            _size_hint(rendered),
                        )
                        rendered_args[k] = rendered
                    except Exception as render_ex:
                        logger.exception(f"PYTHON.INJECT: Exception rendering key={k}: {render_ex}")
                        rendered_args[k] = v
                else:
                    rendered_args[k] = v
            
            # Coerce and inject into exec_globals
            for k, v in rendered_args.items():
                coerced = _coerce_param(v)
                exec_globals[k] = coerced
                logger.debug(f"PYTHON.INJECT: Injected {k} type={type(coerced).__name__}")
        
        # Auto-inject 'data' from context if not in args (for sink execution)
        logger.debug(
            "PYTHON.AUTO_INJECT: context_key_count=%s data_in_exec_globals=%s",
            len(context.keys()) if isinstance(context, dict) else 0,
            ('data' in exec_globals),
        )
        if context and 'data' not in exec_globals:
            logger.debug(
                "PYTHON.AUTO_INJECT: context_has_data=%s context_has_result=%s",
                ('data' in context),
                ('result' in context),
            )
            if 'data' in context:
                exec_globals['data'] = context['data']
                logger.debug("PYTHON.INJECT: Auto-injected 'data' from context (type=%s)", type(context['data']).__name__)
            elif 'result' in context:
                exec_globals['data'] = context['result']
                logger.debug("PYTHON.INJECT: Auto-injected 'data' from context['result'] (type=%s)", type(context['result']).__name__)
        
        logger.debug(
            "PYTHON.EXECUTE_PYTHON_TASK: Execution globals prepared count=%s",
            len(exec_globals.keys()),
        )

        exec_locals = {}
        logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Executing Python code")
        
        # Execute code in a thread pool to avoid blocking the event loop
        # Note: exec() is synchronous and can be slow or hang
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: exec(code, exec_globals, exec_locals))
        
        logger.debug(
            "PYTHON.EXECUTE_PYTHON_TASK: Execution completed locals_count=%s",
            len(exec_locals.keys()),
        )

        # Check if code defines main() function (legacy support)
        if 'main' in exec_locals and callable(exec_locals['main']):
            logger.info(f"PYTHON.EXECUTE_PYTHON_TASK: Legacy main() function detected, executing it")
            # Render Jinja templates in args against context
            rendered_args = {}
            try:
                for k, v in args.items():
                    # Check if value is a TaskResultProxy object (has _data attribute)
                    if hasattr(v, '_data'):
                        logger.info(f"PYTHON.RENDER: Unwrapping TaskResultProxy for key={k}")
                        rendered_args[k] = v._data
                    # Check if value is dict or list (already resolved data structures)
                    elif isinstance(v, (dict, list)):
                        logger.debug(f"PYTHON.RENDER: Using dict/list directly for key={k}, type={type(v).__name__}")
                        rendered_args[k] = v
                    elif isinstance(v, str):
                        try:
                            logger.debug(f"PYTHON.RENDER: Rendering template for key={k}")
                            tmpl = jinja_env.from_string(v)
                            rendered = tmpl.render(context or {})
                            logger.debug(
                                "PYTHON.RENDER: Rendered result for key=%s type=%s size=%sB",
                                k,
                                type(rendered).__name__,
                                _size_hint(rendered),
                            )
                            rendered_args[k] = rendered
                        except Exception as render_ex:
                            logger.exception(f"PYTHON.RENDER: Exception rendering key={k}: {render_ex}")
                            rendered_args[k] = v
                    else:
                        rendered_args[k] = v
            except Exception:
                rendered_args = args

            # Coerce string literals to Python objects (e.g., "30" -> 30)
            coerced_args = {}
            try:
                for k, v in rendered_args.items():
                    coerced = _coerce_param(v)
                    logger.debug(
                        "PYTHON.COERCE: key=%s type_before=%s type_after=%s",
                        k,
                        type(v).__name__,
                        type(coerced).__name__,
                    )
                    coerced_args[k] = coerced
            except Exception as coerce_ex:
                logger.exception(f"PYTHON.COERCE: Exception: {coerce_ex}")
                coerced_args = rendered_args

            # Call main function as async coroutine
            main_func = exec_locals["main"]
            func_signature = inspect.signature(main_func)
            call_kwargs = _build_call_kwargs(func_signature, coerced_args, context)
            logger.info(
                f"PYTHON.CALL: Executing main with kwargs: {list(call_kwargs.keys())}"
            )
            result_data = await _invoke_main(main_func, call_kwargs)

            t_p_end = time.perf_counter()
            logger.info(f"[PERF] Python execution for {task_name} took {t_p_end - t_p_start:.4f}s")

            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            if log_event_callback:
                log_event_callback(
                    'task_complete', task_id, task_name, 'python',
                    'success', duration, context, result_data,
                    args_meta, event_id
                )

            return {
                'id': task_id,
                'status': 'success',
                'data': result_data
            }
        else:
            # Pure code execution mode: capture 'result' variable from exec_locals
            logger.info("PYTHON.EXECUTE_PYTHON_TASK: Pure code execution mode (no main() function)")
            
            # Check for explicit 'result' variable
            if 'result' in exec_locals:
                result_data = exec_locals['result']
                logger.info(f"PYTHON.EXECUTE_PYTHON_TASK: Captured 'result' variable, type={type(result_data).__name__}")
                logger.debug(
                    "PYTHON.EXECUTE_PYTHON_TASK: Result size=%sB",
                    _size_hint(result_data),
                )
            else:
                # No explicit result - return success status with available locals
                logger.warning("PYTHON.EXECUTE_PYTHON_TASK: No 'result' variable found, returning success status")
                non_builtins = {k: v for k, v in exec_locals.items() if not k.startswith('__')}
                result_data = {
                    'status': 'success',
                    'message': 'Code executed without explicit result variable',
                    'locals_count': len(non_builtins),
                    'locals_keys': list(non_builtins.keys())
                }

            t_p_end = time.perf_counter()
            logger.info(f"[PERF] Python execution for {task_name} took {t_p_end - t_p_start:.4f}s")

            end_time = datetime.datetime.now()
            duration = (end_time - start_time).total_seconds()

            if log_event_callback:
                log_event_callback(
                    'task_complete', task_id, task_name, 'python',
                    'success', duration, context, result_data,
                    args_meta, event_id
                )

            return {
                'id': task_id,
                'status': 'success',
                'data': result_data
            }

    except Exception as e:
        error_msg = str(e)
        logger.exception(f"PYTHON.EXECUTE_PYTHON_TASK: Exception - {error_msg}", exc_info=True)

        end_time = datetime.datetime.now()
        duration = (end_time - start_time).total_seconds()

        if log_event_callback:
            log_event_callback(
                'task_error', task_id, task_name, 'python',
                'error', duration, context, None,
                {"error": error_msg, **args_meta}, None
            )

        return {
            'id': task_id,
            'status': 'error',
            'error': error_msg
        }
    
    finally:
        # Restore original environment variables
        if original_env:
            _restore_environment(original_env)
            logger.debug(f"PYTHON.EXECUTE_PYTHON_TASK: Restored original environment")


def execute_python_task(
    task_config: Dict[str, Any],
    context: Dict[str, Any],
    jinja_env: Environment,
    args: Optional[Dict[str, Any]] = None,
    log_event_callback: Optional[Callable] = None,
) -> Dict[str, Any]:
    """Backward-compatible synchronous entry point."""
    return asyncio.run(
        execute_python_task_async(
            task_config, context, jinja_env, args, log_event_callback
        )
    )
__all__ = ['execute_python_task', 'execute_python_task_async']


async def _invoke_main(main_func: Callable, kwargs: Dict[str, Any]) -> Any:
    """Execute user-provided main function, supporting both async and sync."""
    if inspect.iscoroutinefunction(main_func):
        return await main_func(**kwargs)

    logger.debug("PYTHON.CALL: main is synchronous; running in default executor")
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(None, lambda: main_func(**kwargs))
