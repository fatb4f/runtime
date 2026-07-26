"""Pure context-establishment stages shared by Marimo and browserless execution."""

from __future__ import annotations

import json
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .dspy_program import ContextReasoner, DspyUnavailable
from .ingest import (
    load_code_intel,
    load_inventory,
    materialize_inputs,
    path_glob_intersects_allowed,
)
from .models import (
    ContextDecision,
    ContextInventory,
    ContextPacket,
    ContextRequest,
    ContextState,
    ContextSufficiency,
    Evidence,
    FileSelection,
    FragmentSelection,
    ProviderSelection,
    Selections,
    SourceObservation,
    WorkflowSelection,
    digest_value,
    path_is_allowed,
    validate_path,
)
from .repository import RepositorySnapshot


class EngineError(RuntimeError):
    pass


@dataclass(frozen=True)
class WorkbookConfig:
    allowed_paths: list[str]
    code_intel_files: list[str]
    projection_ids: list[str]
    max_selected_files: int
    max_packet_bytes: int


@dataclass(frozen=True)
class EngineResult:
    state: ContextState
    trace: dict[str, str]
    hook_projection: dict[str, Any] | None
    code_intel_projection: dict[str, Any] | None


def _run_json(command: list[str], *, cwd: Path, stdin: bytes | None = None) -> object:
    process = subprocess.run(
        command,
        cwd=cwd,
        input=stdin,
        capture_output=True,
        check=False,
        timeout=30,
    )
    if process.returncode != 0:
        raise EngineError(process.stderr.decode(errors="replace").strip() or "command failed")
    return json.loads(process.stdout)


def _load_workbook_config(model_root: Path, cue_binary: str = "cue") -> WorkbookConfig:
    value = _run_json(
        [cue_binary, "export", ".", "-e", "workbookConfig", "--out", "json"],
        cwd=model_root,
    )
    if not isinstance(value, dict):
        raise EngineError("workbookConfig must be an object")
    projections = _run_json(
        [cue_binary, "export", ".", "-e", "rootSeed.projections", "--out", "json"],
        cwd=model_root,
    )
    if not isinstance(projections, dict):
        raise EngineError("rootSeed.projections must be an object")
    return WorkbookConfig(
        allowed_paths=[str(item) for item in value["allowedPaths"]],
        code_intel_files=[str(item) for item in value["codeIntelFiles"]],
        projection_ids=sorted(str(item) for item in projections),
        max_selected_files=int(value["limits"]["maxSelectedFiles"]),
        max_packet_bytes=int(value["limits"]["maxPacketBytes"]),
    )


def load_workbook_config(
    root: Path,
    cue_binary: str = "cue",
    *,
    revision: str = "HEAD",
) -> tuple[WorkbookConfig, RepositorySnapshot]:
    snapshot = RepositorySnapshot.resolve(root, revision)
    with tempfile.TemporaryDirectory(prefix="context-workbook-cue-") as temporary:
        model_root = snapshot.materialize_cue_package(
            ".codex/context-model", Path(temporary)
        )
        return _load_workbook_config(model_root, cue_binary), snapshot


def build_request(
    *,
    prompt: str,
    config: WorkbookConfig,
    snapshot: RepositorySnapshot,
    requested_projection_ids: list[str] | None = None,
) -> ContextRequest:
    revision = snapshot.resolved_revision
    request_id = f"request-{digest_value({'prompt': prompt, 'revision': revision})[7:23]}"
    return ContextRequest.model_validate(
        {
            "schema": "dotfiles.context-request.v0",
            "requestID": request_id,
            "prompt": prompt,
            "repository": {
                "repository": "fatb4f/dotfiles",
                "root": ".",
                "revision": revision,
            },
            "allowedPaths": config.allowed_paths,
            "requestedProjectionIDs": requested_projection_ids or ["agent-context-resolver"],
        }
    )


def _validate_request_against_config(request: ContextRequest, config: WorkbookConfig) -> None:
    if request.repository.repository != "fatb4f/dotfiles" or request.repository.root != ".":
        raise EngineError("request repository coordinate does not match the workbook repository")
    if not request.allowed_paths:
        raise EngineError("request must retain at least one configured path boundary")
    widened_paths = [
        path for path in request.allowed_paths if not path_is_allowed(path, config.allowed_paths)
    ]
    if widened_paths:
        raise EngineError(f"request widens configured path boundary: {sorted(widened_paths)}")
    if not request.requested_projection_ids:
        raise EngineError("request must select at least one configured projection")
    unknown_projections = set(request.requested_projection_ids) - set(config.projection_ids)
    if unknown_projections:
        raise EngineError(
            f"request selects unknown projections: {sorted(unknown_projections)}"
        )


def _scope_inventory(
    inventory: ContextInventory,
    allowed_paths: list[str],
    code_intel: dict[str, Any],
) -> ContextInventory:
    fragment_ids = {
        fragment_id
        for fragment_id, fragment in inventory.fragments.items()
        if isinstance(fragment.source_ref.get("path"), str)
        and path_is_allowed(fragment.source_ref["path"], allowed_paths)
    }
    pending = list(fragment_ids)
    while pending:
        fragment_id = pending.pop()
        for prerequisite_id in inventory.fragments[fragment_id].prerequisites:
            if prerequisite_id not in inventory.fragments:
                raise EngineError(
                    f"fragment prerequisite is absent from inventory: {prerequisite_id}"
                )
            if prerequisite_id not in fragment_ids:
                fragment_ids.add(prerequisite_id)
                pending.append(prerequisite_id)
    fragments = {
        fragment_id: inventory.fragments[fragment_id].model_dump(by_alias=True)
        for fragment_id in sorted(fragment_ids)
    }

    providers: dict[str, Any] = {}
    if code_intel:
        for provider_id, provider in inventory.providers.items():
            value = provider.model_dump(by_alias=True)
            value["pathGlobs"] = [
                pattern
                for pattern in value["pathGlobs"]
                if path_glob_intersects_allowed(pattern, allowed_paths)
            ]
            if value["pathGlobs"]:
                providers[provider_id] = value

    has_workflow_entries = any(
        isinstance(document, dict) and bool(document.get("entrypoints"))
        for document in code_intel.values()
    )
    workflows = {
        workflow_id: workflow.model_dump(by_alias=True)
        for workflow_id, workflow in inventory.workflows.items()
        if workflow.authority.artifact_class == "source" or has_workflow_entries
    }
    return ContextInventory.model_validate(
        {"fragments": fragments, "providers": providers, "workflows": workflows}
    )


def _declared_paths(
    snapshot: RepositorySnapshot,
    inventory: ContextInventory,
    code_intel: dict[str, Any],
    allowed_paths: list[str],
) -> list[str]:
    paths: set[str] = set()
    for fragment in inventory.fragments.values():
        source = fragment.source_ref.get("path")
        if isinstance(source, str):
            paths.add(source)
    workflow = next(
        (
            document
            for document in code_intel.values()
            if isinstance(document, dict) and isinstance(document.get("entrypoints"), list)
        ),
        {},
    )
    if isinstance(workflow, dict):
        for entrypoint in workflow.get("entrypoints", []):
            path = entrypoint.get("path")
            if isinstance(path, str):
                paths.add(path)
    return sorted(
        path
        for path in paths
        if path_is_allowed(path, allowed_paths) and snapshot.is_file(path)
    )


def _selection_items(decision: ContextDecision) -> Selections:
    return Selections(
        fragments=[
            FragmentSelection(
                fragmentID=item,
                reason=decision.fragments.reason,
                evidenceIDs=decision.fragments.evidence_ids,
            )
            for item in decision.fragments.ids
        ],
        files=[
            FileSelection(
                path=item,
                reason=decision.files.reason,
                evidenceIDs=decision.files.evidence_ids,
            )
            for item in decision.files.ids
        ],
        providers=[
            ProviderSelection(
                providerID=item,
                reason=decision.providers.reason,
                evidenceIDs=decision.providers.evidence_ids,
            )
            for item in decision.providers.ids
        ],
        workflows=[
            WorkflowSelection(
                workflowID=item,
                reason=decision.workflows.reason,
                evidenceIDs=decision.workflows.evidence_ids,
            )
            for item in decision.workflows.ids
        ],
    )


def _validate_decision(
    *,
    snapshot: RepositorySnapshot,
    request: ContextRequest,
    inventory: Any,
    decision: ContextDecision,
    max_selected_files: int,
) -> None:
    unknown_fragments = set(decision.fragments.ids) - set(inventory.fragments)
    unknown_providers = set(decision.providers.ids) - set(inventory.providers)
    unknown_workflows = set(decision.workflows.ids) - set(inventory.workflows)
    if unknown_fragments:
        raise EngineError(f"DSPy selected unknown fragments: {sorted(unknown_fragments)}")
    if unknown_providers:
        raise EngineError(f"DSPy selected unknown providers: {sorted(unknown_providers)}")
    if unknown_workflows:
        raise EngineError(f"DSPy selected unknown workflows: {sorted(unknown_workflows)}")
    selected_fragments = set(decision.fragments.ids)
    missing_prerequisites = {
        fragment_id: sorted(
            set(inventory.fragments[fragment_id].prerequisites) - selected_fragments
        )
        for fragment_id in selected_fragments
        if set(inventory.fragments[fragment_id].prerequisites) - selected_fragments
    }
    if missing_prerequisites:
        raise EngineError(
            "DSPy selected fragments without prerequisites: "
            f"{missing_prerequisites}"
        )
    if len(decision.files.ids) > max_selected_files:
        raise EngineError("DSPy selected too many files")
    for relative in decision.files.ids:
        validate_path(relative)
        if not path_is_allowed(relative, request.allowed_paths):
            raise EngineError(f"DSPy selected file outside request boundary: {relative}")
        if not snapshot.is_file(relative):
            raise EngineError(f"DSPy selected non-file path: {relative}")


def _derive_sufficiency(decision: ContextDecision) -> ContextSufficiency:
    blocking = sorted(key for key, gap in decision.gaps.items() if gap.blocks_sufficiency)
    unresolved = sorted(
        key for key, conflict in decision.conflicts.items() if conflict.resolution == "unresolved"
    )
    state = decision.sufficiency_state
    reasons = list(decision.sufficiency_reasons)
    if blocking or unresolved:
        state = "insufficient"
        reasons.append("Complete gap and conflict maps contain unresolved blockers.")
    return ContextSufficiency(
        state=state,
        reasons=list(dict.fromkeys(reasons)),
        blockingGapIDs=blocking,
        unresolvedConflictIDs=unresolved,
    )


def _make_packet(
    *,
    request: ContextRequest,
    inventory: Any,
    observations: dict[str, SourceObservation],
    evidence: dict[str, Evidence],
    decision: ContextDecision,
    selected: Selections,
    sufficiency: ContextSufficiency,
) -> ContextPacket | None:
    if sufficiency.state != "sufficient":
        return None
    subject = {
        "request": request.model_dump(by_alias=True),
        "inventoryDigest": digest_value(inventory.model_dump(by_alias=True)),
        "observationDigest": digest_value(
            {key: value.model_dump(by_alias=True) for key, value in observations.items()}
        ),
        "evidenceDigest": digest_value(
            {key: value.model_dump(by_alias=True) for key, value in evidence.items()}
        ),
        "decision": decision.model_dump(by_alias=True),
    }
    referenced_evidence = sorted(
        {
            evidence_id
            for group in (
                decision.fragments,
                decision.files,
                decision.providers,
                decision.workflows,
            )
            for evidence_id in group.evidence_ids
        }
        | {
            evidence_id
            for hypothesis in decision.hypotheses.values()
            for evidence_id in hypothesis.evidence_ids
        }
        | {
            evidence_id
            for conflict in decision.conflicts.values()
            for evidence_id in conflict.evidence_ids
        }
    )
    return ContextPacket.model_validate(
        {
            "schema": "dotfiles.context-packet.v0",
            "requestID": request.request_id,
            "contextDigest": digest_value(subject),
            "selected": {
                "fragmentIDs": [item.fragment_id for item in selected.fragments],
                "files": [item.path for item in selected.files],
                "providerIDs": [item.provider_id for item in selected.providers],
                "workflowIDs": [item.workflow_id for item in selected.workflows],
            },
            "evidenceIDs": referenced_evidence,
            "unresolvedGapIDs": sufficiency.blocking_gap_ids,
            "provenance": {
                "semanticRole": "workflow",
                "artifactClass": "generated_projection",
                "claimAuthority": "candidate",
            },
        }
    )


def cue_validate_state(model_root: Path, state: ContextState, cue_binary: str = "cue") -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json") as handle:
        handle.write(state.model_dump_json(by_alias=True, exclude_none=True))
        handle.flush()
        process = subprocess.run(
            [cue_binary, "vet", "-c", "-d", "#ContextState", ".", handle.name],
            cwd=model_root,
            capture_output=True,
            text=True,
            check=False,
            timeout=30,
        )
    if process.returncode != 0:
        raise EngineError(process.stderr.strip() or "CUE rejected context state")


def project_hook(state: ContextState) -> dict[str, Any]:
    payload = {
        "schema": "agent.resolver-prompt-surface.v2",
        "requestID": state.request.request_id,
        "sufficiency": state.sufficiency.model_dump(by_alias=True),
        "context": state.projection.model_dump(by_alias=True) if state.projection else None,
        "execution": {
            "mode": "prompt-only",
            "routeExecution": False,
            "sourceAuthority": False,
            "rawTranscriptForwarding": False,
        },
    }
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": json.dumps(payload, sort_keys=True, separators=(",", ":")),
        }
    }


def project_code_intel(state: ContextState) -> dict[str, Any]:
    selected_provider_ids = [item.provider_id for item in state.selected.providers]
    selected_workflow_ids = [item.workflow_id for item in state.selected.workflows]
    return {
        "schema": "dotfiles.code-intel-context.v0",
        "reference": True,
        "authority": False,
        "requestID": state.request.request_id,
        "contextDigest": state.projection.context_digest if state.projection else None,
        "providers": {
            key: state.inventory.providers[key].model_dump(by_alias=True)
            for key in selected_provider_ids
        },
        "workflows": {
            key: state.inventory.workflows[key].model_dump(by_alias=True)
            for key in selected_workflow_ids
        },
        "evidenceIDs": state.projection.evidence_ids if state.projection else [],
    }


class ContextEngine:
    def __init__(self, *, root: Path, cue_binary: str = "cue") -> None:
        self.root = root.resolve(strict=True)
        self.cue_binary = cue_binary

    def run(self, *, request: ContextRequest, reasoner: ContextReasoner) -> EngineResult:
        snapshot = RepositorySnapshot.resolve(self.root, request.repository.revision)
        with tempfile.TemporaryDirectory(prefix="context-workbook-cue-") as temporary:
            model_root = snapshot.materialize_cue_package(
                ".codex/context-model", Path(temporary)
            )
            config = _load_workbook_config(model_root, self.cue_binary)
            _validate_request_against_config(request, config)
            inventory = load_inventory(model_root, self.cue_binary)
            code_intel = load_code_intel(
                snapshot, config.code_intel_files, request.allowed_paths
            )
            inventory = _scope_inventory(inventory, request.allowed_paths, code_intel)
            declared_paths = _declared_paths(
                snapshot, inventory, code_intel, request.allowed_paths
            )
            materialized = materialize_inputs(
                prompt=request.prompt,
                requested_revision=snapshot.requested_revision,
                resolved_revision=snapshot.resolved_revision,
                inventory=inventory,
                selected_paths=declared_paths,
                code_intel=code_intel,
            )
            try:
                decision = reasoner.establish(
                    request=request,
                    inventory=inventory,
                    observations=materialized.observations,
                    evidence=materialized.evidence,
                    code_intel=materialized.code_intel,
                )
            except DspyUnavailable as error:
                decision = fail_closed_decision(str(error))
            _validate_decision(
                snapshot=snapshot,
                request=request,
                inventory=inventory,
                decision=decision,
                max_selected_files=config.max_selected_files,
            )
            selected = _selection_items(decision)
            sufficiency = _derive_sufficiency(decision)
            packet = _make_packet(
                request=request,
                inventory=inventory,
                observations=materialized.observations,
                evidence=materialized.evidence,
                decision=decision,
                selected=selected,
                sufficiency=sufficiency,
            )
            state = ContextState.model_validate(
                {
                    "schema": "dotfiles.context-state.v0",
                    "request": request.model_dump(by_alias=True),
                    "inventory": inventory.model_dump(by_alias=True),
                    "observations": {
                        key: value.model_dump(by_alias=True)
                        for key, value in materialized.observations.items()
                    },
                    "providerObservations": [],
                    "evidence": {
                        key: value.model_dump(by_alias=True)
                        for key, value in materialized.evidence.items()
                    },
                    "hypotheses": {
                        key: value.model_dump(by_alias=True)
                        for key, value in decision.hypotheses.items()
                    },
                    "selected": selected.model_dump(by_alias=True),
                    "gaps": {
                        key: value.model_dump(by_alias=True)
                        for key, value in decision.gaps.items()
                    },
                    "conflicts": {
                        key: value.model_dump(by_alias=True)
                        for key, value in decision.conflicts.items()
                    },
                    "sufficiency": sufficiency.model_dump(by_alias=True),
                    "projection": packet.model_dump(by_alias=True) if packet else None,
                }
            )
            cue_validate_state(model_root, state, self.cue_binary)
        serialized_packet = json.dumps(
            state.projection.model_dump(by_alias=True) if state.projection else {},
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
        if len(serialized_packet) > config.max_packet_bytes:
            raise EngineError("projected packet exceeds configured byte limit")
        trace = {
            **materialized.node_digests,
            "decision": digest_value(decision.model_dump(by_alias=True)),
            "sufficiency": digest_value(sufficiency.model_dump(by_alias=True)),
            "projection": digest_value(
                state.projection.model_dump(by_alias=True) if state.projection else {}
            ),
        }
        return EngineResult(
            state=state,
            trace=trace,
            hook_projection=(
                project_hook(state)
                if "agent-context-resolver" in request.requested_projection_ids
                else None
            ),
            code_intel_projection=(
                project_code_intel(state)
                if "code-intel" in request.requested_projection_ids
                else None
            ),
        )


def fail_closed_decision(message: str) -> ContextDecision:
    return ContextDecision.model_validate(
        {
            "hypotheses": {},
            "fragments": {
                "ids": [],
                "reason": "No fragments selected because DSPy context establishment was unavailable.",
                "evidenceIDs": ["evidence.prompt"],
            },
            "files": {
                "ids": [],
                "reason": "No files selected because DSPy context establishment was unavailable.",
                "evidenceIDs": ["evidence.prompt"],
            },
            "providers": {
                "ids": [],
                "reason": "No providers selected because DSPy context establishment was unavailable.",
                "evidenceIDs": ["evidence.code-intel"],
            },
            "workflows": {
                "ids": [],
                "reason": "No workflows selected because DSPy context establishment was unavailable.",
                "evidenceIDs": ["evidence.prompt"],
            },
            "gaps": {
                "gap.dspy-unavailable": {
                    "kind": "runtime-capability",
                    "description": message,
                    "blocksSufficiency": True,
                    "requiredEvidenceIDs": [],
                }
            },
            "conflicts": {},
            "sufficiencyState": "insufficient",
            "sufficiencyReasons": ["DSPy context establishment did not run."],
        }
    )


class FailClosedProgram:
    def __init__(self, message: str) -> None:
        self._decision = fail_closed_decision(message)

    def establish(self, **_: object) -> ContextDecision:
        return self._decision


def production_reasoner_or_fail_closed() -> ContextReasoner:
    from .dspy_program import production_reasoner

    try:
        return production_reasoner()
    except DspyUnavailable as error:
        return FailClosedProgram(str(error))


def establish_context(
    *,
    root: Path,
    request: ContextRequest,
    reasoner: ContextReasoner,
    cue_binary: str = "cue",
) -> EngineResult:
    return ContextEngine(root=root, cue_binary=cue_binary).run(request=request, reasoner=reasoner)
