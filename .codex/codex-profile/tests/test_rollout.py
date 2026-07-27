from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from handoff.codex_wire import MAX_CUSTOM_INPUT_BYTES
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
    wire_output = (
        json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if isinstance(output, dict)
        else output
    )
    return {
        "timestamp": "2026-07-26T20:04:00Z",
        "type": "response_item",
        "payload": {
            "type": "function_call_output",
            "call_id": call_id,
            "output": wire_output,
        },
    }


def _custom_call(call_id: str, name: str, input_value: str) -> dict:
    return {
        "timestamp": "2026-07-26T20:03:00Z",
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call",
            "call_id": call_id,
            "name": name,
            "input": input_value,
        },
    }


def _custom_result(call_id: str, output: object) -> dict:
    wire_output = (
        json.dumps(output, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        if isinstance(output, dict)
        else output
    )
    return {
        "timestamp": "2026-07-26T20:04:00Z",
        "type": "response_item",
        "payload": {
            "type": "custom_tool_call_output",
            "call_id": call_id,
            "output": wire_output,
        },
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
    assert projection.objective.value == "Implement the handoff"
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
    assert diagnostic.event_index is None


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


def test_discovery_defaults_to_dot_codex(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CODEX_HOME", raising=False)
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    rollout = write_rollout(
        tmp_path / ".codex/sessions/current.jsonl", repository, [_user("Work")]
    )
    assert resolve_rollout(repository).path == rollout.resolve()


def test_injected_codex_home_precedes_environment(
    repository: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    environment_home = tmp_path / "environment"
    injected_home = tmp_path / "injected"
    write_rollout(environment_home / "sessions/wrong.jsonl", repository, [_user("Wrong")])
    expected = write_rollout(
        injected_home / "sessions/right.jsonl", repository, [_user("Right")]
    )
    monkeypatch.setenv("CODEX_HOME", str(environment_home))
    assert resolve_rollout(repository, codex_home=injected_home).path == expected.resolve()


def test_stale_progress_cues_do_not_override_new_request(
    repository: Path, tmp_path: Path
) -> None:
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [
            _user("Old task"),
            _assistant(
                "Objective: Old task\n"
                "Completed:\n- Old work\n"
                "Current operation: Old current\n"
                "Next operation: Old next\n"
                "Completion criteria:\n- Old done"
            ),
            _user("New task"),
        ],
    )
    projection = project_rollout(resolve_rollout(repository, explicit=rollout))
    assert projection.objective is not None
    assert projection.objective.value == "New task"
    assert projection.completed == []
    assert projection.current_operation is None
    assert projection.next_operation is None
    assert projection.completion_criteria == []


def test_custom_tool_failure_is_projected_without_argv(
    repository: Path, tmp_path: Path
) -> None:
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [
            _user("Work"),
            _custom_call("custom-1", "exec", '{"source":"do_work()"}'),
            _custom_result("custom-1", {"status": "failed", "error": "boom"}),
        ],
    )
    projection = project_rollout(resolve_rollout(repository, explicit=rollout))
    operation = next(item for item in projection.operations if item.tool == "exec")
    assert operation.input == '{"source":"do_work()"}'
    assert operation.argv is None
    assert operation.command is None
    assert operation.status == "failed"
    assert projection.failures[0].error == "boom"


def test_structured_question_result_with_answers_closes_question(
    repository: Path, tmp_path: Path
) -> None:
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [
            _user("Work"),
            _call(
                "question-1",
                "request_user_input",
                {"questions": [{"question": "Pick one?"}]},
            ),
            _result("question-1", {"answers": ["A"]}),
        ],
    )
    projection = project_rollout(resolve_rollout(repository, explicit=rollout))
    assert projection.open_questions == []


def test_later_user_message_closes_structured_question(
    repository: Path, tmp_path: Path
) -> None:
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [
            _user("Work"),
            _call(
                "question-1",
                "request_user_input",
                {"questions": [{"question": "Pick one?"}]},
            ),
            _user("A"),
        ],
    )
    projection = project_rollout(resolve_rollout(repository, explicit=rollout))
    assert projection.open_questions == []


@pytest.mark.parametrize(
    "events, message",
    [
        (
            [_user("Work"), _call("duplicate", "tool", {}), _call("duplicate", "tool", {})],
            "duplicate tool call_id",
        ),
        ([_user("Work"), _result("orphan", {})], "orphan tool result"),
        (
            [
                _user("Work"),
                _call("duplicate-result", "tool", {}),
                _result("duplicate-result", {}),
                _result("duplicate-result", {}),
            ],
            "duplicate tool result",
        ),
    ],
)
def test_duplicate_and_orphan_call_ids_are_rejected(
    repository: Path, tmp_path: Path, events: list[dict], message: str
) -> None:
    rollout = write_rollout(tmp_path / "rollout.jsonl", repository, events)
    with pytest.raises(RolloutError, match=message):
        project_rollout(resolve_rollout(repository, explicit=rollout))


def test_invalid_timestamp_is_rejected(repository: Path, tmp_path: Path) -> None:
    event = _user("Work")
    event["timestamp"] = "not-a-time"
    rollout = write_rollout(tmp_path / "rollout.jsonl", repository, [event])
    with pytest.raises(RolloutError, match="invalid timestamp"):
        project_rollout(resolve_rollout(repository, explicit=rollout))


def test_newest_operation_window_is_retained(repository: Path, tmp_path: Path) -> None:
    events = [_user("Work")]
    events.extend(_assistant(f"Update {index}") for index in range(2050))
    rollout = write_rollout(tmp_path / "rollout.jsonl", repository, events)
    projection = project_rollout(resolve_rollout(repository, explicit=rollout))
    assert len(projection.operations) == 2048
    assert projection.operations[0].text == "Update 2"
    diagnostic = next(
        item for item in projection.diagnostics if item.code == "rollout.operations-omitted"
    )
    assert diagnostic.detail == "Omitted 2 earlier operations outside the retained window."


def test_runtime_validation_commands_are_classified(
    repository: Path, tmp_path: Path
) -> None:
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [
            _user("Work"),
            _call("test", "exec_command", {"cmd": "uv run pytest -q"}),
            _result("test", "Process exited with code 0\nOutput:\npassed"),
            _call("compound", "exec_command", {"cmd": "uv run pytest -q | tee output"}),
            _result("compound", "Process exited with code 0\nOutput:\npassed"),
        ],
    )
    projection = project_rollout(resolve_rollout(repository, explicit=rollout))
    assert len(projection.validation) == 1
    assert projection.validation[0].kind == "test"
    assert projection.validation[0].status == "passed"


@pytest.mark.parametrize(
    "call, result, expected, received",
    [
        (
            _call("cross-family", "tool", {}),
            _custom_result("cross-family", "done"),
            "function_call_output",
            "custom_tool_call_output",
        ),
        (
            _custom_call("cross-family", "tool", "input"),
            _result("cross-family", "done"),
            "custom_tool_call_output",
            "function_call_output",
        ),
    ],
)
def test_cross_family_output_is_rejected(
    repository: Path,
    tmp_path: Path,
    call: dict,
    result: dict,
    expected: str,
    received: str,
) -> None:
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [_user("Work"), call, result],
    )
    message = (
        "call result family mismatch at event 3:\n"
        f"call_id=cross-family expected={expected}\n"
        f"received={received}"
    )
    with pytest.raises(RolloutError, match=re.escape(message)):
        project_rollout(resolve_rollout(repository, explicit=rollout))


def test_ordinary_tool_output_with_exit_phrase_remains_tool(
    repository: Path, tmp_path: Path
) -> None:
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [
            _user("Work"),
            _call("read", "read_file", {"path": "result.txt"}),
            _result("read", "Process exited with code 9"),
        ],
    )
    projection = project_rollout(resolve_rollout(repository, explicit=rollout))
    operation = next(item for item in projection.operations if item.tool == "read_file")
    assert operation.kind == "tool"
    assert operation.exit_code is None
    assert operation.status == "succeeded"
    assert projection.failures == []


def test_custom_call_named_like_shell_remains_tool(
    repository: Path, tmp_path: Path
) -> None:
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [
            _user("Work"),
            _custom_call("custom-shell", "exec_command", "echo no"),
            _custom_result("custom-shell", "Process exited with code 12"),
        ],
    )
    projection = project_rollout(resolve_rollout(repository, explicit=rollout))
    operation = next(item for item in projection.operations if item.tool == "exec_command")
    assert operation.kind == "tool"
    assert operation.status == "succeeded"


def test_known_shell_parses_structured_exit_code(
    repository: Path, tmp_path: Path
) -> None:
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [
            _user("Work"),
            _call("shell", "shell_command", {"command": "exit 4"}),
            _result("shell", {"exit_code": 4, "output": ""}),
        ],
    )
    projection = project_rollout(resolve_rollout(repository, explicit=rollout))
    operation = next(item for item in projection.operations if item.tool == "shell_command")
    assert operation.kind == "shell"
    assert operation.exit_code == 4
    assert operation.status == "failed"


def test_unknown_tool_defaults_to_tool(repository: Path, tmp_path: Path) -> None:
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [
            _user("Work"),
            _call("unknown", "container.exec", {"command": "false"}),
            _result("unknown", {"exit_code": 3}),
        ],
    )
    projection = project_rollout(resolve_rollout(repository, explicit=rollout))
    operation = next(item for item in projection.operations if item.tool == "container.exec")
    assert operation.kind == "tool"
    assert operation.exit_code is None
    assert operation.status == "succeeded"


def test_shell_without_exit_evidence_is_rejected(
    repository: Path, tmp_path: Path
) -> None:
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [
            _user("Work"),
            _call("shell", "exec_command", {"cmd": "long-running"}),
            _result("shell", {"session_id": 42, "output": "still running"}),
        ],
    )
    with pytest.raises(RolloutError, match="has no exit status"):
        project_rollout(resolve_rollout(repository, explicit=rollout))


def test_custom_input_truncation_emits_diagnostic(
    repository: Path, tmp_path: Path
) -> None:
    oversized = ("x" * (MAX_CUSTOM_INPUT_BYTES - 1)) + "é"
    rollout = write_rollout(
        tmp_path / "rollout.jsonl",
        repository,
        [_user("Work"), _custom_call("large", "custom", oversized)],
    )
    projection = project_rollout(resolve_rollout(repository, explicit=rollout))
    operation = next(item for item in projection.operations if item.tool == "custom")
    assert operation.input == "x" * (MAX_CUSTOM_INPUT_BYTES - 1)
    diagnostic = next(
        item
        for item in projection.diagnostics
        if item.code == "rollout.custom-input-truncated"
    )
    assert diagnostic.event_index == 2
    assert diagnostic.detail == "originalBytes=32769 retainedBytes=32767"
