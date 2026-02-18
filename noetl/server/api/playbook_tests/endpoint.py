"""
Playbook test suite file API.

Stores and retrieves test suite JSON files in-repo so suites are shareable
across developers and environments.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import os
import re
from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Path as FastAPIPath, Body
from pydantic import BaseModel, Field

from noetl.core.logger import setup_logger

logger = setup_logger(__name__, include_location=True)
router = APIRouter(prefix="/playbook-tests", tags=["PlaybookTests"])


def _repo_root() -> Path:
    # .../noetl/server/api/playbook_tests/endpoint.py -> repo root
    return Path(__file__).resolve().parents[4]


def _suites_dir() -> Path:
    configured = os.getenv("NOETL_PLAYBOOK_TEST_SUITES_DIR", "").strip()
    base = Path(configured).expanduser() if configured else (_repo_root() / "tests" / "fixtures" / "playbook_tests")
    base.mkdir(parents=True, exist_ok=True)
    return base


def _sanitize_suite_id(suite_id: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9/_\-.]+", "_", suite_id or "").strip()
    cleaned = cleaned.strip("/.")
    cleaned = re.sub(r"/+", "/", cleaned)
    if not cleaned:
        raise ValueError("suite_id cannot be empty")
    parts = cleaned.split("/")
    if any(part in ("..", "") for part in parts):
        raise ValueError("suite_id contains invalid path segments")
    return cleaned


def _suite_path(suite_id: str) -> Path:
    safe = _sanitize_suite_id(suite_id)
    path = (_suites_dir() / f"{safe}.json").resolve()
    base = _suites_dir().resolve()
    if not str(path).startswith(str(base)):
        raise ValueError("suite_id resolves outside suites directory")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


class TestSuiteUpsertRequest(BaseModel):
    playbook_path: str = Field(..., description="Playbook metadata.path associated with this suite")
    tests: list[Dict[str, Any]] = Field(default_factory=list, description="List of test case objects")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Optional suite metadata")


class TestSuiteResponse(BaseModel):
    suite_id: str
    file_path: str
    playbook_path: str
    tests: list[Dict[str, Any]]
    metadata: Dict[str, Any]
    updated_at: str


@router.get("/suites/{suite_id:path}", response_model=TestSuiteResponse)
async def get_test_suite(
    suite_id: str = FastAPIPath(..., description="Suite id. Usually the playbook metadata.path"),
):
    try:
        suite_file = _suite_path(suite_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not suite_file.exists():
        raise HTTPException(status_code=404, detail=f"Test suite '{suite_id}' not found")

    try:
        data = json.loads(suite_file.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.exception("Failed to read test suite file %s: %s", suite_file, exc)
        raise HTTPException(status_code=500, detail="Failed to read suite file")

    return TestSuiteResponse(
        suite_id=suite_id,
        file_path=str(suite_file),
        playbook_path=data.get("playbook_path", suite_id),
        tests=data.get("tests", []),
        metadata=data.get("metadata", {}),
        updated_at=data.get("updated_at") or datetime.now(timezone.utc).isoformat(),
    )


@router.put("/suites/{suite_id:path}", response_model=TestSuiteResponse)
async def upsert_test_suite(
    suite_id: str = FastAPIPath(..., description="Suite id. Usually the playbook metadata.path"),
    payload: TestSuiteUpsertRequest = Body(...),
):
    try:
        suite_file = _suite_path(suite_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    now = datetime.now(timezone.utc).isoformat()
    data = {
        "suite_id": suite_id,
        "playbook_path": payload.playbook_path,
        "tests": payload.tests,
        "metadata": payload.metadata,
        "updated_at": now,
    }

    try:
        suite_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except Exception as exc:
        logger.exception("Failed to save suite file %s: %s", suite_file, exc)
        raise HTTPException(status_code=500, detail="Failed to save suite file")

    return TestSuiteResponse(
        suite_id=suite_id,
        file_path=str(suite_file),
        playbook_path=payload.playbook_path,
        tests=payload.tests,
        metadata=payload.metadata,
        updated_at=now,
    )


@router.delete("/suites/{suite_id:path}")
async def delete_test_suite(
    suite_id: str = FastAPIPath(..., description="Suite id"),
):
    try:
        suite_file = _suite_path(suite_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    if not suite_file.exists():
        raise HTTPException(status_code=404, detail=f"Test suite '{suite_id}' not found")

    try:
        suite_file.unlink()
    except Exception as exc:
        logger.exception("Failed to delete suite file %s: %s", suite_file, exc)
        raise HTTPException(status_code=500, detail="Failed to delete suite file")

    return {"status": "success", "suite_id": suite_id, "file_path": str(suite_file)}

