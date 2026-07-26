"""Revision-bound orchestration for the authoritative context graph service."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Literal

from .repository import RepositoryError, RepositorySnapshot


class GraphServiceError(RuntimeError):
    """An internal failure which must be translated at the transport boundary."""

    def __init__(self, stage: str, code: str, message: str) -> None:
        super().__init__(message)
        self.stage = stage
        self.code = code


@dataclass(frozen=True)
class RevisionBinding:
    snapshot: RepositorySnapshot
    overlay_enabled: bool


@dataclass(frozen=True)
class SourceManifest:
    version: str
    paths: tuple[str, ...]


def bind_revision(
    root: Path,
    revision: str,
    overlay_mode: Literal["disabled", "required", "auto"],
) -> RevisionBinding:
    """Resolve the commit first, then decide whether overlay observation is legal."""

    try:
        snapshot = RepositorySnapshot.resolve(root, revision)
        head = RepositorySnapshot.resolve(root, "HEAD").resolved_revision
    except RepositoryError as error:
        raise GraphServiceError("revision", "revision.unresolved", str(error)) from error

    if overlay_mode == "disabled":
        return RevisionBinding(snapshot=snapshot, overlay_enabled=False)
    if overlay_mode == "required" and snapshot.resolved_revision != head:
        raise GraphServiceError(
            "revision",
            "overlay.historical-revision",
            "required overlay hydration is valid only for the checkout HEAD",
        )
    if overlay_mode not in {"required", "auto"}:
        raise GraphServiceError("revision", "overlay.mode-unknown", "unknown overlay mode")
    return RevisionBinding(
        snapshot=snapshot,
        overlay_enabled=snapshot.resolved_revision == head,
    )


def source_manifest_digest(
    snapshot: RepositorySnapshot,
    manifest: SourceManifest,
) -> str:
    """Hash ``version NUL path NUL bytes NUL ...`` at the bound revision."""

    ordered = list(manifest.paths)
    if ordered != sorted(ordered) or len(ordered) != len(set(ordered)):
        raise GraphServiceError(
            "manifest", "manifest.paths-not-canonical", "manifest paths must be sorted and unique"
        )
    digest = hashlib.sha256()
    digest.update(manifest.version.encode())
    digest.update(b"\0")
    for path in ordered:
        digest.update(path.encode())
        digest.update(b"\0")
        try:
            digest.update(snapshot.read_bytes(path))
        except (RepositoryError, UnicodeError) as error:
            raise GraphServiceError("manifest", "manifest.source-unavailable", str(error)) from error
        digest.update(b"\0")
    return f"sha256:{digest.hexdigest()}"


def qualified_hydrator(
    *,
    snapshot: RepositorySnapshot,
    manifest: SourceManifest,
    cache_root: Path,
) -> tuple[Path, str]:
    """Build the exact revision's hydrator and atomically cache it by source digest."""

    digest = source_manifest_digest(snapshot, manifest)
    target = cache_root / digest.removeprefix("sha256:") / "context-git-hydrator"
    if target.is_file() and os.access(target, os.X_OK):
        return target, digest

    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="context-git-hydrator-") as temporary:
        checkout = Path(temporary) / "source"
        for relative in manifest.paths:
            content = snapshot.read_bytes(relative)
            destination = checkout / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
        built = Path(temporary) / "context-git-hydrator"
        process = subprocess.run(
            [
                "go",
                "build",
                "-trimpath",
                "-ldflags",
                (
                    "-X github.com/fatb4f/dotfiles/.codex/context-hydrators/git/"
                    f"internal/hydrator.BuildHydratorDigest={digest}"
                ),
                "-o",
                str(built),
                "./cmd/context-git-hydrator",
            ],
            cwd=checkout / ".codex/context-hydrators/git",
            capture_output=True,
            check=False,
            timeout=120,
        )
        if process.returncode:
            raise GraphServiceError(
                "hydration",
                "hydrator.build-failed",
                process.stderr.decode(errors="replace").strip() or "hydrator build failed",
            )
        os.chmod(built, 0o755)
        os.replace(built, target)
    return target, digest


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def _hydrate(
    hydrator: Path,
    command: str,
    request: dict[str, object],
    *,
    cwd: Path,
) -> dict[str, object]:
    with tempfile.TemporaryDirectory(prefix="context-graph-hydration-") as temporary:
        request_path = Path(temporary) / "request.json"
        request_path.write_bytes(_canonical(request))
        process = subprocess.run(
            [str(hydrator), command, "--request", str(request_path)],
            cwd=cwd,
            capture_output=True,
            check=False,
            timeout=120,
        )
    if process.returncode:
        raise GraphServiceError(
            "hydration",
            f"hydrator.{command}-failed",
            process.stderr.decode(errors="replace").strip() or f"{command} hydration failed",
        )
    try:
        payload = json.loads(process.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GraphServiceError(
            "hydration", "hydrator.output-invalid", "hydrator returned invalid JSON"
        ) from error
    if not isinstance(payload, dict):
        raise GraphServiceError(
            "hydration", "hydrator.output-invalid", "hydrator returned a non-object"
        )
    return payload


def hydrate_revision(
    *,
    binding: RevisionBinding,
    repository_id: str,
    hydrator: Path,
) -> tuple[dict[str, object], dict[str, object] | None]:
    committed = _hydrate(
        hydrator,
        "committed",
        {
            "schema": "kernel.git-committed-snapshot-request.v0",
            "repositoryID": repository_id,
            "path": ".",
            "revision": binding.snapshot.resolved_revision,
        },
        cwd=binding.snapshot.root,
    )
    overlay = None
    if binding.overlay_enabled:
        overlay = _hydrate(
            hydrator,
            "overlay",
            {
                "schema": "kernel.git-overlay-request.v0",
                "repositoryID": repository_id,
                "path": ".",
                "baseRevision": {
                    "format": "sha1",
                    "hex": binding.snapshot.resolved_revision,
                },
            },
            cwd=binding.snapshot.root,
        )
    return committed, overlay


def _cue_export(model_root: Path, expression: str, *, stage: str) -> object:
    process = subprocess.run(
        ["cue", "export", ".", "-e", expression, "--out", "json"],
        cwd=model_root,
        capture_output=True,
        check=False,
        timeout=120,
    )
    if process.returncode:
        raise GraphServiceError(
            stage,
            f"{stage}.cue-rejected",
            process.stderr.decode(errors="replace").strip() or "CUE evaluation failed",
        )
    try:
        return json.loads(process.stdout)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise GraphServiceError(
            stage,
            f"{stage}.cue-output-invalid",
            "CUE returned invalid JSON",
        ) from error


def _load_source_manifest(model_root: Path, expression: str) -> SourceManifest:
    value = _cue_export(model_root, expression, stage="manifest")
    if not isinstance(value, dict):
        raise GraphServiceError(
            "manifest", "manifest.invalid", f"{expression} must export an object"
        )
    version = value.get("version")
    paths = value.get("paths")
    if not isinstance(version, str) or not version:
        raise GraphServiceError(
            "manifest", "manifest.invalid", f"{expression}.version must be non-empty"
        )
    if not isinstance(paths, list) or not paths or not all(
        isinstance(path, str) for path in paths
    ):
        raise GraphServiceError(
            "manifest", "manifest.invalid", f"{expression}.paths must be non-empty strings"
        )
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise GraphServiceError(
            "manifest",
            "manifest.paths-not-canonical",
            f"{expression}.paths must be sorted and unique",
        )
    return SourceManifest(version=version, paths=tuple(paths))


def load_revision_manifests(
    model_root: Path,
) -> tuple[SourceManifest, SourceManifest, SourceManifest]:
    return (
        _load_source_manifest(model_root, "contextSchemaSources"),
        _load_source_manifest(model_root, "contextPolicySources"),
        _load_source_manifest(model_root, "gitHydratorSources"),
    )


def _read_object(path: Path, *, stage: str, code: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise GraphServiceError(stage, code, str(error)) from error
    if not isinstance(value, dict):
        raise GraphServiceError(stage, code, f"{path} must contain an object")
    return value


def _runtime_cue_source(
    *,
    request: dict[str, object],
    proposal: dict[str, object] | None,
    committed: dict[str, object],
    overlay: dict[str, object] | None,
    schema_digest: str,
    policy_digest: str,
) -> str:
    request_json = json.dumps(request, sort_keys=True, separators=(",", ":"))
    committed_json = json.dumps(committed, sort_keys=True, separators=(",", ":"))
    lines = [
        "package contextmodel",
        "",
        f"runtimeRequest: #ContextApplicationRequest & {request_json}",
        "runtimePolicy: #ContextSelectionPolicy & {",
        '\tschema: "dotfiles.context-selection-policy.v0"',
        '\tpredicates: ["contains"]',
        "\tlimits: {}",
        "}",
        "runtimeCommittedProjection: #GitCommittedSnapshotProjection & {",
        f"\tobservation: {committed_json}",
        f'\tschemaDigest: "{schema_digest}"',
        f'\tpolicyDigest: "{policy_digest}"',
        "}",
    ]
    projection = "runtimeCommittedProjection"
    evaluation_type = "#ContextCommittedSelectionEvaluation"
    if overlay is not None:
        overlay_json = json.dumps(overlay, sort_keys=True, separators=(",", ":"))
        lines.extend(
            [
                "runtimeOverlayProjection: #GitOverlayProjection & {",
                "\tcommitted: runtimeCommittedProjection",
                f"\tobservation: {overlay_json}",
                f'\tschemaDigest: "{schema_digest}"',
                f'\tpolicyDigest: "{policy_digest}"',
                "}",
            ]
        )
        projection = "runtimeOverlayProjection"
        evaluation_type = "#ContextOverlaySelectionEvaluation"

    if proposal is None:
        lines.extend(
            [
                "runtimeProposal: #ContextRootProposal & {",
                '\tschema: "dotfiles.context-root-proposal.v0"',
                "\trequestID: runtimeRequest.requestID",
                f"\tsnapshotID: {projection}.graph.snapshotID",
                "\tmemberIDs: []",
                "\tnamespaceIDs: []",
                "\tpathPrefixes: []",
                "}",
            ]
        )
    else:
        proposal_json = json.dumps(proposal, sort_keys=True, separators=(",", ":"))
        lines.append(f"runtimeProposal: #ContextRootProposal & {proposal_json}")

    evaluation_lines = [
        f"runtimeEvaluation: {evaluation_type} & {{",
        "\trequest: runtimeRequest",
        "\tproposal: runtimeProposal",
        "\tpolicy: runtimePolicy",
        "\tcommittedProjection: runtimeCommittedProjection",
    ]
    if overlay is not None:
        evaluation_lines.append("\toverlayProjection: runtimeOverlayProjection")
    evaluation_lines.extend(
        [
            "}",
            "runtimeResult: {",
            '\tschema: "dotfiles.context-graph-service-result.v0"',
            '\tstatus: "success"',
            "\tevaluation: runtimeEvaluation",
            "}",
            "",
        ]
    )
    lines.extend(evaluation_lines)
    return "\n".join(lines)


def evaluate_revision(
    *,
    model_root: Path,
    request: dict[str, object],
    proposal: dict[str, object] | None,
    committed: dict[str, object],
    overlay: dict[str, object] | None,
    schema_digest: str,
    policy_digest: str,
) -> dict[str, object]:
    runtime_path = model_root / "runtime_graph_service.cue"
    runtime_path.write_text(
        _runtime_cue_source(
            request=request,
            proposal=proposal,
            committed=committed,
            overlay=overlay,
            schema_digest=schema_digest,
            policy_digest=policy_digest,
        ),
        encoding="utf-8",
    )
    _cue_export(model_root, "runtimeCommittedProjection", stage="snapshot")
    projection_expression = "runtimeCommittedProjection"
    if overlay is not None:
        _cue_export(model_root, "runtimeOverlayProjection", stage="snapshot")
        projection_expression = "runtimeOverlayProjection"
    projection = _cue_export(model_root, projection_expression, stage="snapshot")
    if not isinstance(projection, dict):
        raise GraphServiceError(
            "snapshot", "snapshot.cue-output-invalid", "projection must be an object"
        )
    graph = projection.get("graph")
    if not isinstance(graph, dict) or not isinstance(graph.get("snapshotID"), str):
        raise GraphServiceError(
            "snapshot", "snapshot.cue-output-invalid", "projection graph is incomplete"
        )
    if proposal is not None and proposal.get("snapshotID") != graph["snapshotID"]:
        raise GraphServiceError(
            "proposal",
            "proposal.snapshot-mismatch",
            "proposal snapshotID does not match the authoritative projection",
        )
    _cue_export(model_root, "runtimeProposal", stage="proposal")
    result = _cue_export(model_root, "runtimeResult", stage="selection")
    if not isinstance(result, dict) or result.get("status") != "success":
        raise GraphServiceError(
            "selection", "selection.cue-output-invalid", "CUE did not produce a success result"
        )
    return result


def _failure(request_id: str, error: GraphServiceError) -> dict[str, object]:
    return {
        "schema": "dotfiles.context-graph-service-result.v0",
        "status": "failure",
        "failure": {
            "schema": "dotfiles.context-graph-failure.v0",
            "requestID": request_id,
            "stage": error.stage,
            "code": error.code,
            "message": str(error),
            "details": {},
        },
    }


def main(arguments: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--request-file", type=Path, required=True)
    parser.add_argument("--proposal-file", type=Path)
    args = parser.parse_args(arguments)
    request_id = "request.unknown"
    try:
        request = _read_object(
            args.request_file, stage="proposal", code="request.invalid"
        )
        request_id = request.get("requestID", request_id)
        if not isinstance(request_id, str):
            request_id = "request.unknown"
        binding = bind_revision(
            args.repo_root,
            str(request.get("revision", "")),
            str(request.get("overlayMode", "")),  # type: ignore[arg-type]
        )
        cache_root = Path(
            os.environ.get(
                "CONTEXT_GRAPH_CACHE",
                str(
                    Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
                    / "dotfiles-context-graph"
                ),
            )
        )
        proposal = (
            _read_object(
                args.proposal_file,
                stage="proposal",
                code="proposal.invalid",
            )
            if args.proposal_file is not None
            else None
        )
        with tempfile.TemporaryDirectory(prefix="context-graph-cue-") as temporary:
            try:
                model_root = binding.snapshot.materialize_cue_package(
                    ".codex/context-model", Path(temporary)
                )
            except RepositoryError as error:
                raise GraphServiceError(
                    "manifest", "manifest.package-unavailable", str(error)
                ) from error
            schema_manifest, policy_manifest, hydrator_manifest = (
                load_revision_manifests(model_root)
            )
            schema_digest = source_manifest_digest(binding.snapshot, schema_manifest)
            policy_digest = source_manifest_digest(binding.snapshot, policy_manifest)
            hydrator, _ = qualified_hydrator(
                snapshot=binding.snapshot,
                manifest=hydrator_manifest,
                cache_root=cache_root,
            )
            committed, overlay = hydrate_revision(
                binding=binding,
                repository_id=str(request.get("repository", "")),
                hydrator=hydrator,
            )
            result = evaluate_revision(
                model_root=model_root,
                request=request,
                proposal=proposal,
                committed=committed,
                overlay=overlay,
                schema_digest=schema_digest,
                policy_digest=policy_digest,
            )
    except (OSError, json.JSONDecodeError) as error:
        result = _failure(
            request_id,
            GraphServiceError("proposal", "request.invalid", str(error)),
        )
    except GraphServiceError as error:
        result = _failure(request_id, error)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
    return 0 if result["status"] == "success" else 2


if __name__ == "__main__":
    sys.exit(main())
