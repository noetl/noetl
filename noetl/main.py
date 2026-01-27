"""
DEPRECATED: Python CLI has been replaced by the Rust CLI.

This Python entry point is deprecated and will be removed in a future version.
The NoETL CLI is now implemented in Rust (noetlctl) and bundled with the Python package.

When you run `noetl` after installing via pip, you are using the Rust binary through
a Python wrapper (noetl.cli_wrapper). This file exists only for backwards compatibility.

Migration:
- The `noetl` command automatically uses the new Rust CLI
- All commands and functionality remain the same
- No action required - the transition is transparent to users

For more information, see:
- documentation/docs/development/rust_cli_migration.md
- documentation/docs/development/pypi_rust_bundling.md

Note: This module remains for backward compatibility only.

to be removed in future releases.
"""

import sys
import warnings


def main():
    """Deprecated Python CLI entry point."""
    warnings.warn(
        "The Python-based CLI (noetl.cli.ctl) is deprecated and has been replaced "
        "by the Rust-based CLI. This entry point exists only for backwards compatibility. "
        "Please use 'noetl' command directly (bundled Rust binary via cli_wrapper).",
        DeprecationWarning,
        stacklevel=2
    )
    
    print("ERROR: Python CLI has been removed.", file=sys.stderr)
    print("Please use the 'noetl' command instead (Rust CLI via wrapper).", file=sys.stderr)
    print("If you installed via pip, the command should already be available.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
