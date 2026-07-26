"""CUE-derived evidence authority matrix and metamorphic transition projection."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, model_validator

from context_workbook.context_graph_properties import (
    ClaimAuthority,
    ContextEvidence,
    StrictModel,
    _run_cue,
    cue_vet,
    model_root,
)

EvidenceKind = Literal[
    "source",
    "observation",
    "diagnostic",
    "attestation",
    "validation-result",
]
AuthorityExpectedResult = Literal["accept", "reject"]

EVIDENCE_KINDS: tuple[str, ...] = (
    "source",
    "observation",
    "diagnostic",
    "attestation",
    "validation-result",
)
AUTHORITY_LEVELS: tuple[str, ...] = ("none", "candidate", "controller", "root")
COLLECTED_EVIDENCE_KINDS: tuple[str, ...] = (
    "observation",
    "diagnostic",
    "attestation",
    "validation-result",
)


class EvidenceAuthorityCase(StrictModel):
    id: str
    kind: EvidenceKind
    authority: ClaimAuthority
    expected: AuthorityExpectedResult


class EvidenceAuthorityMatrix(StrictModel):
    schema_: Literal["kernel.context-evidence-authority-matrix.v0"] = Field(
        alias="schema"
    )
    cases: dict[str, EvidenceAuthorityCase]

    @model_validator(mode="after")
    def keys_match_ids(self) -> "EvidenceAuthorityMatrix":
        mismatches = [key for key, value in self.cases.items() if key != value.id]
        if mismatches:
            raise ValueError(
                f"authority case map key does not match id: {mismatches[0]}"
            )
        return self


class AuthorityBoundContextEvidence(ContextEvidence):
    @model_validator(mode="after")
    def collected_authority_is_bounded(self) -> "AuthorityBoundContextEvidence":
        if self.kind != "source" and self.authority not in {"none", "candidate"}:
            raise ValueError(
                "collected evidence cannot claim controller or root authority"
            )
        return self


class EvidenceKindOnlyTransition(StrictModel):
    schema_: Literal["kernel.context-evidence-kind-transition.v0"] = Field(
        alias="schema"
    )
    before: AuthorityBoundContextEvidence
    after: AuthorityBoundContextEvidence
    admission_id: None = Field(alias="admissionID")

    @model_validator(mode="after")
    def only_kind_changes(self) -> "EvidenceKindOnlyTransition":
        before = self.before.model_dump(by_alias=True, exclude_none=False)
        after = self.after.model_dump(by_alias=True, exclude_none=False)
        before.pop("kind")
        after.pop("kind")
        if before != after:
            raise ValueError(
                "kind-only transition changed evidence state or authority"
            )
        return self


@lru_cache(maxsize=1)
def load_evidence_authority_matrix() -> EvidenceAuthorityMatrix:
    completed = _run_cue(
        "export",
        str(model_root()),
        "-e",
        "contextEvidenceAuthorityMatrix",
        "--out",
        "json",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"CUE authority matrix export failed: {completed.stderr.strip()}"
        )
    return EvidenceAuthorityMatrix.model_validate_json(completed.stdout)


def minimal_evidence(kind: str, authority: str) -> dict[str, Any]:
    return {
        "kind": kind,
        "subject": None,
        "producer": None,
        "source": {
            "kind": "authority-matrix",
            "repository": "fatb4f/dotfiles",
            "revision": "generated",
        },
        "authority": authority,
        "diagnostics": [],
    }


def expected_authority_case_ids() -> set[str]:
    return {
        f"authority.{kind}.{authority}"
        for kind in EVIDENCE_KINDS
        for authority in AUTHORITY_LEVELS
    }


def validate_authority_matrix_coverage(matrix: EvidenceAuthorityMatrix) -> None:
    expected = expected_authority_case_ids()
    generated = set(matrix.cases)
    if generated != expected:
        raise AssertionError(
            "authority matrix coverage mismatch: "
            f"missing={sorted(expected - generated)}, "
            f"orphaned={sorted(generated - expected)}"
        )
    for case_id, case in matrix.cases.items():
        expected_id = f"authority.{case.kind}.{case.authority}"
        if case_id != expected_id:
            raise AssertionError(
                f"authority case identity mismatch: {case_id} != {expected_id}"
            )


def pydantic_accepts_evidence(value: dict[str, Any]) -> bool:
    try:
        AuthorityBoundContextEvidence.model_validate(value)
    except ValueError:
        return False
    return True


def pydantic_accepts_transition(value: dict[str, Any]) -> bool:
    try:
        EvidenceKindOnlyTransition.model_validate(value)
    except ValueError:
        return False
    return True


def execute_authority_matrix(matrix: EvidenceAuthorityMatrix) -> dict[str, Any]:
    validate_authority_matrix_coverage(matrix)
    executed: dict[str, Any] = {}

    for case_id, case in sorted(matrix.cases.items()):
        evidence = minimal_evidence(case.kind, case.authority)
        cue_accepted = cue_vet("#ContextEvidence", evidence).accepted
        pydantic_accepted = pydantic_accepts_evidence(evidence)
        expected = case.expected == "accept"

        if cue_accepted != expected:
            raise AssertionError(f"CUE authority outcome mismatch for {case_id}")
        if pydantic_accepted != expected:
            raise AssertionError(
                f"Pydantic authority outcome mismatch for {case_id}"
            )

        executed[case_id] = {
            "expected": case.expected,
            "cueAccepted": cue_accepted,
            "pydanticAccepted": pydantic_accepted,
        }

    expected_ids = expected_authority_case_ids()
    executed_ids = set(executed)
    report = {
        "schema": "kernel.context-evidence-authority-report.v0",
        "expectedCaseIDs": sorted(expected_ids),
        "generatedCaseIDs": sorted(matrix.cases),
        "executedCaseIDs": sorted(executed_ids),
        "reportedCaseIDs": sorted(executed),
        "cases": executed,
    }

    for key in ("generatedCaseIDs", "executedCaseIDs", "reportedCaseIDs"):
        if set(report[key]) != expected_ids:
            raise AssertionError(f"authority report set mismatch: {key}")

    return report


def build_kind_only_transition(
    before_kind: str,
    after_kind: str,
    before_authority: str,
    after_authority: str,
) -> dict[str, Any]:
    before = minimal_evidence(before_kind, before_authority)
    after = minimal_evidence(after_kind, after_authority)
    return {
        "schema": "kernel.context-evidence-kind-transition.v0",
        "before": before,
        "after": after,
        "admissionID": None,
    }
