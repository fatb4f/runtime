from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from hypothesis import HealthCheck, given, settings, strategies as st

IdentityTerm = Literal[
    "content-identity",
    "occurrence-identity",
    "snapshot-occurrence-identity",
    "occurrence-metadata",
]

IDENTITY_PROPERTY_IDS = {
    "rename-content-preserved",
    "content-edit-content-changed",
    "unrelated-entry-preserved",
    "mode-change-content-preserved",
}

EXPECTED_RELATIONS: dict[str, tuple[set[IdentityTerm], set[IdentityTerm]]] = {
    "rename-content-preserved": (
        {"content-identity"},
        {"occurrence-identity", "snapshot-occurrence-identity"},
    ),
    "content-edit-content-changed": (
        {"occurrence-identity"},
        {"content-identity", "snapshot-occurrence-identity"},
    ),
    "unrelated-entry-preserved": (
        {"content-identity", "occurrence-identity"},
        {"snapshot-occurrence-identity"},
    ),
    "mode-change-content-preserved": (
        {"content-identity", "occurrence-identity"},
        {"occurrence-metadata", "snapshot-occurrence-identity"},
    ),
}


@dataclass(frozen=True)
class IdentityState:
    repository_id: str
    revision_format: str
    revision_hex: str
    path: str
    object_format: str
    object_hex: str
    mode: str
    kind: str


@dataclass(frozen=True)
class IdentityMutation:
    property_id: str
    before: IdentityState
    after: IdentityState
    preserves: frozenset[IdentityTerm]
    changes: frozenset[IdentityTerm]


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _identities(state: IdentityState) -> dict[IdentityTerm, object]:
    return {
        "content-identity": f"git-object:{state.object_format}:{state.object_hex}",
        "occurrence-identity": _digest(f"{state.repository_id}\0{state.path}"),
        "snapshot-occurrence-identity": _digest(
            f"{state.repository_id}\0{state.revision_format}\0{state.revision_hex}\0{state.path}"
        ),
        "occurrence-metadata": (state.mode, state.kind),
    }


_identifier = st.from_regex(r"[a-z][a-z0-9]{0,11}", fullmatch=True)
_path_segment = st.from_regex(r"[a-z0-9][a-z0-9._-]{0,11}", fullmatch=True)
_path = st.lists(_path_segment, min_size=1, max_size=4).map("/".join)
_object_hex = st.binary(min_size=20, max_size=20).map(bytes.hex)


@st.composite
def identity_mutations(draw: st.DrawFn) -> IdentityMutation:
    property_id = draw(st.sampled_from(sorted(IDENTITY_PROPERTY_IDS)))
    repository_id = "repo." + draw(_identifier)
    path = draw(_path)
    revision_a = draw(_object_hex)
    revision_b = draw(_object_hex.filter(lambda value: value != revision_a))
    object_a = draw(_object_hex)

    before = IdentityState(
        repository_id=repository_id,
        revision_format="sha1",
        revision_hex=revision_a,
        path=path,
        object_format="sha1",
        object_hex=object_a,
        mode="100644",
        kind="blob",
    )

    if property_id == "rename-content-preserved":
        after = IdentityState(
            **{
                **before.__dict__,
                "revision_hex": revision_b,
                "path": path + ".renamed",
            }
        )
    elif property_id == "content-edit-content-changed":
        object_b = draw(_object_hex.filter(lambda value: value != object_a))
        after = IdentityState(
            **{
                **before.__dict__,
                "revision_hex": revision_b,
                "object_hex": object_b,
            }
        )
    elif property_id == "unrelated-entry-preserved":
        after = IdentityState(**{**before.__dict__, "revision_hex": revision_b})
    elif property_id == "mode-change-content-preserved":
        after = IdentityState(
            **{
                **before.__dict__,
                "revision_hex": revision_b,
                "mode": "100755",
            }
        )
    else:  # pragma: no cover - sampled_from is closed above.
        raise AssertionError(f"unsupported property: {property_id}")

    preserves, changes = EXPECTED_RELATIONS[property_id]
    return IdentityMutation(
        property_id=property_id,
        before=before,
        after=after,
        preserves=frozenset(preserves),
        changes=frozenset(changes),
    )


def _repo_root() -> Path:
    configured = os.environ.get("CONTEXT_GRAPH_REPO_ROOT")
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def _property_catalog() -> dict[str, object]:
    source_root = _repo_root() / ".codex" / "context-model"
    with tempfile.TemporaryDirectory(prefix="git-identity-cue-") as temporary_directory:
        model_root = Path(temporary_directory) / "context-model"
        shutil.copytree(source_root, model_root)
        module_root = model_root / "cue.mod"
        module_file = module_root / "module.cue"
        if not module_file.exists():
            module_root.mkdir()
            module_file.write_text(
                'module: "example.com/contextmodel@v0"\n'
                'language: {version: "v0.18.0"}\n',
                encoding="utf-8",
            )
        completed = subprocess.run(
            [
                os.environ.get("CONTEXT_GRAPH_CUE", "cue"),
                "export",
                ".:contextmodel",
                "-e",
                "gitCommittedSnapshotPropertyCatalog",
                "--out",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "CUE_CACHE_DIR": str(Path(temporary_directory) / "cache")},
            cwd=model_root,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"CUE property export failed: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def test_cue_catalog_declares_identity_preservation_matrix() -> None:
    properties = _property_catalog()["properties"]
    assert IDENTITY_PROPERTY_IDS <= set(properties)
    for property_id, (preserves, changes) in EXPECTED_RELATIONS.items():
        property_spec = properties[property_id]
        assert set(property_spec["preserves"]) == preserves
        assert set(property_spec["changes"]) == changes


@settings(
    max_examples=64,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.filter_too_much],
)
@given(mutation=identity_mutations())
def test_identity_mutation_matrix(mutation: IdentityMutation) -> None:
    before = _identities(mutation.before)
    after = _identities(mutation.after)

    for term in mutation.preserves:
        assert before[term] == after[term], (
            mutation.property_id,
            term,
            mutation.before,
            mutation.after,
        )
    for term in mutation.changes:
        assert before[term] != after[term], (
            mutation.property_id,
            term,
            mutation.before,
            mutation.after,
        )


def _projection_members(revision_hex: str) -> dict[str, object]:
    source_root = _repo_root() / ".codex" / "context-model"
    with tempfile.TemporaryDirectory(prefix="git-identity-projection-") as temporary_directory:
        model_root = Path(temporary_directory) / "context-model"
        shutil.copytree(source_root, model_root)
        fixture = model_root / "identity_projection_fixture.cue"
        fixture.write_text(
            f'''package contextmodel

identityProjection: #GitCommittedSnapshotProjection & {{
    observation: {{
        schema: "kernel.git-committed-snapshot-observation.v0"
        repositoryID: "repo.fixture"
        requestedRevision: "{revision_hex}"
        resolvedRevision: {{format: "sha1", hex: "{revision_hex}"}}
        rootTree: {{format: "sha1", hex: "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb"}}
        occurrences: [{{
            path: "file.txt"
            mode: "100644"
            kind: "blob"
            objectID: {{format: "sha1", hex: "cccccccccccccccccccccccccccccccccccccccc"}}
            size: 1
        }}]
        hydrator: {{
            identity: "hydrator.context-git"
            digest: "sha256:1111111111111111111111111111111111111111111111111111111111111111"
        }}
    }}
    schemaDigest: "sha256:2222222222222222222222222222222222222222222222222222222222222222"
    policyDigest: "sha256:3333333333333333333333333333333333333333333333333333333333333333"
}}
''',
            encoding="utf-8",
        )
        completed = subprocess.run(
            [
                os.environ.get("CONTEXT_GRAPH_CUE", "cue"),
                "export",
                ".:contextmodel",
                "-e",
                "identityProjection.graph.members",
                "--out",
                "json",
            ],
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ, "CUE_CACHE_DIR": str(Path(temporary_directory) / "cache")},
            cwd=model_root,
        )
    if completed.returncode != 0:
        raise RuntimeError(f"CUE projection export failed: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


def test_projection_separates_stable_and_snapshot_occurrence_identity() -> None:
    revision_a = "a" * 40
    revision_b = "d" * 40
    members_a = _projection_members(revision_a)
    members_b = _projection_members(revision_b)

    expected_occurrence_id = _digest("repo.fixture\0file.txt")
    assert set(members_a) == {expected_occurrence_id}
    assert set(members_b) == {expected_occurrence_id}

    properties_a = members_a[expected_occurrence_id]["properties"]
    properties_b = members_b[expected_occurrence_id]["properties"]
    assert properties_a["occurrenceIdentity"] == expected_occurrence_id
    assert properties_b["occurrenceIdentity"] == expected_occurrence_id
    assert properties_a["snapshotOccurrenceIdentity"] != properties_b["snapshotOccurrenceIdentity"]
