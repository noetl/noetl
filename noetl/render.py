import re
import json
import logging
import base64
import traceback
from typing import Any, Dict, List, Union, Optional
from jinja2 import Environment, meta, StrictUndefined, BaseLoader
from noetl.logger import log_error

logger = logging.getLogger(__name__)


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
    if isinstance(template, str) and '{{' in template and '}}' in template:
        logger.debug(f"Render template: {template}")
        logger.debug(f"Render template context keys: {list(context.keys())}")
        if 'city' in context:
            logger.debug(f"Render template city value: {context['city']}, Type: {type(context['city'])}")
        if rules:
            logger.debug(f"Render template rules: {rules}")

    render_ctx = dict(context)
    if rules:
        render_ctx.update(rules)

    if isinstance(template, str):
        if '{{' not in template or '}}' not in template:
            logger.debug(f"render_template: Plain string without template variables, returning as-is: {template}")
            return template

        logger.debug(f"render_template: String with template variables detected: {template}")
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
                temp_env = Environment(loader=env.loader)
                for name, filter_func in env.filters.items():
                    temp_env.filters[name] = filter_func
                for name, global_var in env.globals.items():
                    temp_env.globals[name] = global_var
                template_obj = temp_env.from_string(template)
                
            try:
                custom_context = render_ctx.copy()

                class TaskResultProxy:
                    def __init__(self, data):
                        self._data = data

                    def __getattr__(self, name):
                        if name == 'data' and name not in self._data:
                            return self
                        elif name == 'result' and name not in self._data:
                            return self
                        elif name == 'is_defined':
                            return True
                        elif name.startswith('command_') and name in self._data:
                            return self._data[name]
                        elif name in self._data:
                            return self._data[name]
                        raise AttributeError(f"'{type(self._data).__name__}' object has no attribute '{name}'")

                for key, value in render_ctx.items():
                    if isinstance(value, dict) and (
                        ('data' not in value and any(k.startswith('command_') for k in value.keys())) or
                        ('result' not in value and any(k.startswith('command_') for k in value.keys()))
                    ):
                        custom_context[key] = TaskResultProxy(value)

                if 'result' in render_ctx and isinstance(render_ctx['result'], dict):
                    custom_context['result'] = TaskResultProxy(render_ctx['result'])

                rendered = template_obj.render(**custom_context)
                logger.debug(f"render_template: Successfully rendered: {rendered}")
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
        error_msg = f"Error rendering SQL template: {e}"
        logger.error(error_msg)
        logger.debug(f"Failed template: {sql_template[:200]}...")
        
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
