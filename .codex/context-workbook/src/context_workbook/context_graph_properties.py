"""CUE-exported context graph property catalog and subprocess oracle."""

from __future__ import annotations

import copy
import json
import os
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

GraphEntityKind = Literal["module", "namespace", "member"]
ClaimAuthority = Literal["none", "candidate", "controller", "root"]
ExpectedResult = Literal["accept", "reject", "accept-or-reject"]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class ContextEntityRef(StrictModel):
    kind: GraphEntityKind
    id: str = Field(pattern=r"^[a-z0-9]+([._:/-][a-z0-9]+)*$")


class ContextSourceRef(StrictModel):
    kind: str = Field(pattern=r"^[a-z0-9]+([._:/-][a-z0-9]+)*$")
    repository: str | None = None
    revision: str | None = None
    path: str | None = None
    content_digest: str | None = Field(alias="contentDigest", default=None)
    properties: dict[str, Any] | None = None


class ContextModule(StrictModel):
    kind: Literal["repository", "workspace", "project", "application"]
    name: str = Field(min_length=1)
    root_namespace_id: str = Field(alias="rootNamespaceID")
    source: ContextSourceRef | None = None
    properties: dict[str, Any] | None = None


class ContextNamespace(StrictModel):
    module_id: str = Field(alias="moduleID")
    parent_namespace_id: str | None = Field(alias="parentNamespaceID")
    name: str = Field(min_length=1)
    kind: Literal[
        "repository-root",
        "source",
        "configuration",
        "contracts",
        "package",
        "application",
        "workflow",
        "generated",
        "evidence",
        "tests",
        "tooling",
        "language",
        "plugin",
        "controller",
    ]
    root_path: str | None = Field(alias="rootPath", default=None)
    language: str | None = None
    source: ContextSourceRef | None = None
    properties: dict[str, Any] | None = None


class ContextMember(StrictModel):
    module_id: str = Field(alias="moduleID")
    namespace_id: str = Field(alias="namespaceID")
    name: str = Field(min_length=1)
    kind: Literal[
        "file",
        "directory",
        "module",
        "package",
        "contract",
        "workflow",
        "provider",
        "entrypoint",
        "cell",
        "generated-artifact",
        "external-component",
        "documentation",
        "test",
    ]
    path: str | None = None
    source: ContextSourceRef | None = None
    properties: dict[str, Any] | None = None


class ContextRelationship(StrictModel):
    subject: ContextEntityRef
    predicate: str = Field(min_length=1)
    object: ContextEntityRef
    evidence_ids: list[str] = Field(alias="evidenceIDs")
    properties: dict[str, Any] | None = None


class ContextDiagnostic(StrictModel):
    code: str
    message: str = Field(min_length=1)


class ContextEvidence(StrictModel):
    kind: Literal["source", "observation", "diagnostic", "attestation", "validation-result"]
    subject: ContextEntityRef | None
    producer: ContextEntityRef | None
    source: ContextSourceRef
    authority: ClaimAuthority
    payload_digest: str | None = Field(alias="payloadDigest", default=None)
    diagnostics: list[ContextDiagnostic]
    properties: dict[str, Any] | None = None

    @model_validator(mode="after")
    def observation_authority_is_bounded(self) -> "ContextEvidence":
        if self.kind == "observation" and self.authority not in {"none", "candidate"}:
            raise ValueError("observation evidence cannot claim controller or root authority")
        return self


class ContextGraphProvenance(StrictModel):
    authority_digest: str = Field(alias="authorityDigest")
    schema_digest: str = Field(alias="schemaDigest")
    hydrator_digest: str = Field(alias="hydratorDigest")
    base_revision: str | None = Field(alias="baseRevision", default=None)
    base_tree: str | None = Field(alias="baseTree", default=None)
    index_digest: str | None = Field(alias="indexDigest", default=None)
    worktree_digest: str | None = Field(alias="worktreeDigest", default=None)


class ContextGraphSnapshot(StrictModel):
    schema_: Literal["kernel.context-graph.v0"] = Field(alias="schema")
    snapshot_id: str = Field(alias="snapshotID")
    modules: dict[str, ContextModule]
    namespaces: dict[str, ContextNamespace]
    members: dict[str, ContextMember]
    relationships: dict[str, ContextRelationship]
    evidence: dict[str, ContextEvidence]
    provenance: ContextGraphProvenance


class ContextGapRecord(StrictModel):
    description: str = Field(min_length=1)
    blocking: bool


class ContextConflictRecord(StrictModel):
    description: str = Field(min_length=1)
    resolved: bool


class ContextGraphSelection(StrictModel):
    schema_: Literal["kernel.context-selection.v0"] = Field(alias="schema")
    request_id: str = Field(alias="requestID")
    snapshot_id: str = Field(alias="snapshotID")
    seed_entities: list[ContextEntityRef] = Field(alias="seedEntities", min_length=1)
    selected: list[ContextEntityRef] = Field(min_length=1)
    relationship_ids: list[str] = Field(alias="relationshipIDs")
    evidence_ids: list[str] = Field(alias="evidenceIDs")
    gaps: dict[str, ContextGapRecord]
    conflicts: dict[str, ContextConflictRecord]
    sufficiency: Literal["insufficient", "provisional", "sufficient"]


class ContextGraphResolution(StrictModel):
    schema_: Literal["kernel.context-resolution.v0"] = Field(alias="schema")
    snapshot: ContextGraphSnapshot
    selection: ContextGraphSelection

    @model_validator(mode="after")
    def selection_matches_snapshot(self) -> "ContextGraphResolution":
        if self.selection.snapshot_id != self.snapshot.snapshot_id:
            raise ValueError("selection snapshotID does not match snapshot snapshotID")
        return self


class PropertyGenerator(StrictModel):
    profile: Literal["repository-context"]
    min_modules: int = Field(alias="minModules", ge=1)
    max_modules: int = Field(alias="maxModules", ge=1)
    min_members: int = Field(alias="minMembers", ge=1)
    max_members: int = Field(alias="maxMembers", ge=1)

    @model_validator(mode="after")
    def bounds_are_ordered(self) -> "PropertyGenerator":
        if self.max_modules < self.min_modules or self.max_members < self.min_members:
            raise ValueError("property generator maximum is below minimum")
        return self


class PropertyExpected(StrictModel):
    cue: ExpectedResult
    pydantic: ExpectedResult


class ContextGraphProperty(StrictModel):
    id: str
    description: str = Field(min_length=1)
    target_definition: Literal["#ContextGraphSnapshot", "#ContextGraphResolution"] = Field(
        alias="targetDefinition"
    )
    mutation: str
    generator: PropertyGenerator
    expected: PropertyExpected


class ContextGraphPropertyCatalog(StrictModel):
    schema_: Literal["kernel.context-properties.v0"] = Field(alias="schema")
    properties: dict[str, ContextGraphProperty]

    @model_validator(mode="after")
    def map_keys_match_property_ids(self) -> "ContextGraphPropertyCatalog":
        mismatches = [key for key, value in self.properties.items() if key != value.id]
        if mismatches:
            raise ValueError(f"property map key does not match id: {mismatches[0]}")
        return self


@dataclass(frozen=True)
class CueResult:
    accepted: bool
    diagnostics: str


def _repo_root() -> Path:
    configured = os.environ.get("CONTEXT_GRAPH_REPO_ROOT")
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[4]


def model_root() -> Path:
    configured = os.environ.get("CONTEXT_GRAPH_MODEL_ROOT")
    if configured:
        return Path(configured).resolve()
    return _repo_root() / ".codex" / "context-model"


def cue_binary() -> str:
    return os.environ.get("CONTEXT_GRAPH_CUE", "cue")


def _run_cue(*args: str) -> subprocess.CompletedProcess[str]:
    root = model_root()
    canonical_args = tuple("." if item == str(root) else item for item in args)
    return subprocess.run(
        [cue_binary(), *canonical_args],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
    )


@lru_cache(maxsize=1)
def load_property_catalog() -> ContextGraphPropertyCatalog:
    completed = _run_cue(
        "export",
        str(model_root()),
        "-e",
        "contextGraphPropertyCatalog",
        "--out",
        "json",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"CUE property export failed: {completed.stderr.strip()}")
    return ContextGraphPropertyCatalog.model_validate_json(completed.stdout)


def export_json_schema(definition: str) -> dict[str, Any]:
    completed = _run_cue(
        "def",
        str(model_root()),
        "-e",
        definition,
        "--out",
        "jsonschema",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"CUE JSON Schema export failed for {definition}: {completed.stderr.strip()}")
    value = json.loads(completed.stdout)
    if value.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise ValueError(f"unexpected JSON Schema dialect for {definition}")
    return value


def cue_vet(definition: str, value: dict[str, Any]) -> CueResult:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", encoding="utf-8") as payload:
        json.dump(value, payload, sort_keys=True, separators=(",", ":"))
        payload.flush()
        completed = _run_cue(
            "vet",
            "-c",
            "-d",
            definition,
            str(model_root()),
            payload.name,
        )
    return CueResult(
        accepted=completed.returncode == 0,
        diagnostics=(completed.stderr or completed.stdout).strip(),
    )


def _first_key(mapping: dict[str, Any]) -> str:
    if not mapping:
        raise ValueError("mutation requires a non-empty mapping")
    return sorted(mapping)[0]


def _unknown_module_root(value: dict[str, Any]) -> None:
    value["modules"][_first_key(value["modules"])]["rootNamespaceID"] = "namespace.missing"


def _cross_module_parent(value: dict[str, Any]) -> None:
    module_ids = sorted(value["modules"])
    if len(module_ids) < 2:
        raise ValueError("cross-module-parent requires at least two modules")
    left, right = module_ids[:2]
    left_root = value["modules"][left]["rootNamespaceID"]
    right_namespaces = [
        namespace_id
        for namespace_id, namespace in value["namespaces"].items()
        if namespace["moduleID"] == right
    ]
    if not right_namespaces:
        raise ValueError("cross-module-parent requires a namespace in the second module")
    value["namespaces"][sorted(right_namespaces)[0]]["parentNamespaceID"] = left_root


def _unknown_member_namespace(value: dict[str, Any]) -> None:
    value["members"][_first_key(value["members"])]["namespaceID"] = "namespace.missing"


def _unknown_relationship_endpoint(value: dict[str, Any]) -> None:
    relationship = value["relationships"][_first_key(value["relationships"])]
    relationship["object"]["id"] = "member.missing"
    relationship["object"]["kind"] = "member"


def _unknown_evidence_reference(value: dict[str, Any]) -> None:
    value["relationships"][_first_key(value["relationships"])]["evidenceIDs"] = [
        "evidence.missing"
    ]


def _unknown_selection_entity(value: dict[str, Any]) -> None:
    value["selection"]["selected"][0] = {"kind": "member", "id": "member.missing"}


def _selection_snapshot_mismatch(value: dict[str, Any]) -> None:
    value["selection"]["snapshotID"] = "sha256:" + "f" * 64
    if value["selection"]["snapshotID"] == value["snapshot"]["snapshotID"]:
        value["selection"]["snapshotID"] = "sha256:" + "e" * 64


def _closed_member_shape(value: dict[str, Any]) -> None:
    value["members"][_first_key(value["members"])]["unexpected"] = True


def _elevate_observation_authority(value: dict[str, Any]) -> None:
    observations = [item for item in value["evidence"].values() if item["kind"] == "observation"]
    if not observations:
        raise ValueError("authority mutation requires observation evidence")
    observations[0]["authority"] = "root"


MUTATORS: dict[str, Callable[[dict[str, Any]], None]] = {
    "unknown-module-root": _unknown_module_root,
    "cross-module-parent": _cross_module_parent,
    "unknown-member-namespace": _unknown_member_namespace,
    "unknown-relationship-endpoint": _unknown_relationship_endpoint,
    "unknown-evidence-reference": _unknown_evidence_reference,
    "unknown-selection-entity": _unknown_selection_entity,
    "selection-snapshot-mismatch": _selection_snapshot_mismatch,
    "closed-member-shape": _closed_member_shape,
    "elevate-observation-authority": _elevate_observation_authority,
}


def mutate_for_property(
    resolution: dict[str, Any], property_spec: ContextGraphProperty
) -> dict[str, Any]:
    value = copy.deepcopy(
        resolution["snapshot"]
        if property_spec.target_definition == "#ContextGraphSnapshot"
        else resolution
    )
    MUTATORS[property_spec.mutation](value)
    return value


def pydantic_accepts(definition: str, value: dict[str, Any]) -> bool:
    model: type[BaseModel]
    if definition == "#ContextGraphSnapshot":
        model = ContextGraphSnapshot
    elif definition == "#ContextGraphResolution":
        model = ContextGraphResolution
    else:
        raise ValueError(f"unsupported Pydantic definition: {definition}")
    try:
        model.model_validate(value)
    except ValueError:
        return False
    return True


def assert_expected(result: bool, expected: ExpectedResult, *, oracle: str, property_id: str) -> None:
    if expected == "accept" and not result:
        raise AssertionError(f"{oracle} rejected property {property_id}, expected acceptance")
    if expected == "reject" and result:
        raise AssertionError(f"{oracle} accepted property {property_id}, expected rejection")


def validate_property_coverage(catalog: ContextGraphPropertyCatalog) -> None:
    declared_mutations = {spec.mutation for spec in catalog.properties.values()}
    implemented_mutations = set(MUTATORS)
    if declared_mutations != implemented_mutations:
        missing = sorted(declared_mutations - implemented_mutations)
        orphaned = sorted(implemented_mutations - declared_mutations)
        raise AssertionError(f"property mutation coverage mismatch: missing={missing}, orphaned={orphaned}")
