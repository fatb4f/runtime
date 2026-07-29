from __future__ import annotations

import json
from datetime import datetime
from typing import Annotated, Literal

from pydantic import (
    AwareDatetime,
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
MAX_VALIDATION = 256
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
        "explicit-completed",
        "explicit-current-operation",
        "explicit-next-operation",
        "explicit-completion-criteria",
        "explicit-open-question",
        "structured-open-question",
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
    timestamp: AwareDatetime | None = None
    text: Text | None = None
    tool: NonEmpty | None = None
    argv: Annotated[list[Argument], Field(max_length=MAX_ARGV)] | None = None
    command: Text | None = None
    input: Text | None = None
    session_id: StrictInt | None = Field(default=None, alias="sessionId")
    exit_code: StrictInt | None = Field(default=None, alias="exitCode")
    status: Literal["pending", "running", "succeeded", "failed"]

    @model_validator(mode="after")
    def operation_shape(self) -> "Operation":
        if sum(value is not None for value in (self.argv, self.command, self.input)) > 1:
            raise ValueError("operation evidence must use only one of argv, command, or input")
        if self.kind == "assistant":
            if (
                self.text is None
                or self.tool is not None
                or self.argv is not None
                or self.command is not None
                or self.input is not None
                or self.session_id is not None
                or self.exit_code is not None
                or self.result_event is not None
                or self.status != "succeeded"
            ):
                raise ValueError("assistant operations require text only")
            return self
        if self.tool is None or self.text is not None:
            raise ValueError("tool and shell operations require a tool name and no text")
        if self.status == "pending":
            if (
                self.result_event is not None
                or self.session_id is not None
                or self.exit_code is not None
            ):
                raise ValueError("pending operations cannot have result evidence")
            return self
        if self.status == "running":
            if self.kind != "shell":
                raise ValueError("only shell operations may be running")
            if (
                self.result_event is None
                or self.session_id is None
                or self.exit_code is not None
            ):
                raise ValueError(
                    "running shell operations require resultEvent and sessionId only"
                )
            return self
        if self.result_event is None:
            raise ValueError("completed operations require resultEvent")
        if self.kind == "shell":
            if self.session_id is not None:
                raise ValueError("completed shell operations cannot have sessionId")
            if self.status == "succeeded":
                if self.exit_code != 0:
                    raise ValueError("succeeded shell operations require exitCode zero")
            elif self.exit_code == 0:
                raise ValueError(
                    "failed shell operations require nonzero exitCode or terminal error"
                )
        elif self.session_id is not None or self.exit_code is not None:
            raise ValueError("ordinary tool operations cannot have shell result evidence")
        return self


class Failure(ClosedModel):
    kind: Literal["tool", "shell"]
    tool: NonEmpty
    event: EventIndex
    timestamp: AwareDatetime | None = None
    argv: Annotated[list[Argument], Field(max_length=MAX_ARGV)] | None = None
    command: Text | None = None
    input: Text | None = None
    exit_code: StrictInt | None = Field(default=None, alias="exitCode")
    error: StrictStr | None = None
    truncated: bool = False

    @model_validator(mode="after")
    def failure_shape(self) -> "Failure":
        if sum(value is not None for value in (self.argv, self.command, self.input)) > 1:
            raise ValueError("failure evidence must use only one of argv, command, or input")
        if self.kind == "shell":
            has_exit_failure = self.exit_code is not None and self.exit_code != 0
            has_terminal_error = self.exit_code is None and bool(self.error)
            if has_exit_failure == has_terminal_error:
                raise ValueError(
                    "shell failures require a nonzero exitCode or terminal error"
                )
        elif self.error is None:
            raise ValueError("tool failures require explicit error text")
        if self.error is not None and len(self.error.encode("utf-8")) > MAX_ERROR_BYTES:
            raise ValueError("retained error exceeds its byte bound")
        return self


class ValidationBase(ClosedModel):
    operation_event: EventIndex = Field(alias="operationEvent")
    result_event: EventIndex = Field(alias="resultEvent")
    status: Literal["passed", "failed"]
    exit_code: StrictInt = Field(alias="exitCode")

    @model_validator(mode="after")
    def result_shape(self) -> "ValidationBase":
        if self.result_event < self.operation_event:
            raise ValueError("validation resultEvent precedes operationEvent")
        if (self.status == "passed") != (self.exit_code == 0):
            raise ValueError("validation status disagrees with exitCode")
        return self


class TestValidation(ValidationBase):
    kind: Literal["test"]
    framework: Literal["pytest"]


class QualificationValidation(ValidationBase):
    kind: Literal["qualification"]
    gate: Literal["handoff-help", "uv-lock-check", "uv-build", "uv-install"]


ValidationResult = Annotated[
    TestValidation | QualificationValidation,
    Field(discriminator="kind"),
]


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
    validation: Annotated[list[ValidationResult], Field(max_length=MAX_VALIDATION)]
    failures: Annotated[list[Failure], Field(max_length=MAX_FAILURES)]
    open_questions: list[DerivedValue] = Field(alias="openQuestions")
    diagnostics: list[Diagnostic]

    @model_validator(mode="after")
    def integrity(self) -> "Handoff":
        if self.created_at.tzinfo is None or self.created_at.utcoffset() is None:
            raise ValueError("createdAt must include a timezone")
        first = self.session.first_event
        last = self.session.last_event

        def require_event(value: int, label: str) -> None:
            if value < first or value > last:
                raise ValueError(f"{label} is outside session bounds")

        derived = [
            *(([self.objective] if self.objective is not None else [])),
            *self.completed,
            *(([self.current_operation] if self.current_operation is not None else [])),
            *(([self.next_operation] if self.next_operation is not None else [])),
            *self.completion_criteria,
            *self.open_questions,
        ]
        for item in derived:
            for event in item.source_events:
                require_event(event, "sourceEvent")
        for operation in self.operations:
            require_event(operation.event, "operation event")
            if operation.result_event is not None:
                require_event(operation.result_event, "operation resultEvent")
                if operation.result_event < operation.event:
                    raise ValueError("operation resultEvent precedes event")
        if self.operations != sorted(
            self.operations, key=lambda item: (item.event, item.result_event or -1)
        ):
            raise ValueError("operations must be chronological")
        for failure in self.failures:
            require_event(failure.event, "failure event")
        if self.failures != sorted(self.failures, key=lambda item: item.event):
            raise ValueError("failures must be chronological")
        operation_results = {
            (operation.event, operation.result_event): operation
            for operation in self.operations
            if operation.result_event is not None
        }
        for result in self.validation:
            require_event(result.operation_event, "validation operationEvent")
            require_event(result.result_event, "validation resultEvent")
            operation = operation_results.get((result.operation_event, result.result_event))
            if operation is None:
                raise ValueError("validation result does not reference an operation")
            if operation.kind != "shell" or operation.exit_code != result.exit_code:
                raise ValueError("validation result disagrees with its operation")
        if self.validation != sorted(
            self.validation, key=lambda item: (item.operation_event, item.result_event)
        ):
            raise ValueError("validation results must be chronological")
        for diagnostic in self.diagnostics:
            if diagnostic.event_index is not None:
                require_event(diagnostic.event_index, "diagnostic eventIndex")
        return self


def canonical_bytes(value: Handoff) -> bytes:
    document = value.model_dump(mode="json", by_alias=True, exclude_none=False)
    data = (json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )
    if len(data) > HANDOFF_MAX_BYTES:
        raise ValueError(f"handoff exceeds {HANDOFF_MAX_BYTES} bytes")
    return data
