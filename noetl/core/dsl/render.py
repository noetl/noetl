



import re
import json
import base64
from typing import Any, Dict, List, Union, Optional
from jinja2 import Environment, meta, StrictUndefined, BaseLoader, Undefined
from noetl.core.logger import log_error
from noetl.core.common import DateTimeEncoder

from noetl.core.logger import setup_logger
logger = setup_logger(__name__, include_location=True)


def _resolve_reference_sync(reference: Any) -> Any:
    """Resolve a TempStore reference synchronously for use in Jinja2 rendering.

    Uses asyncio.run_coroutine_threadsafe or a new event loop to bridge
    the sync Jinja2 context with async TempStore.resolve().
    Returns None on any failure (template rendering should handle gracefully).
    """
    if not isinstance(reference, dict):
        return None
    kind = reference.get("kind")
    if kind not in ("temp_ref", "result_ref"):
        return None
    try:
        import asyncio
        from noetl.core.storage.result_store import default_store

        # Try to schedule on the running event loop
        try:
            loop = asyncio.get_running_loop()
            # We're inside an async context but called synchronously by Jinja2.
            # Use a thread to run the coroutine without blocking the event loop.
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(asyncio.run, default_store.resolve(reference))
                return future.result(timeout=5.0)
        except RuntimeError:
            # No running loop — safe to use asyncio.run directly
            return asyncio.run(default_store.resolve(reference))
    except Exception as exc:
        logger.debug("[LAZY-RESOLVE] Failed to resolve reference: %s", exc)
        return None


class TaskResultProxy:
    """Lightweight proxy allowing ``{{ step.field }}`` attribute access on dict results.

    When accessing a field that doesn't exist in the dict but the dict has a
    ``reference`` key, resolves from TempStore (shared cache) on demand.
    This supports the data plane separation: step results carry compact
    {status, reference, context} envelopes, and .rows is fetched from
    shared storage only when actually accessed in a template.

    Defined at module level to avoid class re-creation on every render call.
    """

    __slots__ = ("_data", "_name", "_resolved_cache")

    def __init__(self, data: dict, name: str = ""):
        object.__setattr__(self, "_data", data)
        object.__setattr__(self, "_name", name)
        object.__setattr__(self, "_resolved_cache", {})

    def __getattr__(self, name: str):
        data = object.__getattribute__(self, "_data")
        if name == "data" and name not in data:
            return self
        if name == "is_defined":
            return True
        def _wrap(val: Any):
            # Wrap nested dicts so chained attribute access works (e.g., iter.batch.offset)
            if isinstance(val, dict):
                return TaskResultProxy(val, name=name)
            return val
        if isinstance(data, dict) and name in data:
            return _wrap(data[name])

        # On-demand resolution from shared cache (TempStore):
        # When the dict has a reference but not the requested field,
        # resolve the reference and cache the result for this proxy instance.
        if isinstance(data, dict) and "reference" in data and name not in data:
            resolved_cache = object.__getattribute__(self, "_resolved_cache")
            if "_resolved_data" not in resolved_cache:
                resolved_data = _resolve_reference_sync(data.get("reference"))
                resolved_cache["_resolved_data"] = resolved_data
            resolved = resolved_cache.get("_resolved_data")
            if resolved is not None:
                # The resolved data is typically a list (rows) or dict
                if isinstance(resolved, list) and name == "rows":
                    return resolved
                if isinstance(resolved, dict) and name in resolved:
                    return _wrap(resolved[name])
                # Build a data-view dict for .row_count, .columns etc
                if isinstance(resolved, list):
                    data_view = {"rows": resolved, "row_count": len(resolved)}
                    if name in data_view:
                        return data_view[name]

        raise AttributeError(f"'{type(data).__name__}' object has no attribute '{name}'")

    def __getitem__(self, key):
        try:
            data = object.__getattribute__(self, "_data")
            def _wrap(val: Any):
                if isinstance(val, dict):
                    return TaskResultProxy(val, name=str(key))
                return val
            if key in data:
                return _wrap(data[key])
            return data[key]
        except Exception as e:
            raise KeyError(key) from e

    def get(self, key, default=None):
        data = object.__getattribute__(self, "_data")
        if isinstance(data, dict):
            return data.get(key, default)
        return default

    def __str__(self):
        return json.dumps(object.__getattribute__(self, "_data"), default=str)

    def __repr__(self):
        return json.dumps(object.__getattribute__(self, "_data"), default=str)

    def __contains__(self, key):
        data = object.__getattribute__(self, "_data")
        return key in data

    def __iter__(self):
        return iter(object.__getattribute__(self, "_data"))

    def __len__(self):
        return len(object.__getattribute__(self, "_data"))

    def items(self):
        return object.__getattribute__(self, "_data").items()

    def keys(self):
        return object.__getattribute__(self, "_data").keys()

    def values(self):
        return object.__getattribute__(self, "_data").values()


def _handle_undefined_values(value: Any) -> Any:
    """Convert Undefined values to None to prevent JSON serialization errors.
    Optimized to avoid deep-copying large JSON structures (like HTTP responses)
    which never contain Jinja Undefined objects.
    """
    if value is None or type(value) in (str, int, float, bool):
        return value
    if isinstance(value, Undefined):
        return None
        
    # Fast path: TaskResultProxy doesn't contain Undefined
    if type(value).__name__ == 'TaskResultProxy':
        return value

    if isinstance(value, dict):
        # Shallow scan to avoid rebuilding massive dictionaries (e.g. HTTP payloads)
        # Undefined is extremely rare inside deep data structures because they originate from JSON.
        has_undefined = False
        for v in value.values():
            if isinstance(v, Undefined) or type(v) in (dict, list):
                has_undefined = True
                break
        
        if not has_undefined:
            return value
            
        return {k: _handle_undefined_values(v) for k, v in value.items()}
        
    if isinstance(value, list):
        if not value:
            return value
        # Shallow scan
        has_undefined = False
        for item in value:
            if isinstance(item, Undefined) or type(item) in (dict, list):
                has_undefined = True
                break
                
        if not has_undefined:
            return value
            
        return [_handle_undefined_values(item) for item in value]
        
    return value




def tojson_filter(obj):
    """Optimized tojson filter that avoids O(N) deep traversal of large JSON payloads."""
    from jinja2 import Undefined
    if isinstance(obj, Undefined):
        return 'null'

    # Unpack TaskResultProxy at the root
    if type(obj).__name__ == 'TaskResultProxy':
        if hasattr(obj, '__dict__') and '_data' in obj.__dict__:
            obj = obj.__dict__['_data']
        elif hasattr(obj, '_data'):
            obj = obj._data

    # Now obj is almost certainly a pure Python dict/list/scalar.
    # No need to recursively walk megabytes of JSON just to look for proxies 
    # that shouldn't be nested inside pure data anyway.
    return json.dumps(obj, cls=DateTimeEncoder)


def add_b64encode_filter(env: Environment) -> Environment:
    if 'b64encode' not in env.filters:
        env.filters['b64encode'] = lambda s: base64.b64encode(s.encode('utf-8')).decode('utf-8') if isinstance(s, str) else base64.b64encode(str(s).encode('utf-8')).decode('utf-8')
    if 'tojson' not in env.filters:
        env.filters['tojson'] = tojson_filter
    if 'encrypt_secret' not in env.filters:
        from noetl.core.secret import encrypt_json
        env.filters['encrypt_secret'] = lambda s: encrypt_json(json.loads(s) if isinstance(s, str) else s)
    return env



def render_template(env: Environment, template: Any, context: Dict, rules: Dict = None, strict_keys: bool = False) -> Any:
    """
    NoETL Jinja2 rendering.

    This function renders templates using Jinja2. When strict_keys=False, it will not raise errors
    for undefined variables, which is useful during the initial rendering phase when not all variables
    may be defined yet. This helps prevent false positive errors in nested templates.

    Args:
        env: The Jinja2 environment
        template: The template to render
        context: The context to use for rendering
        rules: Additional rules for rendering
        strict_keys: Whether to use strict key checking (raises errors for undefined variables)

    Returns:
        The rendered template
    """
    logger.debug(
        "render_template called: template_type=%s template_len=%s",
        type(template).__name__,
        len(template) if isinstance(template, str) else "-",
    )

    env = add_b64encode_filter(env)
    if isinstance(template, str) and (('{{' in template and '}}' in template) or ('{%' in template and '%}' in template)):
        logger.debug(
            "Render template: has_jinja=true context_key_count=%s template_len=%s",
            len(context.keys()) if isinstance(context, dict) else 0,
            len(template),
        )
        if rules:
            logger.debug("Render template rules_keys=%s", list(rules.keys()) if isinstance(rules, dict) else type(rules).__name__)

    render_ctx = dict(context)
    if rules:
        render_ctx.update(rules)

    if isinstance(template, str):
        if (('{{' not in template or '}}' not in template) and 
            ('{%' not in template or '%}' not in template)):
            logger.debug("render_template: plain string (no variables), length=%s", len(template))
            return template

        logger.debug("render_template: string with variables, length=%s", len(template))
        try:
            expr = template.strip()
            if expr == '{{}}':
                return ""
            if expr.startswith('{{') and expr.endswith('}}'):
                var_path = expr[2:-2].strip()
                if not any(op in var_path for op in ['==', '!=', '<', '>', '+', '-', '*', '/', '|', ' if ', ' else ']):
                    if '.' not in var_path and var_path.strip() in render_ctx:
                        return render_ctx.get(var_path.strip())
                    elif '.' in var_path:
                        parts = var_path.split('.')
                        value = render_ctx
                        valid_path = True
                        for part in parts:
                            part = part.strip()
                            if isinstance(value, dict) and part in value:
                                value = value.get(part)
                            else:
                                valid_path = False
                                break
                        if valid_path:
                            return value

            if strict_keys:
                template_obj = env.from_string(template)
            else:
                # Use overlay() for lightweight environment derivation (shares
                # filters/globals with parent instead of copying them one-by-one).
                temp_env = env.overlay()
                # Ensure custom filters survive the overlay
                temp_env = add_b64encode_filter(temp_env)
                template_obj = temp_env.from_string(template)
                
            try:
                custom_context = render_ctx.copy()

                reserved = {
                    'work',
                    'workload',
                    'context',
                    'env',
                    'job',
                    'input',
                    'data',
                    'results',
                    # Keep execution/iteration namespaces as plain dicts so
                    # Jinja can perform normal item lookup (e.g. ctx.foo)
                    # without TaskResultProxy interfering with runtime vars.
                    'ctx',
                    'iter',
                    'loop',
                    'event',
                }
                for key, value in render_ctx.items():
                    if key in reserved:
                        continue
                    if isinstance(value, dict):
                        # Always allow '.result' addressing for dict-like step results
                        custom_context[key] = TaskResultProxy(value, name=key)
                    elif isinstance(value, list):
                        # Provide a minimal wrapper so {{ step.result | length }} works for list-like results
                        custom_context[key] = {'result': value}

                if 'result' in render_ctx and isinstance(render_ctx['result'], dict):
                    custom_context['result'] = TaskResultProxy(render_ctx['result'])

                # Skip _handle_undefined_values overhead to prevent megabytes of JSON from 
                # being deeply traversed 40+ times per loop iteration.

                rendered = template_obj.render(**custom_context)
                logger.debug(
                    "render_template: rendered successfully output_type=%s output_len=%s",
                    type(rendered).__name__,
                    len(rendered) if isinstance(rendered, str) else "-",
                )
            except Exception as e:
                error_msg = (
                    f"Template rendering error: {e} "
                    f"(template_len={len(template) if isinstance(template, str) else '-'})"
                )
                # Reduce noise: always suppress persistence for undefined-variable cases.
                # These are expected when rendering loop-scoped variables like {{ city_item }} before evaluation.
                msg = str(e)
                if ("is undefined" in msg) or ("UndefinedError" in msg):
                    logger.debug(error_msg)
                else:
                    logger.error(error_msg)
                    # Persist to DB for non-undefined errors
                    log_error(
                        error=e,
                        error_type="template_rendering",
                        template_string=template,
                        context_data=render_ctx,
                        input_data={"template": template}
                    )
                
                if "'dict object' has no attribute 'data'" in str(e) or "'dict object' has no attribute 'result'" in str(e):
                    try:
                        var_path_match = re.search(r'{{(.*?)}}', template)
                        if var_path_match:
                            var_path = var_path_match.group(1).strip()
                            fixed_path = var_path.replace('.data.', '.').replace('.result.', '.')
                            fixed_template = template.replace(var_path, fixed_path)
                            logger.debug(
                                "Attempting fallback rendering with modified path template_len=%s",
                                len(fixed_template),
                            )
                            fixed_obj = env.from_string(fixed_template)
                            rendered = fixed_obj.render(**render_ctx)
                            logger.debug(
                                "Fallback rendering succeeded output_type=%s output_len=%s",
                                type(rendered).__name__,
                                len(rendered) if isinstance(rendered, str) else "-",
                            )
                            return rendered
                    except Exception as fallback_error:
                        logger.error(f"Fallback rendering also failed: {fallback_error}")
                
                if strict_keys:
                    raise
                return template

            # Check if the original template used tojson filter - if so, respect the string output
            # The user explicitly requested JSON string format, don't parse it back to dict
            if '| tojson' in template or '|tojson' in template:
                logger.debug("render_template: Template uses tojson filter, returning string output as-is")
                return rendered

            if (rendered.startswith('[') and rendered.endswith(']')) or \
                    (rendered.startswith('{') and rendered.endswith('}')):
                try:
                    return json.loads(rendered)
                except json.JSONDecodeError:
                    # Fallback to Python literal evaluation for non-JSON dict/list (single quotes)
                    try:
                        import ast
                        lit = ast.literal_eval(rendered)
                        return lit
                    except Exception:
                        pass

            # Try to coerce simple scalars (bool/int/float) from strings
            try:
                import ast
                if rendered.lower() in {"true","false"}:
                    return rendered.lower() == "true"
                if rendered.isdigit():
                    return int(rendered)
                # float-like
                if any(ch in rendered for ch in ['.', 'e', 'E']) and rendered.replace('.','',1).replace('e','',1).replace('E','',1).lstrip('+-').replace('0','1').isdigit():
                    return float(rendered)
                # None/null-like
                if rendered.strip().lower() in {"none","null"}:
                    return None
                # ast literal for tuples etc.
                try:
                    lit = ast.literal_eval(rendered)
                    return lit
                except Exception:
                    pass
            except Exception:
                pass

            if rendered.strip() == "":
                return ""

            return rendered
        except Exception as e:
            error_msg = (
                f"Template rendering error: {e} "
                f"(template_len={len(template) if isinstance(template, str) else '-'})"
            )
            logger.error(error_msg)
            
            log_error(
                error=e,
                error_type="template_rendering",
                template_string=template,
                context_data=render_ctx,
                input_data={"template": template}
            )
            
            if strict_keys:
                raise
            return template
    elif isinstance(template, dict):
        if not template:
            return template
        return {k: render_template(env, v, render_ctx, rules, strict_keys=strict_keys) for k, v in template.items()}
    elif isinstance(template, list):
        return [render_template(env, item, render_ctx, rules, strict_keys=strict_keys) for item in template]

    logger.debug(
        "render_template: returning unchanged value type=%s",
        type(template).__name__,
    )
    return template


class SQLCommentPreserver:
    """Helper class to preserve SQL comments during template rendering."""

    def __init__(self):
        self.comment_placeholders = {}
        self.placeholder_counter = 0

    def preserve_comments(self, sql: str) -> str:
        """Preserve comments with placeholders."""
        self.comment_placeholders.clear()
        self.placeholder_counter = 0

        comment_patterns = [
            r'--[^\n]*',  # Single-line comments
            r'/\*.*?\*/',  # Multi-line comments
        ]

        result = sql
        for pattern in comment_patterns:
            def replace_comment(match):
                comment = match.group(0)
                placeholder = f"__NOETL_COMMENT_PLACEHOLDER_{self.placeholder_counter}__"
                self.comment_placeholders[placeholder] = comment
                self.placeholder_counter += 1
                return placeholder

            result = re.sub(pattern, replace_comment, result, flags=re.DOTALL)

        return result

    def restore_comments(self, sql: str) -> str:
        """Restore SQL comments from placeholders."""
        result = sql
        for placeholder, comment in self.comment_placeholders.items():
            result = result.replace(placeholder, comment)
        return result


def render_sql_template(env: Environment, sql_template: str, context: Dict) -> str:
    """
    Render SQL template while preserving comments and handling multiline strings properly.

    Args:
        env: Jinja2 environment
        sql_template: SQL template string with Jinja2 expressions
        context: Template context

    Returns:
        Rendered SQL string with comments preserved
    """
    env = add_b64encode_filter(env)
    if not sql_template or not isinstance(sql_template, str):
        return sql_template

    if '{{' not in sql_template and '}}' not in sql_template:
        return sql_template

    try:
        comment_preserver = SQLCommentPreserver()
        sql_with_placeholders = comment_preserver.preserve_comments(sql_template)
        template_obj = env.from_string(sql_with_placeholders)
        rendered_sql = template_obj.render(**context)
        final_sql = comment_preserver.restore_comments(rendered_sql)
        logger.debug(f"SQL template rendered, length: {len(final_sql)}")
        return final_sql

    except Exception as e:
        error_msg = f"Error rendering SQL template: {e} | template_len={len(sql_template)}"
        logger.error(error_msg)
        
        log_error(
            error=e,
            error_type="sql_template_rendering",
            template_string=sql_template,
            context_data=context,
            input_data={"sql_template": sql_template}
        )
        
        raise


def render_duckdb_commands(env: Environment, commands: Union[str, List[str]], context: Dict, task_with: Dict = None) -> List[str]:
    """
    Render DuckDB commands.

    Args:
        env: Jinja2 environment
        commands: SQL commands, string or list
        context: Template context
        task_with: Additional task parameters

    Returns:
        Rendered SQL commands list
    """
    if task_with is None:
        task_with = {}

    full_context = {**context, **task_with}

    if isinstance(commands, str):
        rendered_sql = render_sql_template(env, commands, full_context)
        
        # Fast regex-based SQL statement splitting that handles strings and comments
        import re
        pattern = re.compile(
            r"('(?:''|\\.|[^'])*')|"
            r'("(?:""|\\.|[^"])*")|'
            r'(--[^\n]*)|'
            r'(/\*.*?\*/)|'
            r'(;)|'
            r'([^;\'"-/]+|.)',
            re.DOTALL
        )
        
        commands_list = []
        current = []
        for match in pattern.finditer(rendered_sql):
            if match.group(5):  # Semicolon
                stmt = "".join(current).strip()
                if stmt:
                    commands_list.append(stmt)
                current.clear()
            elif match.group(3) or match.group(4):
                pass  # Ignore comments
            else:
                current.append(match.group(0))
                
        if current:
            stmt = "".join(current).strip()
            if stmt:
                commands_list.append(stmt)

        return commands_list

    elif isinstance(commands, list):
        rendered_commands = []
        for cmd in commands:
            if isinstance(cmd, str):
                rendered_cmd = render_sql_template(env, cmd, full_context)
                if rendered_cmd and not rendered_cmd.strip().startswith('--'):
                    rendered_commands.append(rendered_cmd)
            else:
                rendered_commands.append(cmd)
        return rendered_commands

    return []


def quote_jinja2_expressions(yaml_text: str) -> str:
    """
    Add quotes around Jinja2 expressions in YAML text.

    Args:
        yaml_text: YAML text content

    Returns:
        YAML text with quoted Jinja2 expressions
    """
    jinja_expr_pattern = re.compile(r'''
        ^(\s*[^:\n]+:\s*)         # YAML key and colon with optional indent
        (?!["'])                  # Not already quoted
        (.*{{.*}}.*?)             # Contains Jinja2 template
        (?<!["'])\s*$             # Not ending with a quote
    ''', re.VERBOSE)

    def replacer(match):
        key_part = match.group(1)
        value_part = match.group(2).strip()
        return f'{key_part}"{value_part}"'

    fixed_lines = []
    for line in yaml_text.splitlines():
        fixed_line = jinja_expr_pattern.sub(replacer, line)
        fixed_lines.append(fixed_line)
    return "\n".join(fixed_lines)
