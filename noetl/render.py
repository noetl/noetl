import re
import json
import logging
from typing import Any, Dict, List, Union
from jinja2 import Environment, meta, StrictUndefined, BaseLoader

logger = logging.getLogger(__name__)


def render_template(env: Environment, template: Any, context: Dict, rules: Dict = None) -> Any:
    """
    NoETL Jinja2 rendering.

    Args:
        env: The Jinja2 environment
        template: The template to render
        context: The context to use for rendering
        rules: Additional rules for rendering

    Returns:
        The rendered template
    """
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

    if isinstance(template, str) and '{{' in template and '}}' in template:
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

            template_obj = env.from_string(template)
            try:
                rendered = template_obj.render(**render_ctx)
            except Exception as e:
                logger.error(f"Template rendering error: {e}, template: {template}")
                return None

            if (rendered.startswith('[') and rendered.endswith(']')) or \
                    (rendered.startswith('{') and rendered.endswith('}')):
                try:
                    return json.loads(rendered)
                except json.JSONDecodeError:
                    pass

            if rendered.strip() == "":
                return ""

            return rendered
        except Exception as e:
            logger.error(f"Template rendering error: {e}, template: {template}")
            return ""
    elif isinstance(template, dict):
        if not template:
            return template
        return {k: render_template(env, v, render_ctx, rules) for k, v in template.items()}
    elif isinstance(template, list):
        return [render_template(env, item, render_ctx, rules) for item in template]
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
        logger.error(f"Error rendering SQL template: {e}")
        logger.debug(f"Failed template: {sql_template[:200]}...")
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


# def render_template_bool(jinja_env: Environment, template_str: str, context: Dict) -> bool:
#     """
#     Render a template and return as boolean, with proper error handling.
#
#     Args:
#         jinja_env: Jinja2 environment
#         template_str: Template string
#         context: Template context
#
#     Returns:
#         Boolean result or False on error
#     """
#     try:
#         # Check if all referenced variables exist
#         ast = jinja_env.parse(template_str)
#         referenced = meta.find_undeclared_variables(ast)
#         for key in referenced:
#             parts = key.split('.')
#             ctx = context
#             valid_path = True
#             for part in parts:
#                 if isinstance(ctx, dict) and part in ctx:
#                     ctx = ctx[part]
#                 else:
#                     valid_path = False
#                     break
#             if not valid_path:
#                 return False
#
#         return render_template_safe(jinja_env, template_str, context)
#     except Exception as e:
#         logger.debug(f"Error in render_template_bool: {str(e)}")
#         return False
#
#
# def safe_render_template_bool(jinja_env: Environment, template_str: str, context: Dict, default: bool = False) -> bool:
#     """
#     Safely render a template as boolean with a default fallback.
#
#     Args:
#         jinja_env: Jinja2 environment
#         template_str: Template string
#         context: Template context
#         default: Default value to return on error
#
#     Returns:
#         Boolean result or default on error
#     """
#     try:
#         result = render_template_safe(jinja_env, template_str, context)
#         if isinstance(result, bool):
#             return result
#         elif isinstance(result, str):
#             return result.lower() in ('true', '1', 'yes', 'on')
#         elif isinstance(result, (int, float)):
#             return bool(result)
#         else:
#             return default
#     except Exception as e:
#         logger.debug(f"Error in safe_render_template_bool: {str(e)}")
#         return default


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
