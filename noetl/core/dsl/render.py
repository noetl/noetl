import re
import json
import base64
from typing import Any, Dict, List, Union, Optional
from jinja2 import Environment, meta, StrictUndefined, BaseLoader, Undefined
from noetl.core.logger import log_error
from noetl.core.common import DateTimeEncoder

from noetl.core.logger import setup_logger
logger = setup_logger(__name__, include_location=True)


def _handle_undefined_values(value: Any) -> Any:
    """Convert Undefined values to None to prevent JSON serialization errors."""
    if isinstance(value, Undefined):
        return None
    elif isinstance(value, dict):
        return {k: _handle_undefined_values(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_handle_undefined_values(item) for item in value]
    return value


def add_b64encode_filter(env: Environment) -> Environment:
    """
    Add the b64encode filter to a Jinja2 environment.
    
    Args:
        env: The Jinja2 environment
        
    Returns:
        The Jinja2 environment with the b64encode filter added
    """
    if 'b64encode' not in env.filters:
        env.filters['b64encode'] = lambda s: base64.b64encode(s.encode('utf-8')).decode('utf-8') if isinstance(s, str) else base64.b64encode(str(s).encode('utf-8')).decode('utf-8')
    
    # Provide a tojson filter for templates that need JSON stringification
    # Always update the filter to ensure latest code is used
    def tojson_filter(obj):
        """Custom tojson filter that unwraps TaskResultProxy objects and handles Undefined."""
        from jinja2 import Undefined

        # Handle Jinja2 Undefined objects
        if isinstance(obj, Undefined):
            return 'null'

        # Recursively unwrap TaskResultProxy objects
        def unwrap_proxies(value):
            """Recursively unwrap all TaskResultProxy objects in nested structures."""
            value_type = type(value).__name__
            logger.debug(f"[TOJSON] unwrap_proxies: value_type={value_type}")

            # Check for TaskResultProxy by class name (handles multiple class definitions)
            if value_type == 'TaskResultProxy':
                logger.debug(f"[TOJSON] Found TaskResultProxy, extracting _data")
                # Access _data directly via object's __dict__ to avoid __getattr__
                if hasattr(value, '__dict__') and '_data' in value.__dict__:
                    return unwrap_proxies(value.__dict__['_data'])
                elif hasattr(value, '_data'):
                    return unwrap_proxies(value._data)
                else:
                    # Fallback: try to convert to string
                    logger.warning(f"[TOJSON] Could not extract _data from TaskResultProxy, using str()")
                    return str(value)
            elif hasattr(value, '_data') and not isinstance(value, (dict, list, tuple, str, int, float, bool, type(None))):
                # Other proxy-like objects with _data attribute
                logger.debug(f"[TOJSON] Found proxy-like object with _data, extracting")
                return unwrap_proxies(value._data)
            elif isinstance(value, dict):
                # Recursively unwrap dict values
                return {k: unwrap_proxies(v) for k, v in value.items()}
            elif isinstance(value, (list, tuple)):
                # Recursively unwrap list/tuple items
                return type(value)(unwrap_proxies(item) for item in value)
            else:
                return value

        obj = unwrap_proxies(obj)
        logger.debug(f"[TOJSON] After unwrap, obj type={type(obj).__name__}")
        return json.dumps(obj, cls=DateTimeEncoder)
    env.filters['tojson'] = tojson_filter
    
    # Provide encrypt_secret filter for caching sensitive data
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
    logger.debug(f"render_template called with template: {template}, type: {type(template)}")

    env = add_b64encode_filter(env)
    if isinstance(template, str) and (('{{' in template and '}}' in template) or ('{%' in template and '%}' in template)):
        logger.debug(f"Render template: {template} | context_keys={list(context.keys())}")
        if rules:
            logger.debug(f"Render template rules: {rules}")

    render_ctx = dict(context)
    if rules:
        render_ctx.update(rules)

    if isinstance(template, str):
        if (('{{' not in template or '}}' not in template) and 
            ('{%' not in template or '%}' not in template)):
            logger.debug(f"render_template: Plain string (no template vars), returning as-is: {template}")
            return template

        logger.debug(f"render_template: String with template vars: {template}")
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
                # Inherit undefined class from parent environment
                temp_env = Environment(loader=env.loader, undefined=env.undefined)
                for name, filter_func in env.filters.items():
                    temp_env.filters[name] = filter_func
                for name, global_var in env.globals.items():
                    temp_env.globals[name] = global_var
                template_obj = temp_env.from_string(template)
                
            try:
                custom_context = render_ctx.copy()

                class TaskResultProxy:
                    def __init__(self, data, name=""):
                        self._data = data
                        self._name = name

                    def __getattr__(self, name):
                        if name == 'data' and name not in self._data:
                            return self
                        elif name == 'result' and name not in self._data:
                            return self
                        elif name == 'is_defined':
                            return True
                        elif name.startswith('command_') and isinstance(self._data, dict) and name in self._data:
                            return self._data[name]
                        elif isinstance(self._data, dict) and name in self._data:
                            return self._data[name]
                        raise AttributeError(f"'{type(self._data).__name__}' object has no attribute '{name}'")

                    def __getitem__(self, key):
                        try:
                            return self._data[key]
                        except Exception as e:
                            raise KeyError(key) from e

                    def get(self, key, default=None):
                        """Support dict-like .get() method for Jinja2 templates."""
                        if isinstance(self._data, dict):
                            return self._data.get(key, default)
                        return default

                    def __str__(self):
                        """Return JSON string representation when TaskResultProxy is rendered directly in Jinja2"""
                        import json
                        return json.dumps(self._data, default=str)
                    
                    def __repr__(self):
                        """Return JSON string representation for debugging"""
                        import json
                        return json.dumps(self._data, default=str)

                reserved = {'work', 'workload', 'context', 'env', 'job', 'input', 'data', 'results'}
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

                # Clean Undefined values from context before rendering
                custom_context = _handle_undefined_values(custom_context)

                rendered = template_obj.render(**custom_context)
                logger.debug(f"render_template: Successfully rendered: {rendered}")
            except Exception as e:
                error_msg = f"Template rendering error: {e}, template: {template}"
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
                            logger.info(f"Attempting fallback rendering with modified path: {fixed_template}")
                            fixed_obj = env.from_string(fixed_template)
                            rendered = fixed_obj.render(**render_ctx)
                            logger.info(f"Fallback rendering succeeded: {rendered}")
                            return rendered
                    except Exception as fallback_error:
                        logger.error(f"Fallback rendering also failed: {fallback_error}")
                
                if strict_keys:
                    raise
                return template

            # Check if the original template used tojson filter - if so, respect the string output
            # The user explicitly requested JSON string format, don't parse it back to dict
            if '| tojson' in template or '|tojson' in template:
                logger.debug(f"render_template: Template uses tojson filter, returning string as-is: {rendered[:100]}...")
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
            error_msg = f"Template rendering error: {e}, template: {template}"
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

    logger.debug(f"render_template: Returning template unchanged: {template}")
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
        error_msg = f"Error rendering SQL template: {e} | template={sql_template[:200]}..."
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

        commands_list = []
        current_command = ""
        in_string = False
        string_char = None

        i = 0
        while i < len(rendered_sql):
            char = rendered_sql[i]

            if char in ('"', "'") and (i == 0 or rendered_sql[i-1] != '\\'):
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None

            if char == ';' and not in_string:
                command = current_command.strip()
                if command:
                    commands_list.append(command)
                current_command = ""
            else:
                current_command += char

            i += 1

        if current_command.strip():
            commands_list.append(current_command.strip())

        return [cmd for cmd in commands_list if cmd and not cmd.strip().startswith('--')]

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
