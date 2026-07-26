from __future__ import annotations

import copy

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from context_workbook.context_graph_admission import (
    ADMISSION_SCENARIOS,
    AUTHORITY_LEVELS,
    CollectedEvidenceEnvelope,
    EvidenceAdmissionBundle,
    EvidenceAdmissionTransition,
    EvidenceAuthorityProjection,
    EvidenceNoAdmissionTransition,
    build_admission_bundle,
    build_admission_transition,
    build_authority_projection,
    build_authority_state,
    build_collected_envelope,
    cue_accepts_admission,
    execute_admission_matrix,
    execute_transport_unknown_field_cases,
    load_evidence_admission_matrix,
    pydantic_accepts_transport,
    unknown_field_transport_cases,
)
from context_workbook.context_graph_properties import cue_vet

MATRIX = load_evidence_admission_matrix()


def assert_pydantic_rejects(model: type, value: dict) -> None:
    with pytest.raises(ValueError):
        model.model_validate(value)


def test_admission_matrix_is_complete_and_executable() -> None:
    report = execute_admission_matrix(MATRIX)
    expected = {
        f"admission.{from_authority}.{to_authority}.{scenario}"
        for from_authority in AUTHORITY_LEVELS
        for to_authority in AUTHORITY_LEVELS
        for scenario in ADMISSION_SCENARIOS
    }
    assert set(report["expectedCaseIDs"]) == expected
    assert set(report["generatedCaseIDs"]) == expected
    assert set(report["executedCaseIDs"]) == expected
    assert set(report["reportedCaseIDs"]) == expected


@settings(
    max_examples=16,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(authority=st.sampled_from(AUTHORITY_LEVELS))
def test_no_admission_and_replay_are_deterministic(authority: str) -> None:
    preserved = build_admission_transition(authority, authority, "no-admission")
    assert cue_accepts_admission(preserved, "no-admission")
    EvidenceNoAdmissionTransition.model_validate(preserved)

    replay = build_admission_transition(authority, authority, "valid-admission")
    assert cue_accepts_admission(replay, "valid-admission")
    EvidenceAdmissionTransition.model_validate(replay)


@settings(
    max_examples=12,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.too_slow],
)
@given(
    scenario=st.sampled_from(
        [
            "wrong-evidence-id",
            "wrong-evidence-digest",
            "wrong-snapshot",
            "wrong-policy-digest",
        ]
    )
)
def test_admission_is_bound_to_exact_evidence_and_provenance(scenario: str) -> None:
    value = build_admission_transition("candidate", "controller", scenario)
    assert not cue_accepts_admission(value, scenario)
    assert_pydantic_rejects(EvidenceAdmissionTransition, value)


def test_elevated_bundle_state_requires_exactly_one_matching_admission() -> None:
    valid = build_admission_bundle()
    assert cue_vet("#ContextEvidenceAdmissionBundle", valid).accepted
    EvidenceAdmissionBundle.model_validate(valid)

    no_admission = copy.deepcopy(valid)
    no_admission["admissions"] = {}
    assert not cue_vet("#ContextEvidenceAdmissionBundle", no_admission).accepted
    assert_pydantic_rejects(EvidenceAdmissionBundle, no_admission)

    duplicate = copy.deepcopy(valid)
    second = copy.deepcopy(next(iter(duplicate["admissions"].values())))
    second["admission"]["admissionID"] = "admission.context-evidence-duplicate"
    second["admission"]["decisionDigest"] = "sha256:" + "9" * 64
    duplicate["admissions"]["admission.context-evidence-duplicate"] = second
    assert not cue_vet("#ContextEvidenceAdmissionBundle", duplicate).accepted
    assert_pydantic_rejects(EvidenceAdmissionBundle, duplicate)


def test_bundle_state_must_equal_transition_after_state() -> None:
    mismatched = build_admission_bundle()
    state = mismatched["states"]["evidence.context-admission"]
    state["effectiveAuthority"] = "root"
    state["snapshotID"] = "sha256:" + "8" * 64

    assert not cue_vet("#ContextEvidenceAdmissionBundle", mismatched).accepted
    assert_pydantic_rejects(EvidenceAdmissionBundle, mismatched)


def test_collection_boundary_rejects_elevated_source_evidence() -> None:
    candidate_source = build_collected_envelope(
        evidence_authority="candidate",
        evidence_kind="source",
    )
    assert cue_vet("#ContextCollectedEvidenceEnvelope", candidate_source).accepted
    CollectedEvidenceEnvelope.model_validate(candidate_source)

    elevated_source = build_collected_envelope(
        evidence_authority="root",
        evidence_kind="source",
    )
    assert not cue_vet("#ContextCollectedEvidenceEnvelope", elevated_source).accepted
    assert_pydantic_rejects(CollectedEvidenceEnvelope, elevated_source)


def test_collection_and_projection_cannot_widen_authority() -> None:
    collection = build_collected_envelope()
    assert cue_vet("#ContextCollectedEvidenceEnvelope", collection).accepted
    CollectedEvidenceEnvelope.model_validate(collection)

    widened = copy.deepcopy(collection)
    widened["state"]["effectiveAuthority"] = "controller"
    assert not cue_vet("#ContextCollectedEvidenceEnvelope", widened).accepted
    assert_pydantic_rejects(CollectedEvidenceEnvelope, widened)

    projection = build_authority_projection()
    assert cue_vet("#ContextEvidenceAuthorityProjection", projection).accepted
    EvidenceAuthorityProjection.model_validate(projection)
    projection["projected"]["effectiveAuthority"] = "root"
    assert not cue_vet("#ContextEvidenceAuthorityProjection", projection).accepted
    assert_pydantic_rejects(EvidenceAuthorityProjection, projection)


def test_unrelated_valid_evidence_extension_preserves_admission() -> None:
    bundle = build_admission_bundle()
    assert cue_vet("#ContextEvidenceAdmissionBundle", bundle).accepted
    EvidenceAdmissionBundle.model_validate(bundle)

    extended = copy.deepcopy(bundle)
    unrelated = build_authority_state(
        "none",
        evidence_authority="none",
        evidence_id="evidence.unrelated",
    )
    unrelated["evidence"]["payloadDigest"] = "sha256:" + "8" * 64
    extended["states"]["evidence.unrelated"] = unrelated
    assert cue_vet("#ContextEvidenceAdmissionBundle", extended).accepted
    EvidenceAdmissionBundle.model_validate(extended)


@pytest.mark.parametrize(
    ("case_id", "definition", "value"),
    [
        (case_id, definition, value)
        for case_id, (definition, value) in sorted(
            unknown_field_transport_cases().items()
        )
    ],
)
def test_every_transport_rejects_unknown_fields(
    case_id: str,
    definition: str,
    value: dict,
) -> None:
    assert not cue_vet(definition, value).accepted, case_id
    assert not pydantic_accepts_transport(definition, value), case_id


def test_unknown_field_case_report_has_exact_coverage() -> None:
    report = execute_transport_unknown_field_cases()
    expected = set(unknown_field_transport_cases())
    assert set(report["expectedCaseIDs"]) == expected
    assert set(report["generatedCaseIDs"]) == expected
    assert set(report["executedCaseIDs"]) == expected
    assert set(report["reportedCaseIDs"]) == expected
