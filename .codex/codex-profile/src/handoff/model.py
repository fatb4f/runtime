from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    StrictStr,
    model_validator,
)

HANDOFF_MAX_BYTES = 1024 * 1024
MAX_OPERATIONS = 2048
MAX_FAILURES = 256
MAX_SOURCE_EVENTS = 64
MAX_COMMAND_BYTES = 32 * 1024
MAX_ARGV = 256
MAX_ARG_BYTES = 8 * 1024
MAX_ERROR_BYTES = 8 * 1024


def _utf8_limit(limit: int):
    def validate(value: str) -> str:
        if len(value.encode("utf-8")) > limit:
            raise ValueError(f"UTF-8 value exceeds {limit} bytes")
        return value

    return validate


NonEmpty = Annotated[StrictStr, Field(min_length=1)]
Text = Annotated[StrictStr, AfterValidator(_utf8_limit(MAX_COMMAND_BYTES))]
Argument = Annotated[StrictStr, AfterValidator(_utf8_limit(MAX_ARG_BYTES))]
EventIndex = Annotated[StrictInt, Field(ge=0)]
GitOID = Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$")]
SessionID = Annotated[StrictStr, Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]{0,255}$")]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)


class DerivedValue(ClosedModel):
    value: Text
    source_events: Annotated[list[EventIndex], Field(alias="sourceEvents", max_length=MAX_SOURCE_EVENTS)]
    derivation: Literal[
        "latest-user-request",
        "explicit-objective",
        "explicit-completed",
        "explicit-current-operation",
        "explicit-next-operation",
        "explicit-completion-criteria",
        "explicit-open-question",
        "structured-open-question",
        "git-staged-change",
    ]

    @model_validator(mode="after")
    def ordered_events(self) -> "DerivedValue":
        if self.source_events != sorted(set(self.source_events)):
            raise ValueError("sourceEvents must be sorted and unique")
        return self


class Diagnostic(ClosedModel):
    code: NonEmpty
    detail: Text | None = None
    event_index: EventIndex | None = Field(default=None, alias="eventIndex")


class StagedEntry(ClosedModel):
    status: Literal["A", "M", "D", "R"]
    path: NonEmpty
    source_path: NonEmpty | None = Field(default=None, alias="sourcePath")

    @model_validator(mode="after")
    def rename_shape(self) -> "StagedEntry":
        if (self.status == "R") != (self.source_path is not None):
            raise ValueError("sourcePath is required only for renames")
        return self


class NumstatEntry(ClosedModel):
    path: NonEmpty
    source_path: NonEmpty | None = Field(default=None, alias="sourcePath")
    added_lines: Annotated[StrictInt, Field(ge=0)] | None = Field(alias="addedLines")
    deleted_lines: Annotated[StrictInt, Field(ge=0)] | None = Field(alias="deletedLines")
    binary: bool

    @model_validator(mode="after")
    def binary_shape(self) -> "NumstatEntry":
        if self.binary != (self.added_lines is None and self.deleted_lines is None):
            raise ValueError("binary entries require null line counts")
        return self


class RepositoryProjection(ClosedModel):
    root: NonEmpty
    head: GitOID
    branch: NonEmpty | None
    upstream: NonEmpty | None
    ahead: Annotated[StrictInt, Field(ge=0)] | None
    behind: Annotated[StrictInt, Field(ge=0)] | None
    index_tree: GitOID = Field(alias="indexTree")
    staged: list[StagedEntry]
    numstat: list[NumstatEntry]


class SessionProjection(ClosedModel):
    rollout: NonEmpty
    session_id: SessionID = Field(alias="sessionId")
    first_event: EventIndex = Field(alias="firstEvent")
    last_event: EventIndex = Field(alias="lastEvent")

    @model_validator(mode="after")
    def event_bounds(self) -> "SessionProjection":
        if self.last_event < self.first_event:
            raise ValueError("lastEvent precedes firstEvent")
        return self


class Operation(ClosedModel):
    kind: Literal["assistant", "tool", "shell"]
    event: EventIndex
    result_event: EventIndex | None = Field(default=None, alias="resultEvent")
    timestamp: NonEmpty | None = None
    text: Text | None = None
    tool: NonEmpty | None = None
    argv: Annotated[list[Argument], Field(max_length=MAX_ARGV)] | None = None
    command: Text | None = None
    exit_code: StrictInt | None = Field(default=None, alias="exitCode")
    status: Literal["pending", "succeeded", "failed"]

    @model_validator(mode="after")
    def operation_shape(self) -> "Operation":
        if self.argv is not None and self.command is not None:
            raise ValueError("command evidence cannot contain both argv and command")
        if self.kind == "assistant":
            if self.text is None or self.tool is not None:
                raise ValueError("assistant operations require text only")
        elif self.tool is None:
            raise ValueError("tool and shell operations require a tool name")
        return self


class Failure(ClosedModel):
    kind: Literal["tool", "shell"]
    tool: NonEmpty
    event: EventIndex
    timestamp: NonEmpty | None = None
    argv: Annotated[list[Argument], Field(max_length=MAX_ARGV)] | None = None
    command: Text | None = None
    exit_code: StrictInt | None = Field(default=None, alias="exitCode")
    error: StrictStr | None = None
    truncated: bool = False

    @model_validator(mode="after")
    def failure_shape(self) -> "Failure":
        if self.argv is not None and self.command is not None:
            raise ValueError("failure cannot contain both argv and command")
        if self.kind == "shell":
            if self.exit_code is None or self.exit_code == 0 or self.error is not None:
                raise ValueError("shell failures require a nonzero exitCode")
        elif self.error is None:
            raise ValueError("tool failures require explicit error text")
        if self.error is not None and len(self.error.encode("utf-8")) > MAX_ERROR_BYTES:
            raise ValueError("retained error exceeds its byte bound")
        return self


class Handoff(ClosedModel):
    schema_: Literal["codex.handoff.v0"] = Field(alias="schema")
    created_at: datetime = Field(alias="createdAt")
    repository: RepositoryProjection
    session: SessionProjection
    objective: DerivedValue | None
    completed: list[DerivedValue]
    current_operation: DerivedValue | None = Field(alias="currentOperation")
    next_operation: DerivedValue | None = Field(alias="nextOperation")
    completion_criteria: list[DerivedValue] = Field(alias="completionCriteria")
    operations: Annotated[list[Operation], Field(max_length=MAX_OPERATIONS)]
    failures: Annotated[list[Failure], Field(max_length=MAX_FAILURES)]
    open_questions: list[DerivedValue] = Field(alias="openQuestions")
    diagnostics: list[Diagnostic]

    @model_validator(mode="after")
    def aware_created_at(self) -> "Handoff":
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("createdAt must include a timezone")
        return self


def canonical_bytes(value: Handoff) -> bytes:
    document = value.model_dump(mode="json", by_alias=True, exclude_none=False)
    data = (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if len(data) > HANDOFF_MAX_BYTES:
        raise ValueError(f"handoff exceeds {HANDOFF_MAX_BYTES} bytes")
    return data
