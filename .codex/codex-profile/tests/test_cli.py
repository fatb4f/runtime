from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

from handoff.cli import create_handoff, main
from handoff.rollout import RolloutError

from conftest import git, write_rollout


def _events() -> list[dict]:
    return [
        {
            "timestamp": "2026-07-26T20:01:00Z",
            "type": "event_msg",
            "payload": {"type": "user_message", "message": "Implement handoff"},
        },
        {
            "timestamp": "2026-07-26T20:02:00Z",
            "type": "event_msg",
            "payload": {
                "type": "agent_message",
                "message": (
                    "Objective: Implement handoff\n"
                    "Completed:\n- Added code\n"
                    "Current operation: Qualifying\n"
                    "Next operation: Continue\n"
                    "Completion criteria:\n- Tests pass"
                ),
            },
        },
    ]


def test_create_stages_and_atomically_publishes(repository: Path, tmp_path: Path) -> None:
    rollout = write_rollout(tmp_path / "rollout.jsonl", repository, _events())
    (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")
    frozen = datetime(2026, 7, 26, 23, 0, tzinfo=timezone.utc)
    path = create_handoff(
        repository=repository,
        rollout_path=rollout,
        output_root=tmp_path / "state",
        now=frozen,
    )
    assert path == tmp_path / "state" / "019fa0d8-5185-71e2-89cd-b9bcbb9ea79d" / "handoff.json"
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["schema"] == "codex.handoff.v0"
    assert document["createdAt"] == "2026-07-26T23:00:00Z"
    assert document["repository"]["staged"][0]["path"] == "tracked.txt"
    assert path.read_bytes().endswith(b"\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert git(repository, "diff", "--cached", "--name-only") == "tracked.txt"


def test_later_rollout_failure_does_not_rollback_staging(
    repository: Path, tmp_path: Path
) -> None:
    rollout = write_rollout(tmp_path / "rollout.jsonl", repository, _events())
    with rollout.open("ab") as handle:
        handle.write(b"{bad}\n")
    (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")
    with pytest.raises(RolloutError):
        create_handoff(
            repository=repository,
            rollout_path=rollout,
            output_root=tmp_path / "state",
        )
    assert git(repository, "diff", "--cached", "--name-only") == "tracked.txt"
    assert not (tmp_path / "state").exists()


def test_output_root_inside_repository_is_rejected(repository: Path, tmp_path: Path) -> None:
    rollout = write_rollout(tmp_path / "rollout.jsonl", repository, _events())
    (repository / "tracked.txt").write_text("not staged\n", encoding="utf-8")
    with pytest.raises(ValueError, match="outside"):
        create_handoff(
            repository=repository,
            rollout_path=rollout,
            output_root=repository / ".state",
        )
    assert git(repository, "diff", "--cached", "--name-only") == ""
    assert git(repository, "diff", "--name-only") == "tracked.txt"


def test_cli_prints_only_path(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
) -> None:
    rollout = write_rollout(tmp_path / "rollout.jsonl", repository, _events())
    monkeypatch.chdir(repository)
    assert (
        main(
            [
                "create",
                "--rollout",
                str(rollout),
                "--output-root",
                str(tmp_path / "state"),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.strip().endswith("/handoff.json")
