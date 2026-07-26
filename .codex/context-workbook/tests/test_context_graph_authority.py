from __future__ import annotations

from hypothesis import HealthCheck, given, settings, strategies as st

from context_workbook.context_graph_authority import (
    AUTHORITY_LEVELS,
    COLLECTED_EVIDENCE_KINDS,
    EVIDENCE_KINDS,
    AuthorityBoundContextEvidence,
    build_kind_only_transition,
    execute_authority_matrix,
    load_evidence_authority_matrix,
    pydantic_accepts_transition,
)
from context_workbook.context_graph_properties import cue_vet

MATRIX = load_evidence_authority_matrix()


def test_authority_matrix_is_complete_and_executable() -> None:
    report = execute_authority_matrix(MATRIX)
    expected = {
        f"authority.{kind}.{authority}"
        for kind in EVIDENCE_KINDS
        for authority in AUTHORITY_LEVELS
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
@given(
    before_kind=st.sampled_from(COLLECTED_EVIDENCE_KINDS),
    before_authority=st.sampled_from(["none", "candidate"]),
    elevated_authority=st.sampled_from(["controller", "root"]),
)
def test_kind_only_reclassification_cannot_widen_authority(
    before_kind: str,
    before_authority: str,
    elevated_authority: str,
) -> None:
    preserved = build_kind_only_transition(
        before_kind,
        "source",
        before_authority,
        before_authority,
    )
    assert cue_vet("#ContextEvidenceKindOnlyTransition", preserved).accepted
    assert pydantic_accepts_transition(preserved)

    escalated = build_kind_only_transition(
        before_kind,
        "source",
        before_authority,
        elevated_authority,
    )

    # The reclassified source evidence is individually admissible. The
    # no-admission transition is what must reject the authority increase.
    AuthorityBoundContextEvidence.model_validate(escalated["after"])
    assert cue_vet("#ContextEvidence", escalated["after"]).accepted
    assert not cue_vet("#ContextEvidenceKindOnlyTransition", escalated).accepted
    assert not pydantic_accepts_transition(escalated)
