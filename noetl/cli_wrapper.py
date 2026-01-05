"""
Console script wrapper for the noetl Rust binary.

This module provides a Python entry point that executes the bundled Rust binary.
It's registered as a console_script in pyproject.toml.
"""

import os
import sys
import subprocess
from pathlib import Path


def get_noetl_binary():
    """Get the path to the noetl binary.
    
    First checks if 'noetl' is in PATH (Docker/K8s deployment).
    Falls back to bundled binary in package (PyPI wheel).
    """
    import shutil
    
    # Check if noetl is in PATH (Docker/K8s environments)
    path_binary = shutil.which('noetl')
    if path_binary:
        return path_binary
    
    # Fall back to bundled binary (PyPI wheel)
    import noetl
    package_dir = Path(noetl.__file__).parent
    binary_name = 'noetl.exe' if sys.platform == 'win32' else 'noetl'
    binary_path = package_dir / 'bin' / binary_name
    
    if not binary_path.exists():
        print(f"Error: noetl binary not found at {binary_path}", file=sys.stderr)
        print("The binary may not be available for your platform.", file=sys.stderr)
        print("Please compile it manually or use a platform-specific wheel.", file=sys.stderr)
        sys.exit(1)
    
    return binary_path


def main():
    """Execute the noetl Rust binary with all arguments."""
    binary_path = get_noetl_binary()
    
    # Execute the binary with all command-line arguments
    try:
        result = subprocess.run(
            [str(binary_path)] + sys.argv[1:],
            check=False
        )
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        sys.exit(130)  # Standard exit code for Ctrl+C
    except Exception as e:
        print(f"Error executing noetl binary: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
