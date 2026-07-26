"""Strict transport and state models projected from the provisional CUE root."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

_ID = re.compile(r"^[a-z0-9]+([._-][a-z0-9]+)*$")
_GRAPH_ID = re.compile(r"^[a-z0-9]+([._:/-][a-z0-9]+)*$")
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")
_CLAIMANT_FIELDS = frozenset(
    {
        "pass",
        "passed",
        "success",
        "valid",
        "complete",
        "admitted",
        "aligned",
        "sufficient",
    }
)


def canonical_json(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest_value(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json(value)).hexdigest()}"


def reject_claimant_fields(value: object, label: str = "payload") -> None:
    if isinstance(value, dict):
        forbidden = sorted(_CLAIMANT_FIELDS.intersection(value))
        if forbidden:
            raise ValueError(f"claimant field in {label}: {forbidden[0]}")
        for child in value.values():
            reject_claimant_fields(child, label)
    elif isinstance(value, list):
        for child in value:
            reject_claimant_fields(child, label)


def validate_id(value: str) -> str:
    if not _ID.fullmatch(value):
        raise ValueError(f"invalid ID: {value!r}")
    return value


def validate_graph_id(value: str) -> str:
    if not _GRAPH_ID.fullmatch(value):
        raise ValueError(f"invalid graph ID: {value!r}")
    return value


def validate_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or value.startswith("/") or ".." in path.parts:
        raise ValueError(f"path escapes repository: {value!r}")
    return value


def path_is_allowed(path: str, allowed_paths: list[str]) -> bool:
    candidate = PurePosixPath(path)
    for allowed in allowed_paths:
        if allowed == ".":
            return True
        root = PurePosixPath(allowed)
        if candidate == root or root in candidate.parents:
            return True
    return False


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class AuthorityBinding(StrictModel):
    semantic_role: Literal["authority", "constraint", "workflow", "evidence"] = Field(
        alias="semanticRole"
    )
    artifact_class: Literal["source", "generated_projection", "runtime_observation"] = Field(
        alias="artifactClass"
    )
    claim_authority: Literal["none", "candidate", "controller", "root"] = Field(
        alias="claimAuthority"
    )
    source_ref: dict[str, Any] | None = Field(alias="sourceRef", default=None)

    @model_validator(mode="after")
    def restrict_claims(self) -> "AuthorityBinding":
        if self.artifact_class != "source" and self.claim_authority not in {"none", "candidate"}:
            raise ValueError("non-source artifacts cannot claim controller or root authority")
        if self.semantic_role == "evidence" and self.claim_authority not in {"none", "candidate"}:
            raise ValueError("evidence cannot claim controller or root authority")
        return self


class RepositoryCoordinate(StrictModel):
    repository: str = Field(min_length=1)
    root: str = "."
    revision: str = Field(min_length=1)
    module_root: str | None = Field(alias="moduleRoot", default=None)

    @model_validator(mode="after")
    def validate_paths(self) -> "RepositoryCoordinate":
        if self.root != ".":
            validate_path(self.root)
        if self.module_root not in {None, "."}:
            validate_path(self.module_root)
        return self


class ContextRequest(StrictModel):
    schema_: Literal["dotfiles.context-request.v0"] = Field(alias="schema")
    request_id: str = Field(alias="requestID")
    prompt: str = Field(min_length=1)
    repository: RepositoryCoordinate
    allowed_paths: list[str] = Field(alias="allowedPaths")
    requested_projection_ids: list[str] = Field(alias="requestedProjectionIDs")

    @model_validator(mode="after")
    def validate_request(self) -> "ContextRequest":
        validate_id(self.request_id)
        for path in self.allowed_paths:
            validate_path(path)
        for projection_id in self.requested_projection_ids:
            validate_id(projection_id)
        return self


class ExplicitContextRoots(StrictModel):
    member_ids: list[str] = Field(alias="memberIDs", default_factory=list)
    namespace_ids: list[str] = Field(alias="namespaceIDs", default_factory=list)
    path_prefixes: list[str] = Field(alias="pathPrefixes", default_factory=list)

    @model_validator(mode="after")
    def canonical_roots(self) -> "ExplicitContextRoots":
        for values in (self.member_ids, self.namespace_ids, self.path_prefixes):
            if values != sorted(values) or len(values) != len(set(values)):
                raise ValueError("explicit roots must be sorted and unique")
        for identifier in (*self.member_ids, *self.namespace_ids):
            validate_graph_id(identifier)
        for path in self.path_prefixes:
            validate_path(path)
        if len(self.member_ids) + len(self.namespace_ids) + len(self.path_prefixes) > 64:
            raise ValueError("explicit roots exceed the 64-root limit")
        return self


class ContextApplicationRequest(StrictModel):
    schema_: Literal["dotfiles.context-application-request.v0"] = Field(alias="schema")
    request_id: str = Field(alias="requestID")
    repository: str = Field(min_length=1)
    revision: str = Field(min_length=1)
    allowed_paths: list[str] = Field(alias="allowedPaths", min_length=1)
    overlay_mode: Literal["disabled", "required", "auto"] = Field(alias="overlayMode")
    roots: ExplicitContextRoots

    @model_validator(mode="after")
    def closed_request(self) -> "ContextApplicationRequest":
        validate_id(self.request_id)
        for path in self.allowed_paths:
            validate_path(path)
        if self.allowed_paths != sorted(self.allowed_paths):
            raise ValueError("allowedPaths must be sorted")
        return self


class ContextRootProposal(StrictModel):
    schema_: Literal["dotfiles.context-root-proposal.v0"] = Field(alias="schema")
    request_id: str = Field(alias="requestID")
    snapshot_id: str = Field(alias="snapshotID", pattern=_DIGEST.pattern)
    member_ids: list[str] = Field(alias="memberIDs", default_factory=list)
    namespace_ids: list[str] = Field(alias="namespaceIDs", default_factory=list)
    path_prefixes: list[str] = Field(alias="pathPrefixes", default_factory=list)

    @model_validator(mode="after")
    def canonical_proposal(self) -> "ContextRootProposal":
        ExplicitContextRoots.model_validate(
            {
                "memberIDs": self.member_ids,
                "namespaceIDs": self.namespace_ids,
                "pathPrefixes": self.path_prefixes,
            }
        )
        validate_id(self.request_id)
        return self


class ContextGraphFailure(StrictModel):
    schema_: Literal["dotfiles.context-graph-failure.v0"] = Field(alias="schema")
    request_id: str = Field(alias="requestID")
    stage: Literal[
        "revision", "manifest", "hydration", "snapshot", "proposal", "selection", "packet"
    ]
    code: str
    message: str = Field(min_length=1)
    details: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def identifiers(self) -> "ContextGraphFailure":
        validate_id(self.request_id)
        validate_id(self.code)
        return self


class ContextRootCatalog(StrictModel):
    schema_: Literal["dotfiles.context-root-catalog.v0"] = Field(alias="schema")
    request_id: str = Field(alias="requestID")
    snapshot_id: str = Field(alias="snapshotID", pattern=_DIGEST.pattern)
    member_ids: list[str] = Field(alias="memberIDs", max_length=2048)
    namespace_ids: list[str] = Field(alias="namespaceIDs", max_length=256)
    paths: list[str] = Field(max_length=2048)

    @model_validator(mode="after")
    def bounded_catalog(self) -> "ContextRootCatalog":
        validate_id(self.request_id)
        for values in (self.member_ids, self.namespace_ids, self.paths):
            if values != sorted(values) or len(values) != len(set(values)):
                raise ValueError("catalog lists must be sorted and unique")
        for identifier in (*self.member_ids, *self.namespace_ids):
            validate_graph_id(identifier)
        for path in self.paths:
            validate_path(path)
        if len(canonical_json(self.model_dump(by_alias=True))) > 262_144:
            raise ValueError("catalog exceeds canonical byte limit")
        return self


class SourceObservation(StrictModel):
    kind: Literal["prompt", "repository", "git", "file", "provider", "tool"]
    subject: str = Field(min_length=1)
    facts: dict[str, Any]
    diagnostics: list[dict[str, str]] = Field(default_factory=list)
    provenance: AuthorityBinding

    @model_validator(mode="before")
    @classmethod
    def no_claimant_facts(cls, value: object) -> object:
        if isinstance(value, dict):
            reject_claimant_fields(value.get("facts", {}), "observation facts")
        return value


class Evidence(StrictModel):
    summary: str = Field(min_length=1)
    observation_ids: list[str] = Field(alias="observationIDs", min_length=1, max_length=1)
    provenance: AuthorityBinding


class ContextHypothesis(StrictModel):
    kind: str = Field(pattern=_ID.pattern)
    statement: str = Field(min_length=1)
    state: Literal["candidate", "accepted", "rejected", "superseded"]
    evidence_ids: list[str] = Field(alias="evidenceIDs", min_length=1, max_length=1)
    confidence: float = Field(ge=0, le=1)
    derived_by: str = Field(alias="derivedBy", pattern=_ID.pattern)


class ContextFragment(StrictModel):
    summary: str
    source_ref: dict[str, Any] = Field(alias="sourceRef")
    prerequisites: list[str] = Field(default_factory=list)
    authority: AuthorityBinding


class Provider(StrictModel):
    kind: Literal["lsp", "mcp", "types", "tool", "repository"]
    languages: list[str] = Field(default_factory=list)
    path_globs: list[str] = Field(alias="pathGlobs", default_factory=list)
    evidence_only: Literal[True] = Field(alias="evidenceOnly")
    authority: AuthorityBinding


class Workflow(StrictModel):
    summary: str
    steps: list[dict[str, Any]]
    authority: AuthorityBinding


class ContextInventory(StrictModel):
    fragments: dict[str, ContextFragment]
    providers: dict[str, Provider]
    workflows: dict[str, Workflow]


class SelectionReason(StrictModel):
    reason: str = Field(min_length=1)
    evidence_ids: list[str] = Field(alias="evidenceIDs", min_length=1, max_length=1)


class FragmentSelection(SelectionReason):
    fragment_id: str = Field(alias="fragmentID")


class FileSelection(SelectionReason):
    path: str


class ProviderSelection(SelectionReason):
    provider_id: str = Field(alias="providerID")


class WorkflowSelection(SelectionReason):
    workflow_id: str = Field(alias="workflowID")


class Selections(StrictModel):
    fragments: list[FragmentSelection] = Field(default_factory=list)
    files: list[FileSelection] = Field(default_factory=list)
    providers: list[ProviderSelection] = Field(default_factory=list)
    workflows: list[WorkflowSelection] = Field(default_factory=list)


class ContextGap(StrictModel):
    kind: str
    description: str
    blocks_sufficiency: bool = Field(alias="blocksSufficiency")
    required_evidence_ids: list[str] = Field(alias="requiredEvidenceIDs", default_factory=list)


class ContextConflict(StrictModel):
    left_ref: str = Field(alias="leftRef")
    right_ref: str = Field(alias="rightRef")
    description: str
    evidence_ids: list[str] = Field(alias="evidenceIDs", min_length=1, max_length=1)
    resolution: Literal["unresolved", "prefer_left", "prefer_right", "superseded", "merged"]


class ContextSufficiency(StrictModel):
    state: Literal["insufficient", "provisional", "sufficient"]
    reasons: list[str] = Field(min_length=1)
    blocking_gap_ids: list[str] = Field(alias="blockingGapIDs")
    unresolved_conflict_ids: list[str] = Field(alias="unresolvedConflictIDs")


class PacketSelections(StrictModel):
    fragment_ids: list[str] = Field(alias="fragmentIDs")
    files: list[str]
    provider_ids: list[str] = Field(alias="providerIDs")
    workflow_ids: list[str] = Field(alias="workflowIDs")


class ContextPacket(StrictModel):
    schema_: Literal["dotfiles.context-packet.v0"] = Field(alias="schema")
    request_id: str = Field(alias="requestID")
    context_digest: str = Field(alias="contextDigest")
    selected: PacketSelections
    evidence_ids: list[str] = Field(alias="evidenceIDs")
    unresolved_gap_ids: list[str] = Field(alias="unresolvedGapIDs")
    provenance: AuthorityBinding

    @model_validator(mode="after")
    def valid_digest(self) -> "ContextPacket":
        if not _DIGEST.fullmatch(self.context_digest):
            raise ValueError("invalid context digest")
        return self


class ContextState(StrictModel):
    schema_: Literal["dotfiles.context-state.v0"] = Field(alias="schema")
    request: ContextRequest
    inventory: ContextInventory
    observations: dict[str, SourceObservation]
    provider_observations: list[dict[str, Any]] = Field(
        alias="providerObservations", default_factory=list
    )
    evidence: dict[str, Evidence]
    hypotheses: dict[str, ContextHypothesis]
    selected: Selections
    gaps: dict[str, ContextGap]
    conflicts: dict[str, ContextConflict]
    sufficiency: ContextSufficiency
    projection: ContextPacket | None = None

    @model_validator(mode="after")
    def enforce_integrity(self) -> "ContextState":
        evidence_ids = set(self.evidence)
        observation_ids = set(self.observations)
        for item in self.evidence.values():
            unknown = set(item.observation_ids) - observation_ids
            if unknown:
                raise ValueError(f"unknown observation IDs: {sorted(unknown)}")
        for item in self.hypotheses.values():
            unknown = set(item.evidence_ids) - evidence_ids
            if unknown:
                raise ValueError(f"unknown hypothesis evidence IDs: {sorted(unknown)}")
        for collection in (
            self.selected.fragments,
            self.selected.files,
            self.selected.providers,
            self.selected.workflows,
        ):
            for item in collection:
                unknown = set(item.evidence_ids) - evidence_ids
                if unknown:
                    raise ValueError(f"unknown selection evidence IDs: {sorted(unknown)}")
        fragment_ids = {item.fragment_id for item in self.selected.fragments}
        provider_ids = {item.provider_id for item in self.selected.providers}
        workflow_ids = {item.workflow_id for item in self.selected.workflows}
        file_paths = {item.path for item in self.selected.files}
        if not fragment_ids <= set(self.inventory.fragments):
            raise ValueError("selection references unknown fragment")
        if not provider_ids <= set(self.inventory.providers):
            raise ValueError("selection references unknown provider")
        if not workflow_ids <= set(self.inventory.workflows):
            raise ValueError("selection references unknown workflow")
        for path in file_paths:
            validate_path(path)
            if not path_is_allowed(path, self.request.allowed_paths):
                raise ValueError(f"selected file outside request boundary: {path}")
        blocking = sorted(key for key, gap in self.gaps.items() if gap.blocks_sufficiency)
        unresolved = sorted(
            key for key, conflict in self.conflicts.items() if conflict.resolution == "unresolved"
        )
        if self.sufficiency.blocking_gap_ids != blocking:
            raise ValueError("blockingGapIDs must be derived from the complete gap map")
        if self.sufficiency.unresolved_conflict_ids != unresolved:
            raise ValueError("unresolvedConflictIDs must be derived from the complete conflict map")
        if self.sufficiency.state == "sufficient" and (blocking or unresolved):
            raise ValueError("sufficient context cannot contain blockers")
        if self.projection is not None:
            if self.projection.request_id != self.request.request_id:
                raise ValueError("projection requestID mismatch")
            projected = self.projection.selected
            if not set(projected.fragment_ids) <= fragment_ids:
                raise ValueError("projection contains unselected fragment")
            if not set(projected.provider_ids) <= provider_ids:
                raise ValueError("projection contains unselected provider")
            if not set(projected.workflow_ids) <= workflow_ids:
                raise ValueError("projection contains unselected workflow")
            if not set(projected.files) <= file_paths:
                raise ValueError("projection contains unselected file")
            if not set(self.projection.evidence_ids) <= evidence_ids:
                raise ValueError("projection contains unknown evidence")
            if not set(self.projection.unresolved_gap_ids) <= set(self.gaps):
                raise ValueError("projection contains unknown gap")
        return self


class DecisionSelection(StrictModel):
    ids: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)
    evidence_ids: list[str] = Field(alias="evidenceIDs", min_length=1, max_length=1)


class ContextDecision(StrictModel):
    """Typed DSPy output. It contains inferences, never source observations."""

    hypotheses: dict[str, ContextHypothesis]
    fragments: DecisionSelection
    files: DecisionSelection
    providers: DecisionSelection
    workflows: DecisionSelection
    gaps: dict[str, ContextGap] = Field(default_factory=dict)
    conflicts: dict[str, ContextConflict] = Field(default_factory=dict)
    sufficiency_state: Literal["insufficient", "provisional", "sufficient"] = Field(
        alias="sufficiencyState"
    )
    sufficiency_reasons: list[str] = Field(alias="sufficiencyReasons", min_length=1)

    @model_validator(mode="after")
    def canonicalize_maps(self) -> "ContextDecision":
        self.hypotheses = dict(sorted(self.hypotheses.items()))
        self.gaps = dict(sorted(self.gaps.items()))
        self.conflicts = dict(sorted(self.conflicts.items()))
        return self
