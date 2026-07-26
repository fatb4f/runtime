"""Bounded repository and code-intel materialization."""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .models import (
    ContextInventory,
    Evidence,
    SourceObservation,
    digest_value,
    path_is_allowed,
)
from .repository import RepositorySnapshot


class IngestError(RuntimeError):
    pass


@dataclass(frozen=True)
class MaterializedInputs:
    inventory: ContextInventory
    observations: dict[str, SourceObservation]
    evidence: dict[str, Evidence]
    code_intel: dict[str, Any]
    node_digests: dict[str, str]


def load_inventory(model_root: Path, cue_binary: str = "cue") -> ContextInventory:
    """Export the authoritative inventory from CUE through the pinned CLI."""
    import subprocess

    process = subprocess.run(
        [cue_binary, "export", ".", "-e", "rootSeed.inventory", "--out", "json"],
        cwd=model_root,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if process.returncode != 0:
        raise IngestError(process.stderr.strip() or "CUE inventory export failed")
    value = json.loads(process.stdout)
    return ContextInventory.model_validate(value)


def path_glob_intersects_allowed(pattern: str, allowed_paths: list[str]) -> bool:
    wildcard = re.search(r"[*?\[]", pattern)
    literal = pattern if wildcard is None else pattern[: wildcard.start()]
    if wildcard is not None:
        literal = literal.rsplit("/", 1)[0] if "/" in literal else "."
    candidate = literal.rstrip("/") or "."
    return path_is_allowed(candidate, allowed_paths) or any(
        path_is_allowed(allowed, [candidate]) for allowed in allowed_paths
    )


def _scope_code_intel_document(document: Any, allowed_paths: list[str]) -> Any:
    if not isinstance(document, dict):
        return document
    scoped = dict(document)
    if isinstance(document.get("entrypoints"), list):
        scoped["entrypoints"] = [
            entrypoint
            for entrypoint in document["entrypoints"]
            if isinstance(entrypoint, dict)
            and isinstance(entrypoint.get("path"), str)
            and path_is_allowed(entrypoint["path"], allowed_paths)
        ]
    if isinstance(document.get("routes"), list):
        routes = []
        for route in document["routes"]:
            if not isinstance(route, dict):
                continue
            globs = [
                glob
                for glob in route.get("globs", [])
                if isinstance(glob, str)
                and path_glob_intersects_allowed(glob, allowed_paths)
            ]
            if globs:
                routes.append({**route, "globs": globs})
        scoped["routes"] = routes
    return scoped


def load_code_intel(
    snapshot: RepositorySnapshot,
    declared_files: list[str],
    allowed_paths: list[str],
) -> dict[str, Any]:
    """Load and scope declared read-only code-intel files to the request boundary."""
    return {
        path: _scope_code_intel_document(
            json.loads(snapshot.read_text(path)), allowed_paths
        )
        for path in declared_files
        if path_is_allowed(path, allowed_paths)
    }


def match_code_intel_paths(code_intel: dict[str, Any], paths: list[str]) -> dict[str, list[str]]:
    routing = next(
        (
            document
            for document in code_intel.values()
            if isinstance(document, dict) and isinstance(document.get("routes"), list)
        ),
        None,
    )
    if routing is None:
        return {}
    matches: dict[str, list[str]] = {}
    for route in routing.get("routes", []):
        route_matches = [
            path for path in paths if any(fnmatch.fnmatch(path, glob) for glob in route.get("globs", []))
        ]
        if route_matches:
            matches[route["id"]] = sorted(route_matches)
    return matches


def materialize_inputs(
    *,
    prompt: str,
    requested_revision: str,
    resolved_revision: str,
    inventory: ContextInventory,
    selected_paths: list[str],
    code_intel: dict[str, Any],
) -> MaterializedInputs:
    path_matches = match_code_intel_paths(code_intel, selected_paths)

    observations: dict[str, SourceObservation] = {
        "prompt.current": SourceObservation.model_validate(
            {
                "kind": "prompt",
                "subject": "user-prompt",
                "facts": {"text": prompt, "digest": digest_value(prompt)},
                "diagnostics": [],
                "provenance": {
                    "semanticRole": "evidence",
                    "artifactClass": "runtime_observation",
                    "claimAuthority": "none",
                },
            }
        ),
        "repository.current": SourceObservation.model_validate(
            {
                "kind": "repository",
                "subject": "fatb4f/dotfiles",
                "facts": {
                    "requestedRevision": requested_revision,
                    "resolvedRevision": resolved_revision,
                    "selectedPaths": selected_paths,
                    "selectedPathDigest": digest_value(selected_paths),
                },
                "diagnostics": [],
                "provenance": {
                    "semanticRole": "evidence",
                    "artifactClass": "runtime_observation",
                    "claimAuthority": "none",
                },
            }
        ),
    }
    if code_intel:
        observations["provider.registry"] = SourceObservation.model_validate(
            {
                "kind": "provider",
                "subject": "code-intel",
                "facts": {
                    "declaredFiles": sorted(code_intel),
                    "digest": digest_value(code_intel),
                    "pathMatches": path_matches,
                },
                "diagnostics": [],
                "provenance": {
                    "semanticRole": "evidence",
                    "artifactClass": "runtime_observation",
                    "claimAuthority": "none",
                },
            }
        )
    evidence = {
        "evidence.prompt": Evidence.model_validate(
            {
                "summary": "The current user prompt is available as bounded runtime evidence.",
                "observationIDs": ["prompt.current"],
                "provenance": {
                    "semanticRole": "evidence",
                    "artifactClass": "runtime_observation",
                    "claimAuthority": "candidate",
                },
            }
        ),
        "evidence.repository": Evidence.model_validate(
            {
                "summary": "Repository revision and explicitly selected paths are materialized.",
                "observationIDs": ["repository.current"],
                "provenance": {
                    "semanticRole": "evidence",
                    "artifactClass": "runtime_observation",
                    "claimAuthority": "candidate",
                },
            }
        ),
    }
    if code_intel:
        evidence["evidence.code-intel"] = Evidence.model_validate(
            {
                "summary": "Declared code-intel registries were loaded as read-only evidence.",
                "observationIDs": ["provider.registry"],
                "provenance": {
                    "semanticRole": "evidence",
                    "artifactClass": "runtime_observation",
                    "claimAuthority": "candidate",
                },
            }
        )
    node_digests = {
        "inventory": digest_value(inventory.model_dump(by_alias=True)),
        "prompt": digest_value(prompt),
        "repository": digest_value(
            {
                "requestedRevision": requested_revision,
                "resolvedRevision": resolved_revision,
                "paths": selected_paths,
            }
        ),
        "code-intel": digest_value(code_intel),
        "materialized-evidence": digest_value(
            {
                "observations": {
                    key: value.model_dump(by_alias=True) for key, value in observations.items()
                },
                "evidence": {key: value.model_dump(by_alias=True) for key, value in evidence.items()},
            }
        ),
    }
    return MaterializedInputs(
        inventory=inventory,
        observations=observations,
        evidence=evidence,
        code_intel=code_intel,
        node_digests=node_digests,
    )
