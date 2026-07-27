from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from handoff.rollout import RolloutError, project_rollout, resolve_rollout

from conftest import write_rollout


def _user(message: str) -> dict:
    return {
        "timestamp": "2026-07-26T20:01:00Z",
        "type": "event_msg",
        "payload": {"type": "user_message", "message": message},
    }


def _assistant(message: str) -> dict:
    return {
        "timestamp": "2026-07-26T20:02:00Z",
        "type": "event_msg",
        "payload": {"type": "agent_message", "message": message, "phase": "commentary"},
    }


def _call(call_id: str, name: str, arguments: dict) -> dict:
    return {
        "timestamp": "2026-07-26T20:03:00Z",
        "type": "response_item",
        "payload": {
            "type": "function_call",
            "call_id": call_id,
            "name": name,
            "arguments": json.dumps(arguments),
        },
    }


def _result(call_id: str, output: object) -> dict:
    return {
        "timestamp": "2026-07-26T20:04:00Z",
        "type": "response_item",
        "payload": {"type": "function_call_output", "call_id": call_id, "output": output},
    }


def test_projects_explicit_cues_and_shell_failure(repository: Path, tmp_path: Path) -> None:
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [
            _user("Implement the handoff"),
            _assistant(
                "Objective: Thin handoff\n"
                "Completed:\n- Git boundary\n"
                "Current operation: Testing\n"
                "Next operation: Publish\n"
                "Completion criteria:\n- Tests pass\n"
                "Open questions:\n- None?"
            ),
            _call("1", "exec_command", {"cmd": "uv run pytest"}),
            _result("1", "Process exited with code 1\nOutput:\nfailed"),
        ],
    )
    projection = project_rollout(resolve_rollout(repository, explicit=rollout))
    assert projection.objective is not None
    assert projection.objective.value == "Thin handoff"
    assert projection.current_operation is not None
    assert projection.next_operation is not None
    assert projection.completion_criteria[0].value == "Tests pass"
    assert projection.failures[0].command == "uv run pytest"
    assert projection.failures[0].exit_code == 1
    assert "failed" not in (projection.failures[0].error or "")


def test_command_string_is_not_split_and_self_call_is_excluded(
    repository: Path, tmp_path: Path
) -> None:
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [
            _user("Work"),
            _call("1", "exec_command", {"cmd": "pytest -q | tee log"}),
            _result("1", "Process exited with code 0\nOutput:\nok"),
            _call("2", "exec_command", {"cmd": "uv run handoff create"}),
        ],
    )
    projection = project_rollout(resolve_rollout(repository, explicit=rollout))
    shell = [operation for operation in projection.operations if operation.kind == "shell"]
    assert len(shell) == 1
    assert shell[0].command == "pytest -q | tee log"
    assert shell[0].argv is None


def test_structured_tool_error_is_bounded(repository: Path, tmp_path: Path) -> None:
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [
            _user("Work"),
            _call("1", "example_tool", {}),
            _result("1", json.dumps({"status": "failed", "error": "x" * 9000})),
        ],
    )
    projection = project_rollout(resolve_rollout(repository, explicit=rollout))
    assert projection.failures[0].kind == "tool"
    assert projection.failures[0].truncated is True
    assert len(projection.failures[0].error.encode("utf-8")) == 8192


def test_trailing_fragment_is_excluded_and_diagnosed(repository: Path, tmp_path: Path) -> None:
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [_user("Work")],
        trailing=b'{"type":"response_item"',
    )
    projection = project_rollout(resolve_rollout(repository, explicit=rollout))
    assert projection.session.last_event == 1
    diagnostic = next(
        item for item in projection.diagnostics if item.code == "rollout.trailing-record-incomplete"
    )
    assert diagnostic.event_index == 2


def test_malformed_complete_record_is_rejected(repository: Path, tmp_path: Path) -> None:
    rollout = write_rollout(tmp_path / "rollout.jsonl", repository, [_user("Work")])
    with rollout.open("ab") as handle:
        handle.write(b"{bad}\n")
    admitted = resolve_rollout(repository, explicit=rollout)
    with pytest.raises(RolloutError, match="malformed complete"):
        project_rollout(admitted)


def test_discovery_rejects_equal_newest_mtime(repository: Path, tmp_path: Path) -> None:
    home = tmp_path / "codex"
    first = write_rollout(home / "sessions/a.jsonl", repository, [_user("one")])
    second = write_rollout(home / "sessions/b.jsonl", repository, [_user("two")])
    stamp = 1_700_000_000_000_000_000
    os.utime(first, ns=(stamp, stamp))
    os.utime(second, ns=(stamp, stamp))
    with pytest.raises(RolloutError, match="share the newest"):
        resolve_rollout(repository, codex_home=home)
