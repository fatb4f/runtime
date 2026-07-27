from __future__ import annotations

import heapq
import json
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Generic, TypeVar

from .codex_wire import (
    CallFamily,
    CustomToolCall,
    CustomToolCallOutput,
    FunctionCall,
    FunctionCallOutput,
    OutputBody,
    WireParseError,
    bound_utf8,
    parse_response_item,
)
from .git import GitError, resolve_metadata_repository
from .model import (
    Diagnostic,
    DerivedValue,
    Failure,
    MAX_ERROR_BYTES,
    MAX_FAILURES,
    MAX_OPERATIONS,
    MAX_VALIDATION,
    Operation,
    QualificationValidation,
    SessionProjection,
    TestValidation,
    ValidationResult,
)
from .tool_registry import classify_tool

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
_RFC3339 = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_COMPOUND_SHELL = re.compile(r"[|;&><\r\n]")
_PYTEST_COMMAND = re.compile(
    r"^(?:(?:uv\s+run\s+)?(?:python(?:3(?:\.\d+)*)?\s+-m\s+)?pytest)(?:\s+.*)?$"
)
_QUALIFICATION_COMMANDS = (
    ("handoff-help", re.compile(r"^(?:uv\s+run\s+)?handoff\s+--help$")),
    ("uv-lock-check", re.compile(r"^uv\s+lock\s+--check$")),
    ("uv-build", re.compile(r"^uv\s+build(?:\s+.*)?$")),
    (
        "uv-install",
        re.compile(r"^(?:uv\s+sync(?:\s+.*)?|uv\s+pip\s+install(?:\s+.*)?)$"),
    ),
)


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
    validation: list[ValidationResult]
    failures: list[Failure]
    open_questions: list[DerivedValue]
    diagnostics: list[Diagnostic]


@dataclass(frozen=True)
class _Call:
    family: CallFamily
    event: int
    name: str
    timestamp: datetime | None
    command: str | None
    argv: list[str] | None
    input: str | None


@dataclass
class _Question:
    call_id: str
    event: int
    text: str


T = TypeVar("T")


class _Newest(Generic[T]):
    def __init__(self, limit: int) -> None:
        self._limit = limit
        self._items: list[tuple[int, int, int, T]] = []
        self._serial = 0
        self.omitted = 0

    def add(self, item: T, *, event: int, result_event: int | None = None) -> None:
        entry = (event, result_event if result_event is not None else -1, self._serial, item)
        self._serial += 1
        if len(self._items) < self._limit:
            heapq.heappush(self._items, entry)
            return
        if entry[:3] > self._items[0][:3]:
            heapq.heapreplace(self._items, entry)
        self.omitted += 1

    def values(self) -> list[T]:
        return [entry[3] for entry in sorted(self._items)]


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

    root = codex_home or Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
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
    operations = _Newest[Operation](MAX_OPERATIONS)
    failures = _Newest[Failure](MAX_FAILURES)
    validation = _Newest[ValidationResult](MAX_VALIDATION)
    diagnostics: list[Diagnostic] = []
    calls: dict[str, _Call] = {}
    seen_calls: set[str] = set()
    seen_results: set[str] = set()
    questions: list[_Question] = []
    metadata: set[tuple[str, str, str | None]] = set()
    latest_user: tuple[int, str] | None = None
    cue_index: int | None = None
    cues: dict[str, list[str]] = {}
    event_count = 0
    trailing = False

    with admitted.path.open("rb") as handle:
        for raw in handle:
            if not raw.endswith(b"\n"):
                trailing = True
                break
            raw = raw[:-1]
            if raw.endswith(b"\r"):
                raw = raw[:-1]
            index = event_count
            event_count += 1
            try:
                event = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise RolloutError(f"malformed complete rollout record at event {index}") from error
            if not isinstance(event, dict):
                raise RolloutError(f"rollout event {index} is not an object")
            timestamp = _timestamp(event, index)

            if event.get("type") == "session_meta":
                _record_metadata(metadata, event, index)

            user_text = _user_text(event)
            if user_text is not None:
                latest_user = (index, user_text)
                cue_index, cues = None, {}
                questions = [question for question in questions if question.event >= index]

            assistant_text = _assistant_text(event)
            if assistant_text is not None:
                operation = Operation(
                    kind="assistant",
                    event=index,
                    timestamp=timestamp,
                    text=assistant_text,
                    status="succeeded",
                )
                operations.add(operation, event=index)
                parsed = _parse_cues(assistant_text)
                if parsed and latest_user is not None and index > latest_user[0]:
                    cue_index, cues = index, parsed

            if event.get("type") != "response_item":
                continue
            try:
                wire_item = parse_response_item(event.get("payload"))
            except WireParseError as error:
                raise RolloutError(
                    f"malformed response item at event {index}: {error}"
                ) from error
            if wire_item is None:
                continue
            if isinstance(wire_item, (FunctionCall, CustomToolCall)):
                call_id = wire_item.call_id
                name = wire_item.name
                if call_id in seen_calls:
                    raise RolloutError(f"duplicate tool call_id at event {index}: {call_id}")
                seen_calls.add(call_id)
                if isinstance(wire_item, FunctionCall):
                    family: CallFamily = "function"
                    arguments = wire_item.arguments
                    command, argv = _command_evidence(arguments)
                    input_value = None
                    if name == "request_user_input":
                        for text in _question_texts(arguments):
                            questions.append(_Question(call_id=call_id, event=index, text=text))
                else:
                    family = "custom"
                    command, argv = None, None
                    bounded = bound_utf8(wire_item.input)
                    input_value = bounded.value
                    if bounded.truncated:
                        diagnostics.append(
                            Diagnostic(
                                code="rollout.custom-input-truncated",
                                detail=(
                                    f"originalBytes={bounded.original_bytes} "
                                    f"retainedBytes={bounded.retained_bytes}"
                                ),
                                eventIndex=index,
                            )
                        )
                calls[call_id] = _Call(
                    family=family,
                    event=index,
                    name=name,
                    timestamp=timestamp,
                    command=command,
                    argv=argv,
                    input=input_value,
                )
            else:
                call_id = wire_item.call_id
                if call_id in seen_results:
                    raise RolloutError(f"duplicate tool result at event {index}: {call_id}")
                if call_id not in seen_calls or call_id not in calls:
                    raise RolloutError(f"orphan tool result at event {index}: {call_id}")
                call = calls[call_id]
                received = (
                    "function_call_output"
                    if isinstance(wire_item, FunctionCallOutput)
                    else "custom_tool_call_output"
                )
                expected = {
                    "function": "function_call_output",
                    "custom": "custom_tool_call_output",
                }[call.family]
                if received != expected:
                    raise RolloutError(
                        f"call result family mismatch at event {index}:\n"
                        f"call_id={call_id} expected={expected}\n"
                        f"received={received}"
                    )
                seen_results.add(call_id)
                calls.pop(call_id)
                output = wire_item.output
                if _contains_answer(output):
                    questions = [
                        question for question in questions if question.call_id != call_id
                    ]
                operation, failure = _complete_call(call, index, timestamp, output)
                if not _is_self_invocation(call.command, call.argv):
                    operations.add(
                        operation, event=operation.event, result_event=operation.result_event
                    )
                    if failure is not None:
                        failures.add(failure, event=failure.event)
                    classified = _classify_validation(operation)
                    if classified is not None:
                        validation.add(
                            classified,
                            event=classified.operation_event,
                            result_event=classified.result_event,
                        )

    if event_count == 0:
        raise RolloutError("rollout contains no complete events")
    _validate_metadata(metadata, admitted)
    for call in calls.values():
        if _is_self_invocation(call.command, call.argv):
            continue
        kind = classify_tool(call.name, call.family)
        operation = Operation(
            kind=kind,
            event=call.event,
            timestamp=call.timestamp,
            tool=call.name,
            argv=call.argv,
            command=call.command,
            input=call.input,
            status="pending",
        )
        operations.add(operation, event=operation.event)

    if trailing:
        diagnostics.append(
            Diagnostic(
                code="rollout.trailing-record-incomplete",
                detail="Excluded a non-newline-terminated trailing fragment.",
            )
        )
    _omission_diagnostic(diagnostics, "operations", operations.omitted)
    _omission_diagnostic(diagnostics, "failures", failures.omitted)
    _omission_diagnostic(diagnostics, "validation", validation.omitted)

    objective: DerivedValue | None = None
    if latest_user is not None:
        objective = _derived(latest_user[1], latest_user[0], "latest-user-request")
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
    for question in questions:
        if question.text not in existing_questions:
            open_questions.append(
                _derived(question.text, question.event, "structured-open-question")
            )
            existing_questions.add(question.text)

    return RolloutProjection(
        session=SessionProjection(
            rollout=str(admitted.path),
            sessionId=admitted.session_id,
            firstEvent=0,
            lastEvent=event_count - 1,
        ),
        objective=objective,
        completed=completed,
        current_operation=current,
        next_operation=next_operation,
        completion_criteria=criteria,
        operations=operations.values(),
        validation=validation.values(),
        failures=failures.values(),
        open_questions=open_questions,
        diagnostics=diagnostics,
    )


def _record_metadata(
    values: set[tuple[str, str, str | None]], event: dict[str, Any], index: int
) -> None:
    payload = event.get("payload")
    if not isinstance(payload, dict):
        raise RolloutError(f"session_meta at event {index} is malformed")
    session_id = payload.get("session_id") or payload.get("id")
    cwd = payload.get("cwd")
    rollout_id = payload.get("id")
    if not isinstance(session_id, str) or not isinstance(cwd, str):
        raise RolloutError(f"session_meta at event {index} is malformed")
    values.add((session_id, cwd, rollout_id if isinstance(rollout_id, str) else None))


def _validate_metadata(
    values: set[tuple[str, str, str | None]], admitted: AdmittedRollout
) -> None:
    if len(values) != 1:
        raise RolloutError("complete session_meta records disagree")
    session_id, cwd, _ = next(iter(values))
    if session_id != admitted.session_id or Path(cwd) != admitted.metadata_cwd:
        raise RolloutError("snapshotted session_meta differs from preliminary admission")


def _complete_call(
    call: _Call,
    result_index: int,
    result_timestamp: datetime | None,
    output: OutputBody,
) -> tuple[Operation, Failure | None]:
    if classify_tool(call.name, call.family) == "shell":
        return _complete_shell_call(call, result_index, result_timestamp, output)
    return _complete_tool_call(call, result_index, result_timestamp, output)


def _complete_shell_call(
    call: _Call,
    result_index: int,
    result_timestamp: datetime | None,
    output: OutputBody,
) -> tuple[Operation, Failure | None]:
    exit_code = _shell_exit_code(output)
    if exit_code is None:
        raise RolloutError(
            f"shell result at event {result_index} has no exit status: {call.name}"
        )
    failed = exit_code != 0
    operation = Operation(
        kind="shell",
        event=call.event,
        resultEvent=result_index,
        timestamp=call.timestamp,
        tool=call.name,
        argv=call.argv,
        command=call.command,
        input=call.input,
        exitCode=exit_code,
        status="failed" if failed else "succeeded",
    )
    if failed:
        return operation, Failure(
            kind="shell",
            tool=call.name,
            event=result_index,
            timestamp=result_timestamp or call.timestamp,
            argv=call.argv,
            command=call.command,
            input=call.input,
            exitCode=exit_code,
        )
    return operation, None


def _complete_tool_call(
    call: _Call,
    result_index: int,
    result_timestamp: datetime | None,
    output: OutputBody,
) -> tuple[Operation, Failure | None]:
    error = _explicit_tool_error(output)
    operation = Operation(
        kind="tool",
        event=call.event,
        resultEvent=result_index,
        timestamp=call.timestamp,
        tool=call.name,
        argv=call.argv,
        command=call.command,
        input=call.input,
        status="failed" if error is not None else "succeeded",
    )
    if error is not None:
        retained, truncated = _bounded_error(error)
        return operation, Failure(
            kind="tool",
            tool=call.name,
            event=result_index,
            timestamp=result_timestamp or call.timestamp,
            argv=call.argv,
            command=call.command,
            input=call.input,
            error=retained,
            truncated=truncated,
        )
    return operation, None


def _command_evidence(arguments: dict[str, object]) -> tuple[str | None, list[str] | None]:
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


def _question_texts(arguments: dict[str, object]) -> list[str]:
    questions = arguments.get("questions")
    if not isinstance(questions, list):
        return []
    return [
        question["question"]
        for question in questions
        if isinstance(question, dict)
        and isinstance(question.get("question"), str)
        and question["question"].strip()
    ]


def _contains_answer(output: Any) -> bool:
    structured = output
    if isinstance(output, str):
        try:
            structured = json.loads(output)
        except json.JSONDecodeError:
            return False
    if not isinstance(structured, dict) or "answers" not in structured:
        return False
    return _nonempty(structured["answers"])


def _nonempty(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, dict):
        return any(_nonempty(item) for item in value.values())
    if isinstance(value, list):
        return any(_nonempty(item) for item in value)
    return value is not None


def _shell_exit_code(output: OutputBody) -> int | None:
    if not isinstance(output, str):
        return None
    try:
        structured = json.loads(output)
    except json.JSONDecodeError:
        structured = None
    if isinstance(structured, dict):
        exit_code = structured.get("exit_code")
        if isinstance(exit_code, int) and not isinstance(exit_code, bool):
            return exit_code
    match = _SHELL_RESULT.search(output)
    return int(match.group(1)) if match else None


def _explicit_tool_error(output: OutputBody) -> str | None:
    if not isinstance(output, str):
        return None
    try:
        structured = json.loads(output)
    except json.JSONDecodeError:
        return None
    if not isinstance(structured, dict):
        return None
    explicit_error = structured.get("error")
    failed_status = structured.get("status") == "failed"
    if explicit_error is not None:
        return (
            explicit_error
            if isinstance(explicit_error, str)
            else json.dumps(explicit_error, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    if failed_status:
        return "tool result reported status=failed"
    return None


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


def _classify_validation(operation: Operation) -> ValidationResult | None:
    if operation.kind != "shell" or operation.result_event is None or operation.exit_code is None:
        return None
    classifier = _validation_classifier(operation.command, operation.argv)
    if classifier is None:
        return None
    status = "passed" if operation.exit_code == 0 else "failed"
    kind, name = classifier
    if kind == "test":
        return TestValidation(
            kind="test",
            framework="pytest",
            operationEvent=operation.event,
            resultEvent=operation.result_event,
            status=status,
            exitCode=operation.exit_code,
        )
    return QualificationValidation(
        kind="qualification",
        gate=name,
        operationEvent=operation.event,
        resultEvent=operation.result_event,
        status=status,
        exitCode=operation.exit_code,
    )


def _validation_classifier(
    command: str | None, argv: list[str] | None
) -> tuple[str, str] | None:
    if argv is not None:
        if _pytest_argv(argv):
            return "test", "pytest"
        if argv in (["handoff", "--help"], ["uv", "run", "handoff", "--help"]):
            return "qualification", "handoff-help"
        if argv == ["uv", "lock", "--check"]:
            return "qualification", "uv-lock-check"
        if argv[:2] == ["uv", "build"]:
            return "qualification", "uv-build"
        if argv[:2] == ["uv", "sync"] or argv[:3] == ["uv", "pip", "install"]:
            return "qualification", "uv-install"
        return None
    if command is None:
        return None
    normalized = command.strip()
    if _COMPOUND_SHELL.search(normalized):
        return None
    if _PYTEST_COMMAND.fullmatch(normalized):
        return "test", "pytest"
    for name, pattern in _QUALIFICATION_COMMANDS:
        if pattern.fullmatch(normalized):
            return "qualification", name
    return None


def _pytest_argv(argv: list[str]) -> bool:
    if not argv:
        return False
    value = argv
    if value[:2] == ["uv", "run"]:
        value = value[2:]
    if value and value[0] == "pytest":
        return True
    return len(value) >= 3 and re.fullmatch(r"python(?:3(?:\.\d+)*)?", value[0]) is not None and value[1:3] == ["-m", "pytest"]


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
            value = "\n".join(buffer).strip()
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


def _timestamp(event: dict[str, Any], index: int) -> datetime | None:
    if "timestamp" not in event:
        return None
    value = event["timestamp"]
    if not isinstance(value, str) or _RFC3339.fullmatch(value) is None:
        raise RolloutError(f"invalid timestamp at event {index}")
    try:
        timestamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RolloutError(f"invalid timestamp at event {index}") from error
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise RolloutError(f"invalid timestamp at event {index}")
    return timestamp


def _omission_diagnostic(
    diagnostics: list[Diagnostic], projection: str, count: int
) -> None:
    if count:
        diagnostics.append(
            Diagnostic(
                code=f"rollout.{projection}-omitted",
                detail=f"Omitted {count} earlier {projection} outside the retained window.",
            )
        )
