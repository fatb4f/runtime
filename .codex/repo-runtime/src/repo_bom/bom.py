from __future__ import annotations

import copy
import hashlib
import json
import re
import uuid
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import quote

PROFILE = "repository-bom.cyclonedx-1.7.v0"
PRODUCER = {"name": "repository-bom-runtime", "version": "0.1.0"}
_DIGEST = re.compile(r"^sha256:[0-9a-f]{64}$")


class BomError(ValueError):
    pass


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def _stable_ref(kind: str, *parts: str) -> str:
    seed = "\0".join((kind, *parts))
    return f"urn:repo-bom:{kind}:{hashlib.sha256(seed.encode()).hexdigest()}"


def _properties(values: dict[str, str]) -> list[dict[str, str]]:
    return [{"name": name, "value": values[name]} for name in sorted(values)]


def _source_identity(source: object) -> str:
    if not isinstance(source, dict):
        return "unknown"
    normalized = copy.deepcopy(source)
    for value in normalized.values():
        if isinstance(value, dict):
            if "url" in value:
                url = str(value["url"])
                value["url"] = url.split("@")[-1] if "://" not in url else re.sub(
                    r"(?<=://)[^/@]+@", "", url
                )
            if "path" in value:
                value["path"] = "<local>"
    return hashlib.sha256(canonical_bytes(normalized)).hexdigest()


def _component(node: dict[str, Any], repository_id: str, members: set[str]) -> dict[str, Any]:
    name = str(node["name"]).lower().replace("_", "-")
    version = str(node.get("version") or "0")
    source = node.get("source", {})
    first_party = str(node.get("id", "")) in members
    if first_party:
        ref = _stable_ref("module", repository_id, "subject/default", "python", name)
        purl = f"pkg:pypi/{quote(name)}@{quote(version)}"
        properties = {
            "repo-bom:classification": "first-party",
            "repo-bom:partition": "subject/default",
            "repo-bom:realization-path": _relative_member_path(node),
        }
    else:
        source_id = _source_identity(source)
        ref = _stable_ref("package", "python", name, version, source_id)
        purl = f"pkg:pypi/{quote(name)}@{quote(version)}"
        properties = {
            "repo-bom:classification": "external",
            "repo-bom:source-digest": f"sha256:{source_id}",
        }
    return {
        "type": "library",
        "bom-ref": ref,
        "name": name,
        "version": version,
        "purl": purl,
        "properties": _properties(properties),
    }


def _relative_member_path(node: dict[str, Any]) -> str:
    path = str(node.get("path", ".")).replace("\\", "/").rstrip("/")
    if path in ("", "."):
        return "."
    # uv emits checkout-absolute paths for workspace members; only the suffix
    # supplied by assembly is retained. This placeholder is replaced there.
    return path


def assemble(observation: Any) -> dict[str, Any]:
    repository = observation.repository
    tree = observation.uv.tree
    resolution = tree.get("resolution")
    members_raw = tree.get("members", [])
    if not isinstance(resolution, dict) or not isinstance(members_raw, list):
        raise BomError("uv tree is missing resolution or members")
    member_ids = {str(member["id"]) for member in members_raw}
    nodes: dict[str, dict[str, Any]] = {}
    for node_id, raw in resolution.items():
        if not isinstance(raw, dict):
            raise BomError(f"invalid uv node {node_id}")
        if raw.get("kind") == "workspace":
            continue
        node = dict(raw)
        node["id"] = node_id
        nodes[node_id] = node
    # uv's member list is authoritative and may carry its path outside resolution.
    for member in members_raw:
        node_id = str(member["id"])
        nodes.setdefault(node_id, dict(member))["path"] = member.get("path", ".")

    root_ref = _stable_ref("repository", repository.repository_id)
    components_by_id: dict[str, dict[str, Any]] = {}
    for node_id, node in nodes.items():
        component = _component(node, repository.repository_id, member_ids)
        if node_id in member_ids:
            raw_path = Path(str(node.get("path", repository.root)))
            try:
                relative = raw_path.resolve().relative_to(repository.root).as_posix() or "."
            except ValueError as error:
                raise BomError("uv workspace member is outside the repository") from error
            component["properties"] = _properties(
                {
                    **{p["name"]: p["value"] for p in component["properties"]},
                    "repo-bom:realization-path": relative,
                }
            )
        components_by_id[node_id] = component

    dependencies: list[dict[str, Any]] = []
    root_targets = sorted(
        components_by_id[node_id]["bom-ref"] for node_id in member_ids if node_id in components_by_id
    )
    dependencies.append({"ref": root_ref, "dependsOn": root_targets})
    for node_id, node in nodes.items():
        targets = []
        for dependency in node.get("dependencies", []):
            target_id = dependency.get("id") if isinstance(dependency, dict) else None
            if target_id not in components_by_id:
                raise BomError(f"unresolved uv dependency reference: {target_id}")
            targets.append(components_by_id[target_id]["bom-ref"])
        dependencies.append(
            {"ref": components_by_id[node_id]["bom-ref"], "dependsOn": sorted(set(targets))}
        )

    profile_digest = "sha256:" + hashlib.sha256(PROFILE.encode()).hexdigest()
    producer_digest = "sha256:" + hashlib.sha256(canonical_bytes(PRODUCER)).hexdigest()
    generation_inputs = {
        "repositoryID": repository.repository_id,
        "revision": repository.revision,
        "tree": repository.tree,
        "worktreeDigest": repository.worktree_digest,
        "projectDigest": observation.uv.project_digest,
        "lockDigest": observation.uv.lock_digest,
        "profileDigest": profile_digest,
        "producerDigest": producer_digest,
    }
    generation_digest = "sha256:" + hashlib.sha256(canonical_bytes(generation_inputs)).hexdigest()
    serial = uuid.UUID(generation_digest.removeprefix("sha256:")[:32])
    document = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.7",
        "serialNumber": f"urn:uuid:{serial}",
        "version": 1,
        "metadata": {
            "tools": {
                "components": [
                    {
                        "type": "application",
                        "bom-ref": _stable_ref("tool", PRODUCER["name"], PRODUCER["version"]),
                        **PRODUCER,
                    }
                ]
            },
            "component": {
                "type": "application",
                "bom-ref": root_ref,
                "name": repository.repository_id,
                "version": repository.revision,
                "properties": _properties(
                    {
                        "repo-bom:completeness": "uv-complete;other-content-unclassified",
                        "repo-bom:generation-digest": generation_digest,
                        "repo-bom:lock-digest": observation.uv.lock_digest,
                        "repo-bom:partition": "subject/default",
                        "repo-bom:producer-digest": producer_digest,
                        "repo-bom:profile": PROFILE,
                        "repo-bom:profile-digest": profile_digest,
                        "repo-bom:project-digest": observation.uv.project_digest,
                        "repo-bom:repository-id": repository.repository_id,
                        "repo-bom:revision": repository.revision,
                        "repo-bom:tree": repository.tree,
                        "repo-bom:worktree-digest": repository.worktree_digest,
                    }
                ),
            },
        },
        "components": sorted(components_by_id.values(), key=lambda value: value["bom-ref"]),
        "dependencies": sorted(dependencies, key=lambda value: value["ref"]),
    }
    validate(document)
    return document


def _walk(value: object):
    if isinstance(value, dict):
        for key, child in value.items():
            yield key, child
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def validate(document: dict[str, Any]) -> None:
    if document.get("bomFormat") != "CycloneDX" or document.get("specVersion") != "1.7":
        raise BomError("only the CycloneDX 1.7 Repository BOM profile is admitted")
    if document.get("version") != 1:
        raise BomError("BOM version must be 1")
    root = document.get("metadata", {}).get("component", {})
    components = document.get("components")
    dependencies = document.get("dependencies")
    if not isinstance(root, dict) or not isinstance(components, list) or not isinstance(dependencies, list):
        raise BomError("metadata.component, components, and dependencies are required")
    refs = [root.get("bom-ref")] + [component.get("bom-ref") for component in components]
    if any(not isinstance(ref, str) or not ref for ref in refs) or len(refs) != len(set(refs)):
        raise BomError("component identities must be non-empty and unique")
    dependency_refs = [entry.get("ref") for entry in dependencies]
    if len(dependency_refs) != len(set(dependency_refs)) or set(dependency_refs) != set(refs):
        raise BomError("dependencies must define every component exactly once")
    for entry in dependencies:
        targets = entry.get("dependsOn")
        if not isinstance(targets, list) or targets != sorted(set(targets)):
            raise BomError("dependency references must be sorted and unique")
        if not set(targets) <= set(refs):
            raise BomError("dependency reference is unresolved")
    for component in [root, *components]:
        component_properties = component.get("properties", [])
        property_names = [item.get("name") for item in component_properties]
        if property_names != sorted(set(property_names)):
            raise BomError("component properties must have unique canonical names")
        for item in component_properties:
            if item.get("name") == "repo-bom:realization-path":
                value = item.get("value")
                if not isinstance(value, str):
                    raise BomError("realization path must be a string")
                path = PurePosixPath(value)
                if path.is_absolute() or "\\" in value or ".." in path.parts or "." in path.parts[1:]:
                    raise BomError("public paths must be normalized repository-relative POSIX paths")
    properties = root.get("properties", [])
    props = {item.get("name"): item.get("value") for item in properties if isinstance(item, dict)}
    required = {
        "repo-bom:completeness",
        "repo-bom:generation-digest",
        "repo-bom:lock-digest",
        "repo-bom:profile",
        "repo-bom:profile-digest",
        "repo-bom:producer-digest",
        "repo-bom:project-digest",
        "repo-bom:repository-id",
        "repo-bom:worktree-digest",
    }
    if not required <= props.keys() or props.get("repo-bom:profile") != PROFILE:
        raise BomError("invalid or incomplete Repository BOM profile")
    for name in required - {"repo-bom:completeness", "repo-bom:profile", "repo-bom:repository-id"}:
        if name.endswith("digest") and not _DIGEST.fullmatch(str(props[name])):
            raise BomError(f"invalid digest property: {name}")
    for key, value in _walk(document):
        if re.search(r"(secret|password|token|raw.?environment)", str(key), re.IGNORECASE):
            raise BomError("secret or raw-environment fields are forbidden")
        if key.endswith("path") and isinstance(value, str):
            path = PurePosixPath(value)
            if path.is_absolute() or "\\" in value or ".." in path.parts:
                raise BomError("public paths must be normalized repository-relative POSIX paths")
    canonical = canonical_bytes(document)
    if json.loads(canonical) != document:
        raise BomError("BOM is not JSON serializable")
    try:
        from cyclonedx.schema import OutputFormat, SchemaVersion, make_schemabased_validator

        validator = make_schemabased_validator(
            output_format=OutputFormat.JSON, schema_version=SchemaVersion.V1_7
        )
        errors = list(validator.iter_errors(document))
        if errors:
            raise BomError(f"CycloneDX 1.7 schema rejection: {errors[0].message}")
    except ImportError:
        pass
