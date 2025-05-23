import re
import sys
from pathlib import Path
from noetl.util import setup_logger
logger = setup_logger(__name__, include_location=True)

def quote_unquoted_jinja2_expressions(yaml_text):
    """
    Wraps unquoted Jinja2 expressions in double quotes.
    """
    jinja_expr_pattern = re.compile(r'''
        ^(\s*[^:\n]+:\s*)         # YAML key and colon (with optional indent)
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


def main(filepath):
    filepath = Path(filepath)
    original = filepath.read_text(encoding="utf-8")

    fixed = quote_unquoted_jinja2_expressions(original)

    if original == fixed:
        logger.success("Jinja2 unquoted expressions not found.")
    else:
        backup_path = filepath.with_suffix(".bak.yaml")
        filepath.write_text(fixed, encoding="utf-8")
        backup_path.write_text(original, encoding="utf-8")
        logger.success(f"Fixed unquoted Jinja2 expressions.")
        logger.success(f"Backup created at: {backup_path}")

if __name__ == "__main__":
    if len(sys.argv) != 2:
        logger.info("Usage: python quote_exprs.py <playbook.yaml>")
        sys.exit(1)

    main(sys.argv[1])
