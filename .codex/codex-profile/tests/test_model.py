from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from handoff.model import Handoff, Operation, canonical_bytes


def _handoff_value() -> dict:
    oid = "a" * 40
    return {
        "schema": "codex.handoff.v0",
        "createdAt": datetime(2026, 7, 26, 23, 0),
        "repository": {
            "root": "/repo",
            "head": oid,
            "branch": "main",
            "upstream": None,
            "ahead": None,
            "behind": None,
            "indexTree": oid,
            "staged": [],
            "numstat": [],
        },
        "session": {
            "rollout": "/rollout.jsonl",
            "sessionId": "session-1",
            "firstEvent": 0,
            "lastEvent": 0,
        },
        "objective": None,
        "completed": [],
        "currentOperation": None,
        "nextOperation": None,
        "completionCriteria": [],
        "operations": [],
        "validation": [],
        "failures": [],
        "openQuestions": [],
        "diagnostics": [],
    }


def test_created_at_requires_timezone() -> None:
    with pytest.raises(ValidationError, match="timezone"):
        Handoff.model_validate(_handoff_value())


def test_unknown_fields_are_rejected() -> None:
    value = _handoff_value()
    value["createdAt"] = datetime.now().astimezone()
    value["unknown"] = True
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Handoff.model_validate(value)


def test_command_string_bound_is_rejected() -> None:
    with pytest.raises(ValidationError, match="exceeds"):
        Operation(
            kind="shell",
            event=1,
            tool="exec_command",
            command="x" * (32 * 1024 + 1),
            status="pending",
        )


@pytest.mark.parametrize(
    "update, message",
    [
        (
            lambda value: value.update(
                {
                    "objective": {
                        "value": "Work",
                        "sourceEvents": [99],
                        "derivation": "latest-user-request",
                    }
                }
            ),
            "sourceEvent",
        ),
        (
            lambda value: value["operations"].append(
                {
                    "kind": "tool",
                    "event": 1,
                    "resultEvent": 0,
                    "tool": "tool",
                    "status": "succeeded",
                }
            ),
            "precedes",
        ),
        (
            lambda value: value["diagnostics"].append(
                {"code": "bad", "eventIndex": 4}
            ),
            "diagnostic eventIndex",
        ),
        (
            lambda value: value["failures"].append(
                {
                    "kind": "tool",
                    "tool": "tool",
                    "event": 3,
                    "error": "failed",
                }
            ),
            "failure event",
        ),
    ],
)
def test_cross_object_event_integrity_is_enforced(update, message: str) -> None:
    value = _handoff_value()
    value["createdAt"] = datetime.now(timezone.utc)
    value["session"]["lastEvent"] = 1
    update(value)
    with pytest.raises(ValidationError, match=message):
        Handoff.model_validate(value)


def test_pending_operation_cannot_have_result() -> None:
    with pytest.raises(ValidationError, match="pending"):
        Operation(
            kind="tool",
            event=1,
            resultEvent=2,
            tool="tool",
            status="pending",
        )


@pytest.mark.parametrize(
    "status, exit_code, message",
    [
        ("succeeded", 1, "zero"),
        ("failed", 0, "nonzero"),
    ],
)
def test_shell_status_requires_consistent_exit_code(
    status: str, exit_code: int, message: str
) -> None:
    with pytest.raises(ValidationError, match=message):
        Operation(
            kind="shell",
            event=1,
            resultEvent=2,
            tool="exec_command",
            command="pytest",
            exitCode=exit_code,
            status=status,
        )


def test_canonical_serialization_is_deterministic() -> None:
    value = _handoff_value()
    value["createdAt"] = datetime(2026, 7, 26, 23, 0, tzinfo=timezone.utc)
    first = Handoff.model_validate(deepcopy(value))
    second = Handoff.model_validate(deepcopy(value))
    assert canonical_bytes(first) == canonical_bytes(second)
    assert b'"createdAt":"2026-07-26T23:00:00Z"' in canonical_bytes(first)


def test_validation_must_reference_matching_operation() -> None:
    value = _handoff_value()
    value["createdAt"] = datetime.now(timezone.utc)
    value["session"]["lastEvent"] = 2
    value["validation"] = [
        {
            "kind": "test",
            "framework": "pytest",
            "operationEvent": 1,
            "resultEvent": 2,
            "status": "passed",
            "exitCode": 0,
        }
    ]
    with pytest.raises(ValidationError, match="does not reference"):
        Handoff.model_validate(value)
