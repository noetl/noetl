#!/usr/bin/env python3
"""
Print simple module size stats (top-N by lines).
Usage: python tools/mod_stats.py [N]
"""

import sys
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def main() -> None:
    try:
        topn = int(sys.argv[1]) if len(sys.argv) > 1 else 20
    except Exception:
        topn = 20
    root = Path(__file__).resolve().parents[1]
    py_files = list(root.rglob("*.py"))
    stats = []
    for f in py_files:
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
            lines = text.count("\n") + 1
            stats.append((lines, str(f.relative_to(root))))
        except Exception:
            pass
    stats.sort(reverse=True)
    logger.info("lines, path")
    for lines, p in stats[:topn]:
        logger.info(f"{lines}, {p}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    main()

