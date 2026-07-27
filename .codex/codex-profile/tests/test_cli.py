from __future__ import annotations

import json
import os
import stat
from datetime import datetime, timezone
from pathlib import Path

import pytest

import handoff.cli as cli_module
from handoff.cli import create_handoff, main
from handoff.codex_wire import MAX_CUSTOM_INPUT_BYTES
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
    assert document["completed"] == [
        {
            "derivation": "explicit-completed",
            "sourceEvents": [2],
            "value": "Added code",
        }
    ]
    assert document["validation"] == []
    assert path.read_bytes().endswith(b"\n")
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    assert git(repository, "diff", "--cached", "--name-only") == "tracked.txt"


def test_invalid_rollout_fails_before_git_snapshot(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rollout = write_rollout(tmp_path / "rollout.jsonl", repository, _events())
    with rollout.open("ab") as handle:
        handle.write(b"{bad}\n")
    (repository / "tracked.txt").write_text("changed\n", encoding="utf-8")

    def unexpected_snapshot(root: Path) -> None:
        pytest.fail(f"begin_snapshot called for invalid rollout: {root}")

    monkeypatch.setattr(cli_module, "begin_snapshot", unexpected_snapshot)
    with pytest.raises(RolloutError):
        create_handoff(
            repository=repository,
            rollout_path=rollout,
            output_root=tmp_path / "state",
        )
    assert git(repository, "diff", "--cached", "--name-only") == ""
    assert git(repository, "diff", "--name-only") == "tracked.txt"
    assert not (tmp_path / "state").exists()


def test_oversized_input_is_bounded_before_git_snapshot(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    oversized = ("x" * (MAX_CUSTOM_INPUT_BYTES - 1)) + "é"
    events = [
        *_events(),
        {
            "timestamp": "2026-07-26T20:03:00Z",
            "type": "response_item",
            "payload": {
                "type": "custom_tool_call",
                "call_id": "large",
                "name": "custom",
                "input": oversized,
            },
        },
    ]
    rollout = write_rollout(tmp_path / "rollout.jsonl", repository, events)
    projected: dict[str, object] = {}
    real_project_rollout = cli_module.project_rollout

    def recording_projection(admitted):
        projection = real_project_rollout(admitted)
        projected["value"] = projection
        return projection

    def inspect_before_snapshot(root: Path) -> None:
        projection = projected["value"]
        operation = next(
            item for item in projection.operations if item.tool == "custom"
        )
        assert len(operation.input.encode("utf-8")) == MAX_CUSTOM_INPUT_BYTES - 1
        raise RuntimeError("snapshot boundary reached")

    monkeypatch.setattr(cli_module, "project_rollout", recording_projection)
    monkeypatch.setattr(cli_module, "begin_snapshot", inspect_before_snapshot)
    with pytest.raises(RuntimeError, match="snapshot boundary reached"):
        create_handoff(
            repository=repository,
            rollout_path=rollout,
            output_root=tmp_path / "state",
        )


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
    monkeypatch.setenv("CODEX_ROLLOUT_PATH", str(tmp_path / "missing.jsonl"))
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


def test_environment_rollout_is_used_without_flag(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    rollout = write_rollout(tmp_path / "rollout.jsonl", repository, _events())
    monkeypatch.setenv("CODEX_ROLLOUT_PATH", str(rollout))
    path = create_handoff(
        repository=repository,
        output_root=tmp_path / "state",
        now=datetime(2026, 7, 26, 23, 0, tzinfo=timezone.utc),
    )
    assert path.is_file()


def test_publication_failure_removes_temporary_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = tmp_path / "state"

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(cli_module.os, "replace", fail_replace)
    with pytest.raises(OSError, match="replace failed"):
        cli_module._publish(
            state_root=state,
            session_id="session-1",
            data=b"{}\n",
        )
    directory = state / "session-1"
    assert not list(directory.glob(".handoff.*"))
    assert not (directory / "handoff.json").exists()
