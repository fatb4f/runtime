from __future__ import annotations

from datetime import datetime
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Annotated, Literal, TypeVar

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
)

NonEmpty = Annotated[StrictStr, Field(min_length=1)]
StringList = Annotated[list[NonEmpty], Field(max_length=256)]
NonNegativeInt = Annotated[StrictInt, Field(ge=0)]
NonNegativeNumber = Annotated[StrictFloat | StrictInt, Field(ge=0)]


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value


AwareDatetime = Annotated[datetime, AfterValidator(_aware)]


def _executable_argv(value: list[str]) -> list[str]:
    if not value or value[0] == "":
        raise ValueError("argv[0] must be nonempty")
    return value


class ContractModel(BaseModel):
    model_config = ConfigDict(
        alias_generator=lambda value: value.split("_")[0]
        + "".join(part.title() for part in value.split("_")[1:]),
        populate_by_name=False,
        extra="forbid",
        strict=True,
    )


class Repository(ContractModel):
    root: Annotated[NonEmpty, Field(pattern=r"^/")]
    revision: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{40}([0-9a-f]{24})?$")]
    branch: NonEmpty | None
    dirty_paths: StringList
    staged_paths: StringList


class Validation(ContractModel):
    passing: StringList
    failing: StringList
    not_run: StringList


class Handoff(ContractModel):
    schema_: Literal["codex.handoff.v0"] = Field(alias="schema")
    created_at: AwareDatetime
    objective: NonEmpty
    invariants: StringList
    decisions: StringList
    repository: Repository
    validation: Validation
    current_operation: NonEmpty
    next_operation: NonEmpty
    completion_criteria: Annotated[list[NonEmpty], Field(min_length=1, max_length=256)]
    evidence_pointers: StringList
    open_questions: StringList


class CommandResult(ContractModel):
    schema_: Literal["codex.command-result.v0"] = Field(alias="schema")
    exit_code: StrictInt
    signal: NonNegativeInt | None
    truncated: bool
    relevant_lines: Annotated[list[StrictStr], Field(max_length=20)]
    artifact: NonEmpty
    sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]


class CommandManifest(ContractModel):
    schema_: Literal["codex.command-artifact.v0"] = Field(alias="schema")
    argv: Annotated[
        list[StrictStr], Field(min_length=1, max_length=4096), AfterValidator(_executable_argv)
    ]
    working_directory: NonEmpty
    started_at: AwareDatetime
    duration_seconds: NonNegativeNumber
    exit_code: StrictInt
    signal: NonNegativeInt | None
    stdout_bytes: NonNegativeInt
    stderr_bytes: NonNegativeInt
    stdout_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    stderr_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]

FailurePhase = Literal[
    "artifact-admission", "projection", "result-admission", "publication"
]


class CommandQuarantine(ContractModel):
    schema_: Literal["codex.command-quarantine.v0"] = Field(alias="schema")
    argv: Annotated[
        list[StrictStr], Field(min_length=1, max_length=4096), AfterValidator(_executable_argv)
    ]
    working_directory: NonEmpty
    started_at: AwareDatetime
    duration_seconds: NonNegativeNumber
    exit_code: StrictInt
    signal: NonNegativeInt | None
    stdout_bytes: NonNegativeInt
    stderr_bytes: NonNegativeInt
    stdout_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    stderr_sha256: Annotated[StrictStr, Field(pattern=r"^[0-9a-f]{64}$")]
    manifest_available: bool
    failure_phase: FailurePhase
    failure_code: NonEmpty
    failure_detail: Annotated[StrictStr, Field(max_length=2048)]


def canonical_bytes(model: BaseModel) -> bytes:
    value = model.model_dump(mode="json", by_alias=True, exclude_none=False)
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()


class ContractViolation(ValueError):
    def __init__(self, code: str, detail: str):
        self.code = code
        super().__init__(f"{code}: {detail}")


ModelT = TypeVar("ModelT", bound=BaseModel)


def _contract_root() -> Path:
    return Path(
        os.environ.get(
            "CODEX_PROFILE_CONTRACT_ROOT",
            Path(__file__).resolve().parents[2] / "contracts",
        )
    )


def _cue_vet(value: BaseModel, definition: str, code: str) -> None:
    cue = os.environ.get("CODEX_PROFILE_CUE", "cue")
    root = _contract_root()
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".json", delete=False
        ) as handle:
            handle.write(canonical_bytes(value))
            input_path = Path(handle.name)
        result = subprocess.run(
            [cue, "vet", ".", str(input_path), "-d", definition],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except (OSError, FileNotFoundError) as error:
        raise ContractViolation("contract.unavailable", str(error)) from error
    finally:
        if "input_path" in locals():
            input_path.unlink(missing_ok=True)
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip() or "CUE admission failed"
        raise ContractViolation(code, detail)


def _validate(model_type: type[ModelT], value: object, code: str) -> ModelT:
    try:
        return model_type.model_validate(value)
    except ValidationError as error:
        raise ContractViolation(code, str(error)) from error


def admit_handoff(
    value: object,
    *,
    repository_authority: Repository | None = None,
) -> Handoff:
    packet = _validate(Handoff, value, "handoff.not-ready")
    _cue_vet(packet, "#Handoff", "handoff.not-ready")
    if repository_authority is not None and (
        packet.repository.root != repository_authority.root
        or packet.repository.revision != repository_authority.revision
    ):
        raise ContractViolation(
            "repository.identity-changed", "repository root or revision differs from authority"
        )
    return packet


def admit_command_artifact(
    value: object,
    *,
    artifact_directory: Path,
) -> CommandManifest:
    manifest = _validate(CommandManifest, value, "command.output-discarded")
    _cue_vet(manifest, "#CommandArtifactManifest", "command.output-discarded")
    for name, expected_size, expected_digest in (
        ("stdout.bin", manifest.stdout_bytes, manifest.stdout_sha256),
        ("stderr.bin", manifest.stderr_bytes, manifest.stderr_sha256),
    ):
        path = artifact_directory / name
        if not path.is_file() or path.stat().st_size != expected_size:
            raise ContractViolation("command.output-discarded", f"{name} is missing or truncated")
        import hashlib

        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(64 * 1024), b""):
                digest.update(block)
        if digest.hexdigest() != expected_digest:
            raise ContractViolation("command.output-discarded", f"{name} hash mismatch")
    return manifest


def validate_command_manifest(value: object) -> CommandManifest:
    return _validate(CommandManifest, value, "command.output-discarded")


def validate_command_result(value: object) -> CommandResult:
    return _validate(CommandResult, value, "command.projection-exceeded")


def admit_command_result(
    value: object, *, limit: int = 4096, artifact_path: Path | None = None
) -> CommandResult:
    result = _validate(CommandResult, value, "command.projection-exceeded")
    _cue_vet(result, "#CommandResult", "command.projection-exceeded")
    if len(canonical_bytes(result)) > limit:
        raise ContractViolation("command.projection-exceeded", f"projection exceeds {limit} bytes")
    artifact = artifact_path or Path(result.artifact)
    if not artifact.is_file():
        raise ContractViolation("command.output-discarded", "manifest is missing")
    if __import__("hashlib").sha256(artifact.read_bytes()).hexdigest() != result.sha256:
        raise ContractViolation("command.output-discarded", "manifest hash mismatch")
    return result
