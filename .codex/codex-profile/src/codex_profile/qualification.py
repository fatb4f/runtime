from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from codex_profile.contracts import (
    ContractViolation,
    CommandManifest,
    CommandResult,
    Handoff,
    Repository,
    admit_command_artifact,
    admit_command_result,
    admit_handoff,
    canonical_bytes,
)
from codex_profile.handoff import HANDOFF_LIMIT, markdown


def _handoff_value() -> dict:
    return {
        "schema": "codex.handoff.v0",
        "createdAt": datetime(2026, 7, 23, 12, 34, 56, 123456, timezone.utc),
        "objective": "objective",
        "invariants": ["a", "b"],
        "decisions": ["one", "two"],
        "repository": {
            "root": "/tmp/repo",
            "revision": "a" * 40,
            "branch": None,
            "dirtyPaths": ["a", "b"],
            "stagedPaths": [],
        },
        "validation": {"passing": [], "failing": [], "notRun": []},
        "currentOperation": "current",
        "nextOperation": "next",
        "completionCriteria": ["done"],
        "evidencePointers": [],
        "openQuestions": [],
    }


def _authority(value: dict) -> Repository:
    return Repository.model_validate(value["repository"])


def _remove_readiness(value: dict, _: Path) -> dict:
    value.pop("nextOperation")
    return value


def _change_repository(value: dict, _: Path) -> dict:
    value["repository"]["revision"] = "b" * 40
    return value


def _exceed_handoff(value: dict, _: Path) -> dict:
    value["objective"] = "x" * (HANDOFF_LIMIT + 1)
    return value


def _reorder_handoff(value: dict, _: Path) -> dict:
    return dict(reversed(list(value.items())))


def _command_artifact(root: Path) -> tuple[dict, Path]:
    directory = root / "artifact"
    directory.mkdir()
    (directory / "stdout.bin").write_bytes(b"ok\n")
    (directory / "stderr.bin").write_bytes(b"")
    return {
        "schema": "codex.command-artifact.v0",
        "argv": ["tool", "", "--"],
        "workingDirectory": "/tmp",
        "startedAt": datetime(2026, 7, 23, tzinfo=timezone.utc),
        "durationSeconds": 0,
        "exitCode": 0,
        "signal": None,
        "stdoutBytes": 3,
        "stderrBytes": 0,
        "stdoutSha256": hashlib.sha256(b"ok\n").hexdigest(),
        "stderrSha256": hashlib.sha256(b"").hexdigest(),
    }, directory


def _remove_output(value: dict, root: Path) -> dict:
    (root / "artifact" / "stdout.bin").unlink()
    return value


def _oversized_result(root: Path) -> tuple[dict, Path]:
    manifest = root / "manifest.json"
    artifact, directory = _command_artifact(root)
    manifest.write_bytes(canonical_bytes(CommandManifest.model_validate(artifact)))
    result = {
        "schema": "codex.command-result.v0",
        "exitCode": 0,
        "signal": None,
        "truncated": True,
        "relevantLines": ["baseline"],
        "artifact": "manifest.json",
        "sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    }
    assert len(canonical_bytes(CommandResult.model_validate(result))) < 4096
    return result, manifest


def _exceed_result(value: dict, _: Path) -> dict:
    value["relevantLines"] = ["x" * 500 for _ in range(20)]
    return value


MUTATIONS = {
    "handoff.remove-readiness": _remove_readiness,
    "handoff.change-repository": _change_repository,
    "handoff.exceed-projection": _exceed_handoff,
    "handoff.reorder-input": _reorder_handoff,
    "command.remove-output": _remove_output,
    "command.exceed-projection": _exceed_result,
}


def _ordered_bytes(value: Any) -> bytes:
    def default(item: Any) -> Any:
        if isinstance(item, datetime):
            return item.isoformat().replace("+00:00", "Z")
        raise TypeError(type(item).__name__)
    return json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), default=default
    ).encode()


def _sha(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def _tree_digest(root: Path) -> str:
    entries: list[dict] = []
    if root.exists():
        for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
            relative = path.relative_to(root).as_posix()
            stat = path.lstat()
            if path.is_symlink():
                kind, data = "symlink", os.readlink(path).encode()
            elif path.is_file():
                kind, data = "file", path.read_bytes()
            elif path.is_dir():
                kind, data = "directory", b""
            else:
                kind, data = "other", b""
            entries.append({
                "path": relative,
                "kind": kind,
                "mode": stat.st_mode & 0o777,
                "length": len(data),
                "content": hashlib.sha256(data).hexdigest(),
            })
    return _sha(json.dumps(entries, sort_keys=True, separators=(",", ":")).encode())


def _semantic_digests(value: dict, operation: str) -> tuple[str, str] | None:
    if operation not in ("admit-handoff", "project-handoff"):
        return None
    try:
        packet = Handoff.model_validate(value)
    except Exception:
        return None
    return _sha(canonical_bytes(packet)), _sha(markdown(packet).encode())


def _operate_admit_handoff(value: dict, context: dict, _: dict) -> None:
    admit_handoff(value, repository_authority=context["authority"])


def _operate_project_handoff(value: dict, context: dict, case: dict) -> None:
    packet = admit_handoff(value, repository_authority=context["authority"])
    json_data, md_data = canonical_bytes(packet), markdown(packet).encode()
    if len(json_data) > HANDOFF_LIMIT or len(md_data) > HANDOFF_LIMIT:
        raise ContractViolation("handoff.size-exceeded", "projection too large")
    expected = case.get("expectedProjectionDigests")
    if expected and {
        "json": "sha256:" + hashlib.sha256(json_data).hexdigest(),
        "markdown": "sha256:" + hashlib.sha256(md_data).hexdigest(),
    } != expected:
        raise ContractViolation(
            "handoff.projection-nondeterministic", "projection digest mismatch"
        )


def _operate_admit_artifact(value: dict, context: dict, _: dict) -> None:
    admit_command_artifact(value, artifact_directory=context["directory"])


def _operate_admit_result(value: dict, context: dict, _: dict) -> None:
    admit_command_result(value, artifact_path=context["manifest"])


OPERATIONS = {
    "admit-handoff": _operate_admit_handoff,
    "project-handoff": _operate_project_handoff,
    "admit-command-artifact": _operate_admit_artifact,
    "admit-command-result": _operate_admit_result,
}


def _load_catalog(contract_root: Path) -> tuple[dict, set[str]]:
    cue = os.environ.get("CODEX_PROFILE_CUE", "cue")
    try:
        executable = subprocess.check_output(
            [cue, "export", "-e", "handoffExecutableCatalog"],
            cwd=contract_root,
            text=True,
        )
        assertions = subprocess.check_output(
            [cue, "export", "-e", "assertionCatalog"],
            cwd=contract_root,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as error:
        raise ContractViolation("contract.unavailable", str(error)) from error
    generated = json.loads(
        (contract_root / "generated/handoff-properties.json").read_text(encoding="utf-8")
    )
    exported = json.loads(executable)
    if generated != exported:
        raise ContractViolation("qualification.generated-stale", "generated property catalog is stale")
    declared = {
        key
        for key in json.loads(assertions)["properties"]
        if key.startswith(("handoff.", "command."))
    }
    return generated, declared


def qualify(report_path: Path, *, contract_root: Path | None = None) -> dict:
    root = contract_root or Path(__file__).resolve().parents[2] / "contracts"
    catalog, declared = _load_catalog(root)
    generated = set(catalog["cases"])
    if set(MUTATIONS) != {case["mutation"] for case in catalog["cases"].values()}:
        raise ContractViolation("qualification.coverage-mismatch", "mutation registry is not exact")
    if set(OPERATIONS) != {
        case["adapterOperation"] for case in catalog["cases"].values()
    }:
        raise ContractViolation("qualification.coverage-mismatch", "operation registry is not exact")
    records = []
    executed: set[str] = set()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codex-profile-qualification-") as work_name:
        work = Path(work_name)
        for property_id, case in catalog["cases"].items():
            case_root = work / property_id
            case_root.mkdir()
            if case["baseline"] == "handoff.valid":
                baseline = _handoff_value()
                context = {"authority": _authority(baseline)}
            elif case["baseline"] == "command.artifact-valid":
                baseline, directory = _command_artifact(case_root)
                context = {"directory": directory}
            else:
                baseline, manifest = _oversized_result(case_root)
                context = {"manifest": manifest}
            try:
                OPERATIONS[case["adapterOperation"]](baseline, context, case)
            except ContractViolation as error:
                raise ContractViolation(
                    "qualification.baseline-rejected",
                    f"{property_id}: {error.code}",
                ) from error
            before_raw = _sha(_ordered_bytes(baseline))
            before_tree = _tree_digest(case_root)
            before_semantic = _semantic_digests(baseline, case["adapterOperation"])
            mutated = MUTATIONS[case["mutation"]](deepcopy(baseline), case_root)
            after_raw = _sha(_ordered_bytes(mutated))
            after_tree = _tree_digest(case_root)
            after_semantic = _semantic_digests(mutated, case["adapterOperation"])
            value_changed = before_raw != after_raw
            artifacts_changed = before_tree != after_tree
            mutation_attempted = value_changed or artifacts_changed
            if not mutation_attempted:
                raise ContractViolation(
                    "qualification.mutation-not-observed", property_id
                )
            rejection_code = None
            actual = "accept"
            try:
                OPERATIONS[case["adapterOperation"]](mutated, context, case)
            except ContractViolation as error:
                actual, rejection_code = "reject", error.code
            if actual != case["expectedResult"] or rejection_code != case["rejectionCode"]:
                raise ContractViolation(
                    "qualification.case-failed",
                    f"{property_id}: got {actual}/{rejection_code}",
                )
            executed.add(property_id)
            evidence = {
                "valueChanged": value_changed,
                "artifactsChanged": artifacts_changed,
                "rawDigests": [before_raw, after_raw],
                "artifactDigests": [before_tree, after_tree],
            }
            if before_semantic is not None and after_semantic is not None:
                evidence["jsonDigests"] = [before_semantic[0], after_semantic[0]]
                evidence["markdownDigests"] = [before_semantic[1], after_semantic[1]]
            records.append({
                "id": property_id,
                "mutationAttempted": mutation_attempted,
                "actualResult": actual,
                "rejectionCode": rejection_code,
                "status": "passed",
                "evidence": evidence,
            })
    ids = sorted(executed)
    if declared != generated or generated != executed:
        raise ContractViolation("qualification.coverage-mismatch", "declared/generated/executed differ")
    report = {
        "schema": "codex-profile-property-report.v0",
        "declaredIDs": sorted(declared),
        "generatedIDs": sorted(generated),
        "executedIDs": ids,
        "reportedIDs": ids,
        "cases": records,
    }
    report_data = (json.dumps(report, indent=2, sort_keys=True) + "\n").encode()
    staged_fd, staged_name = tempfile.mkstemp(
        prefix=f".{report_path.name}.", dir=report_path.parent
    )
    staged = Path(staged_name)
    try:
        with os.fdopen(staged_fd, "wb") as handle:
            handle.write(report_data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(staged, report_path)
        directory_fd = os.open(report_path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        staged.unlink(missing_ok=True)
    persisted = json.loads(report_path.read_text(encoding="utf-8"))
    if set(persisted["reportedIDs"]) != executed:
        raise ContractViolation("qualification.coverage-mismatch", "persisted report differs")
    cue = os.environ.get("CODEX_PROFILE_CUE", "cue")
    with tempfile.NamedTemporaryFile(suffix=".json") as validation_input:
        validation_input.write(report_data)
        validation_input.flush()
        result = subprocess.run(
            [cue, "vet", ".", validation_input.name, "-d", "#QualificationReport"],
            cwd=root,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    if result.returncode:
        raise ContractViolation(
            "qualification.report-invalid",
            result.stderr.decode("utf-8", "replace").strip(),
        )
    return persisted
