from __future__ import annotations

import json
import os
import subprocess
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

import pytest
from hypothesis import given, strategies as st
from pydantic import ValidationError

from codex_profile.contracts import Handoff, canonical_bytes
from codex_profile.handoff import create_handoff, repository_state


def git(repo: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


@pytest.fixture
def repo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    path = tmp_path / "repo"; path.mkdir()
    git(path, "init", "-q")
    git(path, "config", "user.email", "test@example.invalid")
    git(path, "config", "user.name", "Test")
    (path / "tracked").write_text("one\n")
    git(path, "add", "tracked"); git(path, "commit", "-qm", "initial")
    monkeypatch.chdir(path)
    return path


def arguments() -> Namespace:
    return Namespace(
        objective="ship", invariant=["preserve"], decision=[], passing=[], failing=[],
        not_run=["tests"], current_operation="implement", next_operation="validate",
        completion_criterion=["tests pass"], evidence_pointer=[], open_question=[],
    )


def test_repository_states_and_atomic_packet(repo: Path, tmp_path: Path) -> None:
    (repo / "tracked").write_text("two\n")
    git(repo, "add", "tracked")
    (repo / "tracked").write_text("three\n")
    (repo / "untracked").write_text("new\n")
    state = repository_state(repo)
    assert state.root == str(repo.resolve())
    assert state.dirty_paths == ["tracked", "untracked"]
    assert state.staged_paths == ["tracked"]
    fixed = datetime(2026, 7, 23, 12, 34, 56, 123456, timezone.utc)
    json_path, md_path, _ = create_handoff(arguments(), now=fixed, state_root=tmp_path / "state")
    assert json_path.stat().st_mode & 0o777 == 0o600
    assert md_path.stat().st_mode & 0o777 == 0o600
    assert json_path.parent.stat().st_mode & 0o777 == 0o700
    assert len(json_path.read_bytes()) <= 16 * 1024
    assert json_path.read_bytes().endswith(b"\n")
    with pytest.raises(FileExistsError):
        create_handoff(arguments(), now=fixed, state_root=tmp_path / "state")


def test_detached_head(repo: Path) -> None:
    git(repo, "checkout", "--detach", "-q")
    assert repository_state(repo).branch is None


@given(st.text(min_size=1).filter(lambda value: value.strip() != ""))
def test_unknown_fields_rejected(objective: str) -> None:
    value = {
        "schema": "codex.handoff.v0", "createdAt": "2026-07-23T12:34:56Z",
        "objective": objective, "invariants": [], "decisions": [],
        "repository": {"root": "/tmp", "revision": "a" * 40, "branch": None,
                       "dirtyPaths": [], "stagedPaths": []},
        "validation": {"passing": [], "failing": [], "notRun": []},
        "currentOperation": "current", "nextOperation": "next",
        "completionCriteria": ["done"], "evidencePointers": [], "openQuestions": [],
        "unknown": True,
    }
    with pytest.raises(ValidationError):
        Handoff.model_validate(value)
