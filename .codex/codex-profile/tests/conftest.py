from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest


def git(repository: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repository,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    root.mkdir()
    git(root, "init", "-q")
    git(root, "config", "user.email", "test@example.invalid")
    git(root, "config", "user.name", "Test")
    (root / "tracked.txt").write_text("one\n", encoding="utf-8")
    git(root, "add", "tracked.txt")
    git(root, "commit", "-qm", "initial")
    return root


def write_rollout(path: Path, repository: Path, events: list[dict], *, trailing: bytes = b"") -> Path:
    session = {
        "timestamp": "2026-07-26T20:00:00Z",
        "type": "session_meta",
        "payload": {
            "id": "019fa0d8-5185-71e2-89cd-b9bcbb9ea79d",
            "session_id": "019fa0d8-5185-71e2-89cd-b9bcbb9ea79d",
            "cwd": str(repository),
        },
    }
    records = [session, *events]
    path.parent.mkdir(parents=True, exist_ok=True)
    body = b"".join(
        json.dumps(record, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"
        for record in records
    )
    path.write_bytes(body + trailing)
    return path
