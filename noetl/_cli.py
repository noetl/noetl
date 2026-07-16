"""Console entry point for the NoETL Python/Rust CLI wheel."""

from __future__ import annotations

import sys

from . import _native


def main() -> int:
    """Run the Rust-backed CLI dispatcher."""

    try:
        return int(_native.cli_main(sys.argv[1:]))
    except Exception as exc:  # pragma: no cover - exercised through wheel smoke
        print(f"noetl: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
