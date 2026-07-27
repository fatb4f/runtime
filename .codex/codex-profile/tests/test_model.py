from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

from handoff.model import Handoff, Operation


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
