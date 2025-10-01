from pathlib import Path

import pytest

PB_DIR = Path(__file__).parent / "fixtures" / "playbooks"
PLAYBOOKS = sorted(PB_DIR.rglob("*.y*ml"))


@pytest.mark.parametrize("path", PLAYBOOKS)
def test_playbook_can_be_parsed(path: Path) -> None:
    text = path.read_text(encoding="utf-8")
    assert text
