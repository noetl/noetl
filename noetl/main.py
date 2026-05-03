"""Retired Python command entry point.

The maintained NoETL CLI is the Rust binary released from:
https://github.com/noetl/cli
"""

import sys
import warnings


def main():
    """Exit with guidance for the maintained Rust CLI."""
    warnings.warn(
        "This Python command entry point is retired. Install the maintained "
        "Rust NoETL CLI from https://github.com/noetl/cli.",
        DeprecationWarning,
        stacklevel=2
    )
    
    print("ERROR: this Python command entry point is retired.", file=sys.stderr)
    print("Install the maintained Rust NoETL CLI from https://github.com/noetl/cli.", file=sys.stderr)
    sys.exit(1)


if __name__ == "__main__":
    main()
