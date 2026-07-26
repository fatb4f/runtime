"""CUE-derived evidence admission matrix and authority-transition oracle."""

from __future__ import annotations

import copy
from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, model_validator

from context_workbook.context_graph_authority import (
    AUTHORITY_LEVELS,
    AuthorityBoundContextEvidence,
)
from context_workbook.context_graph_properties import (
    ClaimAuthority,
    ContextEntityRef,
    StrictModel,
    _run_cue,
    cue_vet,
    model_root,
)

AdmissionScenario = Literal[
    "no-admission",
    "valid-admission",
    "wrong-evidence-id",
    "wrong-evidence-digest",
    "wrong-snapshot",
    "wrong-policy-digest",
    "unknown-field",
]
AdmissionExpectedResult = Literal["accept", "reject"]

GRAPH_ID_PATTERN = r"^[a-z0-9]+([._:/-][a-z0-9]+)*$"
DIGEST_PATTERN = r"^sha256:[0-9a-f]{64}$"
CONTENT_DIGEST_PATTERN = r"^[a-z0-9][a-z0-9._-]*:[0-9a-f]+$"

ADMISSION_SCENARIOS: tuple[str, ...] = (
    "no-admission",
    "valid-admission",
    "wrong-evidence-id",
    "wrong-evidence-digest",
    "wrong-snapshot",
    "wrong-policy-digest",
    "unknown-field",
)
AUTHORITY_RANK: dict[str, int] = {
    "none": 0,
    "candidate": 1,
    "controller": 2,
    "root": 3,
}


class EvidenceAuthorityState(StrictModel):
    schema_: Literal["kernel.context-evidence-authority-state.v0"] = Field(alias="schema")
    evidence_id: str = Field(alias="evidenceID", pattern=GRAPH_ID_PATTERN)
    snapshot_id: str = Field(alias="snapshotID", pattern=DIGEST_PATTERN)
    evidence: AuthorityBoundContextEvidence
    effective_authority: ClaimAuthority = Field(alias="effectiveAuthority")

    @model_validator(mode="after")
    def state_is_digest_bound_and_non_demotion(self) -> "EvidenceAuthorityState":
        if self.evidence.payload_digest is None:
            raise ValueError("authority state requires evidence payloadDigest")
        if AUTHORITY_RANK[self.effective_authority] < AUTHORITY_RANK[self.evidence.authority]:
            raise ValueError("effective authority cannot be below evidence authority")
        return self


class CollectedEvidenceEnvelope(StrictModel):
    schema_: Literal["kernel.context-evidence-collection.v0"] = Field(alias="schema")
    state: EvidenceAuthorityState
    admission: None

    @model_validator(mode="after")
    def collection_is_bounded_for_every_evidence_kind(self) -> "CollectedEvidenceEnvelope":
        if self.state.evidence.authority not in {"none", "candidate"}:
            raise ValueError("collection evidence cannot claim controller or root authority")
        if self.state.effective_authority != self.state.evidence.authority:
            raise ValueError("collection cannot widen effective authority")
        return self


class EvidenceAdmissionRecord(StrictModel):
    schema_: Literal["kernel.context-evidence-admission-record.v0"] = Field(alias="schema")
    admission_id: str = Field(alias="admissionID", pattern=GRAPH_ID_PATTERN)
    decision_digest: str = Field(alias="decisionDigest", pattern=DIGEST_PATTERN)
    evidence_id: str = Field(alias="evidenceID", pattern=GRAPH_ID_PATTERN)
    evidence_digest: str = Field(alias="evidenceDigest", pattern=CONTENT_DIGEST_PATTERN)
    source_snapshot_id: str = Field(alias="sourceSnapshotID", pattern=DIGEST_PATTERN)
    policy_digest: str = Field(alias="policyDigest", pattern=DIGEST_PATTERN)
    actor: ContextEntityRef
    from_authority: ClaimAuthority = Field(alias="from")
    to_authority: ClaimAuthority = Field(alias="to")


class EvidenceNoAdmissionTransition(StrictModel):
    schema_: Literal["kernel.context-evidence-no-admission-transition.v0"] = Field(alias="schema")
    before: EvidenceAuthorityState
    after: EvidenceAuthorityState
    admission: None

    @model_validator(mode="after")
    def no_admission_preserves_intrinsic_state(self) -> "EvidenceNoAdmissionTransition":
        if self.before.effective_authority != self.before.evidence.authority:
            raise ValueError("no-admission transition starts from unadmitted authority")
        if self.before != self.after:
            raise ValueError("authority changed without admission")
        return self


class EvidenceAdmissionTransition(StrictModel):
    schema_: Literal["kernel.context-evidence-admission-transition.v0"] = Field(alias="schema")
    policy_digest: str = Field(alias="policyDigest", pattern=DIGEST_PATTERN)
    before: EvidenceAuthorityState
    after: EvidenceAuthorityState
    admission: EvidenceAdmissionRecord

    @model_validator(mode="after")
    def transition_is_bound_and_monotonic(self) -> "EvidenceAdmissionTransition":
        if self.before.effective_authority != self.before.evidence.authority:
            raise ValueError("admission transition starts from unadmitted authority")
        before = self.before.model_dump(by_alias=True, exclude_none=False)
        after = self.after.model_dump(by_alias=True, exclude_none=False)
        before_authority = before.pop("effectiveAuthority")
        after_authority = after.pop("effectiveAuthority")
        if before != after:
            raise ValueError("admission changed evidence identity or state")
        if AUTHORITY_RANK[after_authority] < AUTHORITY_RANK[before_authority]:
            raise ValueError("authority demotion is not an admitted transition")
        payload_digest = self.before.evidence.payload_digest
        bindings = {
            "evidenceID": self.before.evidence_id,
            "evidenceDigest": payload_digest,
            "sourceSnapshotID": self.before.snapshot_id,
            "policyDigest": self.policy_digest,
            "from": before_authority,
            "to": after_authority,
        }
        record = self.admission.model_dump(by_alias=True, exclude_none=False)
        mismatches = [key for key, value in bindings.items() if record[key] != value]
        if mismatches:
            raise ValueError(f"admission binding mismatch: {mismatches[0]}")
        return self


class EvidenceAuthorityProjection(StrictModel):
    schema_: Literal["kernel.context-evidence-authority-projection.v0"] = Field(alias="schema")
    projection_kind: str = Field(alias="projectionKind", pattern=GRAPH_ID_PATTERN)
    source: EvidenceAuthorityState
    projected: EvidenceAuthorityState

    @model_validator(mode="after")
    def projection_preserves_authority(self) -> "EvidenceAuthorityProjection":
        if self.source != self.projected:
            raise ValueError("projection changed evidence authority state")
        return self


class EvidenceAdmissionBundle(StrictModel):
    schema_: Literal["kernel.context-evidence-admission-bundle.v0"] = Field(alias="schema")
    states: dict[str, EvidenceAuthorityState]
    admissions: dict[str, EvidenceAdmissionTransition]

    @model_validator(mode="after")
    def bundle_is_admission_closed(self) -> "EvidenceAdmissionBundle":
        state_mismatches = [
            key for key, value in self.states.items() if key != value.evidence_id
        ]
        if state_mismatches:
            raise ValueError(
                f"state map key does not match evidenceID: {state_mismatches[0]}"
            )
        admission_mismatches = [
            key
            for key, value in self.admissions.items()
            if key != value.admission.admission_id
        ]
        if admission_mismatches:
            raise ValueError(
                "admission map key does not match admissionID: "
                f"{admission_mismatches[0]}"
            )

        admissions_by_state: dict[str, list[EvidenceAdmissionTransition]] = {}
        for transition in self.admissions.values():
            state_id = transition.after.evidence_id
            stored_state = self.states.get(state_id)
            if stored_state is None:
                raise ValueError(f"admission state is missing: {state_id}")
            if stored_state != transition.after:
                raise ValueError(f"stored state does not match admission after-state: {state_id}")
            admissions_by_state.setdefault(state_id, []).append(transition)

        for state_id, state in self.states.items():
            if AUTHORITY_RANK[state.effective_authority] > AUTHORITY_RANK[state.evidence.authority]:
                qualifying = admissions_by_state.get(state_id, [])
                if len(qualifying) != 1:
                    raise ValueError(
                        "elevated authority state requires exactly one admission: "
                        f"{state_id}"
                    )
        return self


class EvidenceAdmissionCase(StrictModel):
    id: str
    from_authority: ClaimAuthority = Field(alias="from")
    to_authority: ClaimAuthority = Field(alias="to")
    scenario: AdmissionScenario
    expected: AdmissionExpectedResult


class EvidenceAdmissionMatrix(StrictModel):
    schema_: Literal["kernel.context-evidence-admission-matrix.v0"] = Field(alias="schema")
    cases: dict[str, EvidenceAdmissionCase]

    @model_validator(mode="after")
    def keys_match_ids(self) -> "EvidenceAdmissionMatrix":
        mismatches = [key for key, value in self.cases.items() if key != value.id]
        if mismatches:
            raise ValueError(f"admission case map key does not match id: {mismatches[0]}")
        return self


TRANSPORT_MODELS: dict[str, type[StrictModel]] = {
    "#ContextEvidenceAuthorityState": EvidenceAuthorityState,
    "#ContextCollectedEvidenceEnvelope": CollectedEvidenceEnvelope,
    "#ContextEvidenceAdmissionRecord": EvidenceAdmissionRecord,
    "#ContextEvidenceNoAdmissionTransition": EvidenceNoAdmissionTransition,
    "#ContextEvidenceAdmissionTransition": EvidenceAdmissionTransition,
    "#ContextEvidenceAuthorityProjection": EvidenceAuthorityProjection,
    "#ContextEvidenceAdmissionBundle": EvidenceAdmissionBundle,
}


@lru_cache(maxsize=1)
def load_evidence_admission_matrix() -> EvidenceAdmissionMatrix:
    completed = _run_cue(
        "export",
        str(model_root()),
        "-e",
        "contextEvidenceAdmissionMatrix",
        "--out",
        "json",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"CUE admission matrix export failed: {completed.stderr.strip()}")
    return EvidenceAdmissionMatrix.model_validate_json(completed.stdout)


def expected_admission_case_ids() -> set[str]:
    return {
        f"admission.{from_authority}.{to_authority}.{scenario}"
        for from_authority in AUTHORITY_LEVELS
        for to_authority in AUTHORITY_LEVELS
        for scenario in ADMISSION_SCENARIOS
    }


def validate_admission_matrix_coverage(matrix: EvidenceAdmissionMatrix) -> None:
    expected = expected_admission_case_ids()
    generated = set(matrix.cases)
    if generated != expected:
        raise AssertionError(
            "admission matrix coverage mismatch: "
            f"missing={sorted(expected - generated)}, orphaned={sorted(generated - expected)}"
        )


def minimal_evidence(
    authority: str = "candidate",
    *,
    kind: str | None = None,
) -> dict[str, Any]:
    evidence_kind = kind or (
        "source" if authority in {"controller", "root"} else "observation"
    )
    return {
        "kind": evidence_kind,
        "subject": {"kind": "member", "id": "member.context-evidence"},
        "producer": {"kind": "member", "id": "member.context-hydrator"},
        "source": {
            "kind": "repository-hydrator",
            "repository": "fatb4f/dotfiles",
            "revision": "main",
            "path": ".codex/context-model/context_graph_admission.cue",
        },
        "authority": authority,
        "payloadDigest": "sha256:" + "1" * 64,
        "diagnostics": [],
    }


def build_authority_state(
    effective_authority: str,
    *,
    evidence_authority: str | None = None,
    evidence_kind: str | None = None,
    evidence_id: str = "evidence.context-admission",
    snapshot_id: str | None = None,
) -> dict[str, Any]:
    intrinsic_authority = evidence_authority or effective_authority
    return {
        "schema": "kernel.context-evidence-authority-state.v0",
        "evidenceID": evidence_id,
        "snapshotID": snapshot_id or "sha256:" + "2" * 64,
        "evidence": minimal_evidence(intrinsic_authority, kind=evidence_kind),
        "effectiveAuthority": effective_authority,
    }


def build_admission_transition(
    from_authority: str,
    to_authority: str,
    scenario: str = "valid-admission",
) -> dict[str, Any]:
    before = build_authority_state(
        from_authority,
        evidence_authority=from_authority,
    )
    after = copy.deepcopy(before)
    after["effectiveAuthority"] = to_authority
    if scenario == "no-admission":
        return {
            "schema": "kernel.context-evidence-no-admission-transition.v0",
            "before": before,
            "after": after,
            "admission": None,
        }

    value: dict[str, Any] = {
        "schema": "kernel.context-evidence-admission-transition.v0",
        "policyDigest": "sha256:" + "3" * 64,
        "before": before,
        "after": after,
        "admission": {
            "schema": "kernel.context-evidence-admission-record.v0",
            "admissionID": "admission.context-evidence",
            "decisionDigest": "sha256:" + "4" * 64,
            "evidenceID": before["evidenceID"],
            "evidenceDigest": before["evidence"]["payloadDigest"],
            "sourceSnapshotID": before["snapshotID"],
            "policyDigest": "sha256:" + "3" * 64,
            "actor": {"kind": "member", "id": "member.context-controller"},
            "from": from_authority,
            "to": to_authority,
        },
    }
    if scenario == "wrong-evidence-id":
        value["admission"]["evidenceID"] = "evidence.other"
    elif scenario == "wrong-evidence-digest":
        value["admission"]["evidenceDigest"] = "sha256:" + "5" * 64
    elif scenario == "wrong-snapshot":
        value["admission"]["sourceSnapshotID"] = "sha256:" + "6" * 64
    elif scenario == "wrong-policy-digest":
        value["admission"]["policyDigest"] = "sha256:" + "7" * 64
    elif scenario == "unknown-field":
        value["unexpected"] = True
    elif scenario != "valid-admission":
        raise ValueError(f"unsupported admission scenario: {scenario}")
    return value


def build_collected_envelope(
    *,
    evidence_authority: str = "candidate",
    evidence_kind: str | None = None,
) -> dict[str, Any]:
    state = build_authority_state(
        evidence_authority,
        evidence_authority=evidence_authority,
        evidence_kind=evidence_kind,
    )
    return {
        "schema": "kernel.context-evidence-collection.v0",
        "state": state,
        "admission": None,
    }


def build_authority_projection() -> dict[str, Any]:
    state = build_authority_state("candidate", evidence_authority="candidate")
    return {
        "schema": "kernel.context-evidence-authority-projection.v0",
        "projectionKind": "duckdb-materialization",
        "source": state,
        "projected": copy.deepcopy(state),
    }


def build_admission_bundle() -> dict[str, Any]:
    transition = build_admission_transition("candidate", "controller")
    return {
        "schema": "kernel.context-evidence-admission-bundle.v0",
        "states": {transition["after"]["evidenceID"]: transition["after"]},
        "admissions": {transition["admission"]["admissionID"]: transition},
    }


def valid_transport_instances() -> dict[str, dict[str, Any]]:
    transition = build_admission_transition("candidate", "controller")
    return {
        "#ContextEvidenceAuthorityState": build_authority_state(
            "candidate", evidence_authority="candidate"
        ),
        "#ContextCollectedEvidenceEnvelope": build_collected_envelope(),
        "#ContextEvidenceAdmissionRecord": copy.deepcopy(transition["admission"]),
        "#ContextEvidenceNoAdmissionTransition": build_admission_transition(
            "candidate", "candidate", "no-admission"
        ),
        "#ContextEvidenceAdmissionTransition": transition,
        "#ContextEvidenceAuthorityProjection": build_authority_projection(),
        "#ContextEvidenceAdmissionBundle": build_admission_bundle(),
    }


def unknown_field_transport_cases() -> dict[str, tuple[str, dict[str, Any]]]:
    valid = valid_transport_instances()
    cases: dict[str, tuple[str, dict[str, Any]]] = {}
    for definition, instance in valid.items():
        malformed = copy.deepcopy(instance)
        malformed["unexpected"] = True
        cases[f"{definition}.top-level"] = (definition, malformed)

    transition = copy.deepcopy(valid["#ContextEvidenceAdmissionTransition"])
    transition["admission"]["unexpected"] = True
    cases["#ContextEvidenceAdmissionTransition.nested-admission"] = (
        "#ContextEvidenceAdmissionTransition",
        transition,
    )
    transition = copy.deepcopy(valid["#ContextEvidenceAdmissionTransition"])
    transition["before"]["unexpected"] = True
    cases["#ContextEvidenceAdmissionTransition.nested-before"] = (
        "#ContextEvidenceAdmissionTransition",
        transition,
    )
    transition = copy.deepcopy(valid["#ContextEvidenceAdmissionTransition"])
    transition["after"]["evidence"]["source"]["unexpected"] = True
    cases["#ContextEvidenceAdmissionTransition.nested-evidence-source"] = (
        "#ContextEvidenceAdmissionTransition",
        transition,
    )
    return cases


def pydantic_accepts_transport(definition: str, value: dict[str, Any]) -> bool:
    model = TRANSPORT_MODELS[definition]
    try:
        model.model_validate(value)
    except ValueError:
        return False
    return True


def execute_transport_unknown_field_cases() -> dict[str, Any]:
    cases = unknown_field_transport_cases()
    executed: dict[str, Any] = {}
    for case_id, (definition, value) in sorted(cases.items()):
        cue_accepted = cue_vet(definition, value).accepted
        pydantic_accepted = pydantic_accepts_transport(definition, value)
        if cue_accepted or pydantic_accepted:
            raise AssertionError(
                f"unknown-field transport case accepted: {case_id} "
                f"cue={cue_accepted} pydantic={pydantic_accepted}"
            )
        executed[case_id] = {
            "definition": definition,
            "cueAccepted": cue_accepted,
            "pydanticAccepted": pydantic_accepted,
        }
    expected_ids = set(cases)
    report = {
        "schema": "kernel.context-evidence-transport-unknown-field-report.v0",
        "expectedCaseIDs": sorted(expected_ids),
        "generatedCaseIDs": sorted(cases),
        "executedCaseIDs": sorted(executed),
        "reportedCaseIDs": sorted(executed),
        "cases": executed,
    }
    for key in ("generatedCaseIDs", "executedCaseIDs", "reportedCaseIDs"):
        if set(report[key]) != expected_ids:
            raise AssertionError(f"unknown-field report set mismatch: {key}")
    return report


def pydantic_accepts_admission(value: dict[str, Any], scenario: str) -> bool:
    model = (
        EvidenceNoAdmissionTransition
        if scenario == "no-admission"
        else EvidenceAdmissionTransition
    )
    try:
        model.model_validate(value)
    except ValueError:
        return False
    return True


def cue_accepts_admission(value: dict[str, Any], scenario: str) -> bool:
    definition = (
        "#ContextEvidenceNoAdmissionTransition"
        if scenario == "no-admission"
        else "#ContextEvidenceAdmissionTransition"
    )
    return cue_vet(definition, value).accepted


def execute_admission_matrix(matrix: EvidenceAdmissionMatrix) -> dict[str, Any]:
    validate_admission_matrix_coverage(matrix)
    executed: dict[str, Any] = {}
    for case_id, case in sorted(matrix.cases.items()):
        value = build_admission_transition(
            case.from_authority,
            case.to_authority,
            case.scenario,
        )
        cue_accepted = cue_accepts_admission(value, case.scenario)
        pydantic_accepted = pydantic_accepts_admission(value, case.scenario)
        expected = case.expected == "accept"
        if cue_accepted != expected:
            definition = (
                "#ContextEvidenceNoAdmissionTransition"
                if case.scenario == "no-admission"
                else "#ContextEvidenceAdmissionTransition"
            )
            raise AssertionError(
                f"CUE admission outcome mismatch for {case_id}: "
                f"expected={expected} diagnostics={cue_vet(definition, value).diagnostics}"
            )
        if pydantic_accepted != expected:
            raise AssertionError(f"Pydantic admission outcome mismatch for {case_id}")
        executed[case_id] = {
            "expected": case.expected,
            "cueAccepted": cue_accepted,
            "pydanticAccepted": pydantic_accepted,
        }

    expected_ids = expected_admission_case_ids()
    report = {
        "schema": "kernel.context-evidence-admission-report.v0",
        "expectedCaseIDs": sorted(expected_ids),
        "generatedCaseIDs": sorted(matrix.cases),
        "executedCaseIDs": sorted(executed),
        "reportedCaseIDs": sorted(executed),
        "cases": executed,
    }
    for key in ("generatedCaseIDs", "executedCaseIDs", "reportedCaseIDs"):
        if set(report[key]) != expected_ids:
            raise AssertionError(f"admission report set mismatch: {key}")
    return report
