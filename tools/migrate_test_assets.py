#!/usr/bin/env python3
import sys
import subprocess
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "examples" / "test"
DST_PB = ROOT / "tests" / "fixtures" / "playbooks"
DST_SEC = ROOT / "tests" / "fixtures" / "secrets"


def is_secret(path: Path) -> bool:
    p = str(path).lower()
    return "/secrets/" in p or "secret" in path.name.lower()


def is_playbook(path: Path) -> bool:
    if path.suffix.lower() not in (".yml", ".yaml"):
        return False
    return "/secrets/" not in str(path).lower()


def main() -> None:
    if not SRC.exists():
        logger.info(f"Source not found: {SRC}", file=sys.stderr)
        sys.exit(1)

    DST_PB.mkdir(parents=True, exist_ok=True)
    DST_SEC.mkdir(parents=True, exist_ok=True)

    moves = []
    for path in SRC.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(SRC)
        if is_secret(path):
            target = DST_SEC / rel
        elif is_playbook(path):
            target = DST_PB / rel
        else:
            continue

        target.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["git", "mv", str(path), str(target)], check=True)
        moves.append((str(path), str(target)))

    logger.info("\nMoved files:")
    for src, dest in moves:
        logger.info(f" - {src} -> {dest}")
    if not moves:
        logger.info("No files matched for migration.")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    main()
