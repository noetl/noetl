"""
Post-installation script to install the noetl Rust binary.

This module provides functionality to install the pre-compiled noetl binary
from the package data to the user's bin directory.
"""

import os
import shutil
import stat
import sys
from pathlib import Path


def get_bin_dir():
    """Get the appropriate bin directory for the current Python environment."""
    # For virtual environments
    if hasattr(sys, 'real_prefix') or (hasattr(sys, 'base_prefix') and sys.base_prefix != sys.prefix):
        if sys.platform == 'win32':
            return Path(sys.prefix) / 'Scripts'
        return Path(sys.prefix) / 'bin'
    
    # For user installs
    if sys.platform == 'win32':
        return Path(sys.prefix) / 'Scripts'
    return Path(sys.prefix) / 'bin'


def get_noetl_binary_path():
    """Get the path to the bundled noetl binary in package data."""
    import noetl
    package_dir = Path(noetl.__file__).parent
    binary_name = 'noetl.exe' if sys.platform == 'win32' else 'noetl'
    return package_dir / 'bin' / binary_name


def install_binary():
    """Install the noetl binary to the bin directory."""
    try:
        source_binary = get_noetl_binary_path()
        
        if not source_binary.exists():
            print(f"Warning: noetl binary not found at {source_binary}", file=sys.stderr)
            print("The binary may not be available for your platform.", file=sys.stderr)
            return False
        
        bin_dir = get_bin_dir()
        bin_dir.mkdir(parents=True, exist_ok=True)
        
        binary_name = 'noetl.exe' if sys.platform == 'win32' else 'noetl'
        target_binary = bin_dir / binary_name
        
        # Copy the binary
        shutil.copy2(source_binary, target_binary)
        
        # Make executable on Unix-like systems
        if sys.platform != 'win32':
            current_permissions = os.stat(target_binary).st_mode
            os.chmod(target_binary, current_permissions | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        
        print(f"Successfully installed noetl binary to {target_binary}")
        return True
        
    except Exception as e:
        print(f"Error installing noetl binary: {e}", file=sys.stderr)
        return False


def main():
    """Main entry point for post-install script."""
    if '--install-binary' in sys.argv:
        success = install_binary()
        sys.exit(0 if success else 1)
    else:
        print("Usage: python -m noetl.install --install-binary")
        sys.exit(1)


if __name__ == '__main__':
    main()
