from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .git import GitError, resolve_metadata_repository
from .model import (
    Diagnostic,
    DerivedValue,
    Failure,
    MAX_ERROR_BYTES,
    Operation,
    SessionProjection,
)

_PROGRESS_HEADERS = {
    "Objective": "objective",
    "Completed": "completed",
    "Current operation": "current_operation",
    "Next operation": "next_operation",
    "Completion criteria": "completion_criteria",
    "Open questions": "open_questions",
}
_LIST_FIELDS = {"completed", "completion_criteria", "open_questions"}
_SHELL_RESULT = re.compile(r"^Process exited with code:?\s*(-?[0-9]+)\s*$", re.MULTILINE)


class RolloutError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdmittedRollout:
    path: Path
    session_id: str
    metadata_cwd: Path


@dataclass(frozen=True)
class RolloutProjection:
    session: SessionProjection
    objective: DerivedValue | None
    completed: list[DerivedValue]
    current_operation: DerivedValue | None
    next_operation: DerivedValue | None
    completion_criteria: list[DerivedValue]
    operations: list[Operation]
    failures: list[Failure]
    open_questions: list[DerivedValue]
    diagnostics: list[Diagnostic]


def resolve_rollout(
    repository: Path,
    *,
    explicit: Path | None = None,
    codex_home: Path | None = None,
) -> AdmittedRollout:
    if explicit is not None:
        path = explicit.expanduser().resolve()
        if not path.is_file():
            raise RolloutError(f"rollout does not exist: {path}")
        return _admit_metadata(path, repository)

    root = (codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".local/share/codex")))
    sessions = root.expanduser().resolve() / "sessions"
    candidates: list[tuple[int, AdmittedRollout]] = []
    if sessions.is_dir():
        for path in sessions.rglob("*.jsonl"):
            if not path.is_file():
                continue
            try:
                admitted = _admit_metadata(path.resolve(), repository)
            except (OSError, UnicodeError, ValueError, RolloutError, GitError):
                continue
            candidates.append((path.stat().st_mtime_ns, admitted))
    if not candidates:
        raise RolloutError(f"no rollout belongs to repository {repository}")
    maximum = max(key for key, _ in candidates)
    newest = [admitted for key, admitted in candidates if key == maximum]
    if len(newest) != 1:
        raise RolloutError("multiple admitted rollouts share the newest mtime_ns")
    return newest[0]


def _admit_metadata(path: Path, repository: Path) -> AdmittedRollout:
    metadata: list[dict[str, Any]] = []
    with path.open("rb") as handle:
        for raw in handle:
            if not raw.endswith(b"\n"):
                break
            try:
                event = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(event, dict) and event.get("type") == "session_meta":
                payload = event.get("payload")
                if isinstance(payload, dict):
                    metadata.append(payload)
    if not metadata:
        raise RolloutError(f"rollout has no session_meta: {path}")

    identities: set[tuple[str, str, str | None]] = set()
    canonical_roots: set[Path] = set()
    for item in metadata:
        session_id = item.get("session_id") or item.get("id")
        cwd = item.get("cwd")
        rollout_id = item.get("id")
        if not isinstance(session_id, str) or not session_id:
            raise RolloutError("session_meta has no session identity")
        if not isinstance(cwd, str) or not cwd:
            raise RolloutError("session_meta has no working directory")
        identities.add((session_id, cwd, rollout_id if isinstance(rollout_id, str) else None))
        try:
            canonical_roots.add(resolve_metadata_repository(Path(cwd)))
        except (OSError, GitError) as error:
            raise RolloutError(f"cannot resolve session repository: {cwd}") from error
    if len(identities) != 1 or len(canonical_roots) != 1:
        raise RolloutError("session_meta records disagree")
    canonical_root = next(iter(canonical_roots))
    if canonical_root != repository:
        raise RolloutError(
            f"rollout repository mismatch: expected {repository}, observed {canonical_root}"
        )
    session_id, cwd, _rollout_id = next(iter(identities))
    return AdmittedRollout(path=path, session_id=session_id, metadata_cwd=Path(cwd))


def project_rollout(admitted: AdmittedRollout) -> RolloutProjection:
    data = admitted.path.read_bytes()
    complete_lines, trailing = _complete_lines(data)
    if not complete_lines:
        raise RolloutError("rollout contains no complete events")
    events: list[dict[str, Any]] = []
    for index, raw in enumerate(complete_lines):
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise RolloutError(f"malformed complete rollout record at event {index}") from error
        if not isinstance(value, dict):
            raise RolloutError(f"rollout event {index} is not an object")
        events.append(value)

    metadata = _metadata_from_events(events, admitted)
    diagnostics: list[Diagnostic] = []
    if trailing:
        diagnostics.append(
            Diagnostic(
                code="rollout.trailing-record-incomplete",
                detail="Excluded a non-newline-terminated trailing fragment.",
                eventIndex=len(complete_lines),
            )
        )

    operations, failures, pending_questions = _operation_trace(events)
    cue_index, cues = _latest_progress_cues(events)
    latest_user = _latest_user_message(events)

    objective: DerivedValue | None = None
    if cue_index is not None and cues.get("objective"):
        objective = _derived(cues["objective"][0], cue_index, "explicit-objective")
    elif latest_user is not None:
        index, text = latest_user
        objective = _derived(text, index, "latest-user-request")
    else:
        diagnostics.append(Diagnostic(code="rollout.objective-unavailable"))

    completed = (
        [_derived(value, cue_index, "explicit-completed") for value in cues.get("completed", [])]
        if cue_index is not None
        else []
    )
    current = _single_cue(
        cue_index, cues, "current_operation", "explicit-current-operation", diagnostics
    )
    next_operation = _single_cue(
        cue_index, cues, "next_operation", "explicit-next-operation", diagnostics
    )
    criteria = (
        [
            _derived(value, cue_index, "explicit-completion-criteria")
            for value in cues.get("completion_criteria", [])
        ]
        if cue_index is not None
        else []
    )
    if not criteria:
        diagnostics.append(Diagnostic(code="rollout.completion-criteria-unavailable"))

    open_questions = (
        [_derived(value, cue_index, "explicit-open-question") for value in cues.get("open_questions", [])]
        if cue_index is not None
        else []
    )
    existing_questions = {item.value for item in open_questions}
    for index, question in pending_questions:
        if question not in existing_questions:
            open_questions.append(_derived(question, index, "structured-open-question"))

    return RolloutProjection(
        session=SessionProjection(
            rollout=str(admitted.path),
            sessionId=metadata,
            firstEvent=0,
            lastEvent=len(events) - 1,
        ),
        objective=objective,
        completed=completed,
        current_operation=current,
        next_operation=next_operation,
        completion_criteria=criteria,
        operations=operations,
        failures=failures,
        open_questions=open_questions,
        diagnostics=diagnostics,
    )


def _complete_lines(data: bytes) -> tuple[list[bytes], bytes]:
    if not data:
        return [], b""
    records = data.split(b"\n")
    trailing = b""
    if records[-1] == b"":
        records.pop()
    else:
        trailing = records.pop()
    complete = [record[:-1] if record.endswith(b"\r") else record for record in records]
    return complete, trailing


def _metadata_from_events(events: list[dict[str, Any]], admitted: AdmittedRollout) -> str:
    values: set[tuple[str, str, str | None]] = set()
    for event in events:
        if event.get("type") != "session_meta" or not isinstance(event.get("payload"), dict):
            continue
        payload = event["payload"]
        session_id = payload.get("session_id") or payload.get("id")
        cwd = payload.get("cwd")
        rollout_id = payload.get("id")
        if not isinstance(session_id, str) or not isinstance(cwd, str):
            raise RolloutError("complete session_meta is malformed")
        values.add((session_id, cwd, rollout_id if isinstance(rollout_id, str) else None))
    if len(values) != 1:
        raise RolloutError("complete session_meta records disagree")
    session_id, cwd, _ = next(iter(values))
    if session_id != admitted.session_id or Path(cwd) != admitted.metadata_cwd:
        raise RolloutError("snapshotted session_meta differs from preliminary admission")
    return session_id


def _operation_trace(
    events: list[dict[str, Any]],
) -> tuple[list[Operation], list[Failure], list[tuple[int, str]]]:
    calls: dict[str, tuple[int, str, dict[str, Any], str | None]] = {}
    results: dict[str, tuple[int, Any, str | None]] = {}
    latest_user_index = max(
        (index for index, event in enumerate(events) if _user_text(event) is not None),
        default=-1,
    )
    pending_questions: list[tuple[int, str]] = []

    for index, event in enumerate(events):
        payload = event.get("payload")
        if not isinstance(payload, dict):
            continue
        payload_type = payload.get("type")
        if event.get("type") == "response_item" and payload_type == "function_call":
            call_id = payload.get("call_id")
            name = payload.get("name")
            if not isinstance(call_id, str) or not isinstance(name, str):
                continue
            arguments = _arguments(payload.get("arguments"))
            calls[call_id] = (index, name, arguments, _timestamp(event))
            if name == "request_user_input" and index > latest_user_index:
                questions = arguments.get("questions")
                if isinstance(questions, list):
                    for question in questions:
                        if isinstance(question, dict) and isinstance(question.get("question"), str):
                            pending_questions.append((index, question["question"]))
        elif event.get("type") == "response_item" and payload_type in {
            "function_call_output",
            "custom_tool_call_output",
        }:
            call_id = payload.get("call_id")
            if isinstance(call_id, str):
                results[call_id] = (index, payload.get("output"), _timestamp(event))

    operations: list[Operation] = []
    failures: list[Failure] = []
    for index, event in enumerate(events):
        text = _assistant_text(event)
        if text is not None:
            operations.append(
                Operation(
                    kind="assistant",
                    event=index,
                    timestamp=_timestamp(event),
                    text=text,
                    status="succeeded",
                )
            )

    for call_id, (event_index, name, arguments, timestamp) in calls.items():
        command, argv = _command_evidence(arguments)
        if _is_self_invocation(command, argv):
            continue
        result = results.get(call_id)
        result_index: int | None = None
        output: Any = None
        result_timestamp: str | None = None
        if result is not None:
            result_index, output, result_timestamp = result
        exit_code, error = _explicit_result(output)
        shell = exit_code is not None or name in {"exec_command", "write_stdin", "wait"}
        failed = (exit_code is not None and exit_code != 0) or error is not None
        status = "pending" if result is None else ("failed" if failed else "succeeded")
        operations.append(
            Operation(
                kind="shell" if shell else "tool",
                event=event_index,
                resultEvent=result_index,
                timestamp=timestamp,
                tool=name,
                argv=argv,
                command=command,
                exitCode=exit_code,
                status=status,
            )
        )
        if exit_code is not None and exit_code != 0:
            failures.append(
                Failure(
                    kind="shell",
                    tool=name,
                    event=result_index if result_index is not None else event_index,
                    timestamp=result_timestamp or timestamp,
                    argv=argv,
                    command=command,
                    exitCode=exit_code,
                )
            )
        elif error is not None:
            retained, truncated = _bounded_error(error)
            failures.append(
                Failure(
                    kind="tool",
                    tool=name,
                    event=result_index if result_index is not None else event_index,
                    timestamp=result_timestamp or timestamp,
                    argv=argv,
                    command=command,
                    error=retained,
                    truncated=truncated,
                )
            )
    operations.sort(key=lambda item: (item.event, item.result_event or -1))
    failures.sort(key=lambda item: item.event)
    return operations, failures, pending_questions


def _arguments(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return decoded if isinstance(decoded, dict) else {}
    return {}


def _command_evidence(arguments: dict[str, Any]) -> tuple[str | None, list[str] | None]:
    command = arguments.get("cmd") or arguments.get("command")
    argv = arguments.get("argv")
    exact_command = command if isinstance(command, str) else None
    exact_argv = (
        argv
        if isinstance(argv, list) and all(isinstance(value, str) for value in argv)
        else None
    )
    if exact_command is not None:
        return exact_command, None
    return None, exact_argv


def _explicit_result(output: Any) -> tuple[int | None, str | None]:
    structured = output
    if isinstance(output, str):
        try:
            structured = json.loads(output)
        except json.JSONDecodeError:
            match = _SHELL_RESULT.search(output)
            return (int(match.group(1)), None) if match else (None, None)
    if not isinstance(structured, dict):
        return None, None
    exit_code = structured.get("exitCode", structured.get("exit_code"))
    resolved_exit = exit_code if isinstance(exit_code, int) and not isinstance(exit_code, bool) else None
    explicit_error = structured.get("error")
    failed_status = structured.get("status") == "failed"
    error: str | None = None
    if explicit_error is not None:
        error = (
            explicit_error
            if isinstance(explicit_error, str)
            else json.dumps(explicit_error, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    elif failed_status:
        error = "tool result reported status=failed"
    return resolved_exit, error


def _bounded_error(value: str) -> tuple[str, bool]:
    data = value.encode("utf-8")
    if len(data) <= MAX_ERROR_BYTES:
        return value, False
    return data[:MAX_ERROR_BYTES].decode("utf-8", "ignore"), True


def _is_self_invocation(command: str | None, argv: list[str] | None) -> bool:
    if argv is not None:
        return argv[:2] == ["handoff", "create"] or argv[:3] == ["uv", "run", "handoff"]
    if command is None:
        return False
    normalized = command.strip()
    return bool(
        re.fullmatch(
            r"(?:uv\s+run(?:\s+--)?\s+)?handoff\s+create"
            r"(?:\s+--(?:rollout|output-root)(?:=|\s+)(?:\"[^\"]*\"|'[^']*'|\S+))*",
            normalized,
        )
    )


def _latest_progress_cues(
    events: list[dict[str, Any]],
) -> tuple[int | None, dict[str, list[str]]]:
    for index in range(len(events) - 1, -1, -1):
        text = _assistant_text(events[index])
        if text is None:
            continue
        cues = _parse_cues(text)
        if cues:
            return index, cues
    return None, {}


def _parse_cues(text: str) -> dict[str, list[str]]:
    values: dict[str, list[str]] = {}
    active: str | None = None
    buffer: list[str] = []

    def flush() -> None:
        nonlocal buffer
        if active is None:
            return
        if active in _LIST_FIELDS:
            items = [line[2:].strip() for line in buffer if line.startswith("- ") and line[2:].strip()]
            if items:
                values[active] = items
        else:
            value = "\n".join(line for line in buffer).strip()
            if value:
                values[active] = [value]
        buffer = []

    header_pattern = re.compile(
        r"^(Objective|Completed|Current operation|Next operation|Completion criteria|Open questions):(?:\s*(.*))?$"
    )
    for line in text.splitlines():
        match = header_pattern.fullmatch(line)
        if match:
            flush()
            active = _PROGRESS_HEADERS[match.group(1)]
            inline = match.group(2)
            buffer = [inline] if inline else []
        elif active is not None:
            buffer.append(line)
    flush()
    return values


def _single_cue(
    cue_index: int | None,
    cues: dict[str, list[str]],
    field: str,
    derivation: str,
    diagnostics: list[Diagnostic],
) -> DerivedValue | None:
    values = cues.get(field, [])
    if cue_index is not None and values:
        return _derived(values[0], cue_index, derivation)
    diagnostics.append(Diagnostic(code=f"rollout.{field.replace('_', '-')}-unavailable"))
    return None


def _derived(value: str, event: int, derivation: str) -> DerivedValue:
    return DerivedValue(value=value, sourceEvents=[event], derivation=derivation)


def _latest_user_message(events: list[dict[str, Any]]) -> tuple[int, str] | None:
    for index in range(len(events) - 1, -1, -1):
        text = _user_text(events[index])
        if text:
            return index, text
    return None


def _user_text(event: dict[str, Any]) -> str | None:
    payload = event.get("payload")
    if event.get("type") != "event_msg" or not isinstance(payload, dict):
        return None
    if payload.get("type") != "user_message":
        return None
    message = payload.get("message")
    return message if isinstance(message, str) and message.strip() else None


def _assistant_text(event: dict[str, Any]) -> str | None:
    payload = event.get("payload")
    if event.get("type") != "event_msg" or not isinstance(payload, dict):
        return None
    if payload.get("type") != "agent_message":
        return None
    message = payload.get("message")
    return message if isinstance(message, str) and message.strip() else None


def _timestamp(event: dict[str, Any]) -> str | None:
    value = event.get("timestamp")
    return value if isinstance(value, str) and value else None
