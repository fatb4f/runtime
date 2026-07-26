from __future__ import annotations

import copy
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal

from hypothesis import HealthCheck, given, settings, strategies as st

DocumentKind = Literal["observation", "projection"]

MUTATION_IDS = {
    "unknown-field-rejected",
    "duplicate-path-rejected",
    "unsorted-path-rejected",
    "incompatible-mode-rejected",
    "non-normalized-path-rejected",
    "noncanonical-revision-rejected",
    "malformed-object-id-rejected",
    "malformed-digest-rejected",
    "opaque-symlink-descendant-rejected",
    "opaque-submodule-descendant-rejected",
    "elevated-authority-rejected",
}

PRIMARY_PROPERTY_IDS = {
    "determinism",
    "rename-content-preserved",
    "content-edit-content-changed",
    "unrelated-entry-preserved",
    "mode-change-content-preserved",
    "symlink-not-traversed",
    "submodule-not-traversed",
    "revision-bound",
}

STRATEGY_KINDS = {"positive", "negative", "boundary", "metamorphic", "environment"}
_ORIGINAL_FAILURES: dict[str, dict[str, Any]] = {}


@dataclass(frozen=True)
class MutationCase:
    property_id: str
    definition: str
    document_kind: DocumentKind
    document: dict[str, Any]


def _repo_root() -> Path:
    configured = os.environ.get("CONTEXT_GRAPH_REPO_ROOT")
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[3]


@lru_cache(maxsize=1)
def _isolated_model_root() -> Path:
    source = _repo_root() / ".codex" / "context-model"
    temporary = Path(tempfile.mkdtemp(prefix="git-snapshot-fuzz-model-"))
    target = temporary / "context-model"
    shutil.copytree(source, target)
    module_file = target / "cue.mod" / "module.cue"
    if not module_file.exists():
        module_file.parent.mkdir()
        module_file.write_text(
            'module: "example.com/contextmodel@v0"\n'
            'language: {version: "v0.18.0"}\n',
            encoding="utf-8",
        )
    return target


def _run_cue(*arguments: str) -> subprocess.CompletedProcess[str]:
    model_root = _isolated_model_root()
    return subprocess.run(
        [os.environ.get("CONTEXT_GRAPH_CUE", "cue"), *arguments],
        cwd=model_root,
        env={
            **os.environ,
            "CUE_CACHE_DIR": str(model_root.parent / "cache"),
        },
        check=False,
        capture_output=True,
        text=True,
    )


def _cue_accepts(definition: str, document: dict[str, Any]) -> tuple[bool, str]:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", encoding="utf-8", delete=False
    ) as handle:
        json.dump(document, handle, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
        document_path = Path(handle.name)
    try:
        completed = _run_cue("vet", ".:contextmodel", str(document_path), "-d", definition)
    finally:
        document_path.unlink(missing_ok=True)
    return completed.returncode == 0, completed.stderr.strip()


@lru_cache(maxsize=1)
def _property_catalog() -> dict[str, Any]:
    completed = _run_cue(
        "export",
        ".:contextmodel",
        "-e",
        "gitCommittedSnapshotPropertyCatalog",
        "--out",
        "json",
    )
    if completed.returncode != 0:
        raise RuntimeError(f"CUE property catalog export failed: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


@lru_cache(maxsize=1)
def _typed_adapter_binary() -> Path:
    hydrator_root = _repo_root() / ".codex" / "context-hydrators" / "git"
    output = _isolated_model_root().parent / "context-git-hydrator"
    digest = "sha256:" + "42" * 32
    completed = subprocess.run(
        [
            "go",
            "build",
            "-trimpath",
            "-ldflags",
            "-X github.com/fatb4f/dotfiles/.codex/context-hydrators/git/internal/hydrator.BuildHydratorDigest="
            + digest,
            "-o",
            str(output),
            "./cmd/context-git-hydrator",
        ],
        cwd=hydrator_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"Go typed adapter build failed: {completed.stderr.strip()}")
    return output


def _typed_adapter_accepts(document: dict[str, Any]) -> tuple[bool, bytes, str]:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", encoding="utf-8", delete=False
    ) as handle:
        json.dump(document, handle, separators=(",", ":"), sort_keys=True)
        handle.write("\n")
        document_path = Path(handle.name)
    try:
        completed = subprocess.run(
            [
                str(_typed_adapter_binary()),
                "validate-observation",
                "--observation",
                str(document_path),
            ],
            check=False,
            capture_output=True,
        )
    finally:
        document_path.unlink(missing_ok=True)
    return (
        completed.returncode == 0,
        completed.stdout,
        completed.stderr.decode(errors="replace").strip(),
    )


def _typed_projection_accepts(document: dict[str, Any]) -> tuple[bool, str]:
    try:
        state = document["collected"]["state"]
        evidence = state["evidence"]
        authority = evidence["authority"]
        effective = state["effectiveAuthority"]
    except (KeyError, TypeError):
        return False, "projection collection authority state is incomplete"
    if authority not in {"none", "candidate"} or effective != authority:
        return False, "collection authority elevation requires admission"
    if document["collected"].get("admission") is not None:
        return False, "collection projection must not contain admission"
    try:
        graph = document["graph"]
        targets = {
            "module": set(graph["modules"]),
            "namespace": set(graph["namespaces"]),
            "member": set(graph["members"]),
            "evidence": set(graph["evidence"]),
        }
        for relationship in graph["relationships"].values():
            for endpoint in (relationship["subject"], relationship["object"]):
                if endpoint["id"] not in targets[endpoint["kind"]]:
                    return False, "projection relationship contains a broken reference"
        if state["evidenceID"] not in targets["evidence"]:
            return False, "collection state references unknown evidence"
        if state["snapshotID"] != graph["snapshotID"]:
            return False, "collection state references a different snapshot"
    except (KeyError, TypeError, AttributeError):
        return False, "projection graph reference structure is incomplete"
    return True, ""


def _cue_projection(observation: dict[str, Any]) -> dict[str, Any]:
    fixture_path = _isolated_model_root() / "fuzz_differential_projection.cue"
    fixture_path.write_text(
        "package contextmodel\n"
        "fuzzDifferentialProjection: #GitCommittedSnapshotProjection & {\n"
        f"observation: {json.dumps(observation, separators=(',', ':'))}\n"
        f"schemaDigest: \"sha256:{'4c' * 32}\"\n"
        f"policyDigest: \"sha256:{'5d' * 32}\"\n"
        "}\n",
        encoding="utf-8",
    )
    try:
        completed = _run_cue(
            "export",
            ".:contextmodel",
            "-e",
            "fuzzDifferentialProjection",
            "--out",
            "json",
        )
    finally:
        fixture_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        raise RuntimeError(f"CUE projection export failed: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


@lru_cache(maxsize=1)
def _hydrated_fixture_observation() -> tuple[dict[str, Any], bytes]:
    hydrator_root = _repo_root() / ".codex" / "context-hydrators" / "git"
    fixture_root = Path(tempfile.mkdtemp(prefix="git-hydrator-differential-"))
    completed = subprocess.run(
        [
            "go",
            "run",
            "./internal/testfixture/cmd/context-git-fixture",
            "--output",
            str(fixture_root),
        ],
        cwd=hydrator_root,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode != 0:
        raise RuntimeError(f"fixture adapter failed: {completed.stderr.strip()}")
    manifest = json.loads((fixture_root / "manifest.json").read_text(encoding="utf-8"))
    commit = manifest["repository"]["commits"]["F"]
    request = {
        "schema": "kernel.git-committed-snapshot-request.v0",
        "repositoryID": "repo.fixture",
        "path": "repository",
        "revision": commit,
    }
    request_path = fixture_root / "request.json"
    request_path.write_text(_canonical_json(request) + "\n", encoding="utf-8")
    completed_bytes = subprocess.run(
        [str(_typed_adapter_binary()), "committed", "--request", str(request_path)],
        cwd=fixture_root,
        check=False,
        capture_output=True,
    )
    if completed_bytes.returncode != 0:
        raise RuntimeError(
            "hydrator execution failed: "
            + completed_bytes.stderr.decode(errors="replace").strip()
        )
    return json.loads(completed_bytes.stdout), completed_bytes.stdout


def _canonical_json(document: dict[str, Any]) -> str:
    return json.dumps(document, separators=(",", ":"), sort_keys=True)


def _candidate_fixture(document: dict[str, Any]) -> dict[str, str]:
    document_json = _canonical_json(document)
    return {
        "documentJSON": document_json,
        "documentDigest": "sha256:" + hashlib.sha256(document_json.encode()).hexdigest(),
    }


def _write_assertion_candidate(case: MutationCase) -> Path:
    property_spec = _property_catalog()["properties"][case.property_id]
    original = _ORIGINAL_FAILURES.setdefault(case.property_id, copy.deepcopy(case.document))
    minimized_fixture = _candidate_fixture(case.document)
    candidate = {
        "schema": "kernel.git-committed-snapshot-assertion-candidate.v1",
        "proposedPropertyID": "candidate." + case.property_id,
        "targetSchemaDefinition": case.definition,
        "mutationClass": property_spec["mutation"],
        "documentKind": case.document_kind,
        "toolIdentities": [
            {
                "name": "cue",
                "version": _run_cue("version").stdout.splitlines()[0],
            },
            {"name": "python", "version": platform.python_version()},
            {"name": "hypothesis", "version": importlib.metadata.version("hypothesis")},
        ],
        "originalFixture": _candidate_fixture(original),
        "minimizedFixture": minimized_fixture,
        "preservedTerms": property_spec["preserves"],
        "changedTerms": property_spec["changes"],
        "affectedOracleSurfaces": ["cue-validation", "typed-validation"],
        "expected": "reject",
        "observed": "accept",
    }
    queue = {
        "schema": "kernel.git-committed-snapshot-regression-queue.v0",
        "authority": "none",
        "review": {"status": "pending", "reviewedBy": None, "promotion": None},
        "candidates": [candidate],
    }
    output_root = Path(
        os.environ.get(
            "CONTEXT_GIT_ASSERTION_CANDIDATE_DIR",
            str(Path(tempfile.gettempdir()) / "context-git-assertion-candidates"),
        )
    )
    output_root.mkdir(parents=True, exist_ok=True)
    digest = minimized_fixture["documentDigest"].removeprefix("sha256:")
    digest_path = output_root / f"{case.property_id}-{digest}.queue.json"
    latest_path = output_root / f"{case.property_id}.latest.queue.json"
    payload = json.dumps(queue, indent=2, sort_keys=True) + "\n"
    digest_path.write_text(payload, encoding="utf-8")
    latest_path.write_text(payload, encoding="utf-8")

    accepted, diagnostics = _cue_accepts("#GitCommittedSnapshotRegressionQueue", queue)
    if not accepted:
        raise AssertionError(f"regression queue envelope rejected: {diagnostics}")
    return latest_path


_identifier = st.from_regex(r"[a-z][a-z0-9]{0,7}", fullmatch=True)
_hex40 = st.binary(min_size=20, max_size=20).map(bytes.hex)


@st.composite
def valid_observations(draw: st.DrawFn) -> dict[str, Any]:
    directory = draw(_identifier)
    filename = draw(_identifier) + ".txt"
    commit = draw(_hex40)
    root_tree = draw(_hex40)
    directory_tree = draw(_hex40)
    blob = draw(_hex40)
    return {
        "schema": "kernel.git-committed-snapshot-observation.v0",
        "repositoryID": "repo." + draw(_identifier),
        "requestedRevision": commit,
        "resolvedRevision": {"format": "sha1", "hex": commit},
        "rootTree": {"format": "sha1", "hex": root_tree},
        "occurrences": [
            {
                "path": directory,
                "mode": "040000",
                "kind": "tree",
                "objectID": {"format": "sha1", "hex": directory_tree},
            },
            {
                "path": f"{directory}/{filename}",
                "mode": "100644",
                "kind": "blob",
                "objectID": {"format": "sha1", "hex": blob},
                "size": 1,
            },
        ],
        "hydrator": {
            "identity": "context-git-hydrator",
            "digest": "sha256:" + "1a" * 32,
        },
    }


@st.composite
def boundary_observations(draw: st.DrawFn) -> dict[str, Any]:
    observation = draw(valid_observations())
    observation["occurrences"][-1]["size"] = draw(st.sampled_from([0, 2**63 - 1]))
    return observation


def _identity_terms(observation: dict[str, Any], index: int = -1) -> dict[str, Any]:
    occurrence = observation["occurrences"][index]
    repository_id = observation["repositoryID"]
    revision = observation["resolvedRevision"]
    path = occurrence["path"]

    def digest(value: str) -> str:
        return "sha256:" + hashlib.sha256(value.encode()).hexdigest()

    return {
        "content-identity": "git-object:"
        + occurrence["objectID"]["format"]
        + ":"
        + occurrence["objectID"]["hex"],
        "occurrence-identity": digest(repository_id + "\0" + path),
        "snapshot-occurrence-identity": digest(
            repository_id
            + "\0"
            + revision["format"]
            + "\0"
            + revision["hex"]
            + "\0"
            + path
        ),
        "occurrence-metadata": (occurrence["mode"], occurrence["kind"]),
    }


@st.composite
def primary_invariant_cases(draw: st.DrawFn) -> tuple[str, dict[str, Any]]:
    return draw(st.sampled_from(sorted(PRIMARY_PROPERTY_IDS))), draw(valid_observations())


@lru_cache(maxsize=1)
def _valid_projection() -> dict[str, Any]:
    observation = {
        "schema": "kernel.git-committed-snapshot-observation.v0",
        "repositoryID": "repo.fixture",
        "requestedRevision": "a" * 40,
        "resolvedRevision": {"format": "sha1", "hex": "a" * 40},
        "rootTree": {"format": "sha1", "hex": "b" * 40},
        "occurrences": [
            {
                "path": "file.txt",
                "mode": "100644",
                "kind": "blob",
                "objectID": {"format": "sha1", "hex": "c" * 40},
                "size": 1,
            }
        ],
        "hydrator": {
            "identity": "context-git-hydrator",
            "digest": "sha256:" + "12" * 32,
        },
    }
    fixture_path = _isolated_model_root() / "fuzz_projection_fixture.cue"
    fixture_path.write_text(
        "package contextmodel\n"
        "fuzzProjection: #GitCommittedSnapshotProjection & {\n"
        f"observation: {json.dumps(observation, separators=(',', ':'))}\n"
        f"schemaDigest: \"sha256:{'2a' * 32}\"\n"
        f"policyDigest: \"sha256:{'3b' * 32}\"\n"
        "}\n",
        encoding="utf-8",
    )
    completed = _run_cue(
        "export", ".:contextmodel", "-e", "fuzzProjection", "--out", "json"
    )
    fixture_path.unlink(missing_ok=True)
    if completed.returncode != 0:
        raise RuntimeError(f"CUE projection export failed: {completed.stderr.strip()}")
    return json.loads(completed.stdout)


@st.composite
def invalid_snapshot_mutations(draw: st.DrawFn) -> MutationCase:
    property_id = draw(st.sampled_from(sorted(MUTATION_IDS)))
    if property_id == "elevated-authority-rejected":
        document = copy.deepcopy(_valid_projection())
        document["collected"]["state"]["effectiveAuthority"] = "controller"
        return MutationCase(property_id, "#GitCommittedSnapshotProjection", "projection", document)

    document = draw(valid_observations())
    occurrences = document["occurrences"]
    if property_id == "unknown-field-rejected":
        document["unknown"] = True
    elif property_id == "duplicate-path-rejected":
        occurrences.append(copy.deepcopy(occurrences[-1]))
        occurrences.sort(key=lambda item: item["path"])
    elif property_id == "unsorted-path-rejected":
        occurrences.reverse()
    elif property_id == "incompatible-mode-rejected":
        occurrences[-1]["mode"] = "160000"
    elif property_id == "non-normalized-path-rejected":
        occurrences[-1]["path"] = occurrences[0]["path"] + "/../escape"
    elif property_id == "noncanonical-revision-rejected":
        document["requestedRevision"] = "main"
    elif property_id == "malformed-object-id-rejected":
        occurrences[-1]["objectID"]["hex"] = "not-hex"
    elif property_id == "malformed-digest-rejected":
        document["hydrator"]["digest"] = "sha256:short"
    elif property_id == "opaque-symlink-descendant-rejected":
        occurrences[:] = [
            {
                "path": "link",
                "mode": "120000",
                "kind": "symlink",
                "objectID": {"format": "sha1", "hex": "d" * 40},
                "size": 8,
            },
            {
                "path": "link/child",
                "mode": "100644",
                "kind": "blob",
                "objectID": {"format": "sha1", "hex": "e" * 40},
                "size": 1,
            },
        ]
    elif property_id == "opaque-submodule-descendant-rejected":
        occurrences[:] = [
            {
                "path": "vendor",
                "mode": "160000",
                "kind": "submodule",
                "objectID": {"format": "sha1", "hex": "d" * 40},
            },
            {
                "path": "vendor/child",
                "mode": "100644",
                "kind": "blob",
                "objectID": {"format": "sha1", "hex": "e" * 40},
                "size": 1,
            },
        ]
    else:  # pragma: no cover
        raise AssertionError(property_id)
    return MutationCase(property_id, "#GitCommittedSnapshotObservation", "observation", document)


def test_fuzz_property_manifest_matches_mutation_schema() -> None:
    completed = _run_cue(
        "export",
        ".:contextmodel",
        "-e",
        "gitCommittedSnapshotFuzzProperties",
        "--out",
        "json",
    )
    assert completed.returncode == 0, completed.stderr
    assert set(json.loads(completed.stdout)) == MUTATION_IDS


def test_assertion_catalog_covers_all_invariants_and_strategy_kinds() -> None:
    properties = _property_catalog()["properties"]
    assert set(properties) == PRIMARY_PROPERTY_IDS | MUTATION_IDS
    for property_id, property_spec in properties.items():
        assert property_spec["id"] == property_id
        assert property_spec["expected"] in {"accept", "reject"}
        assert set(property_spec["strategies"]) == STRATEGY_KINDS
        assert all(property_spec["strategies"][kind] for kind in STRATEGY_KINDS)
        assert property_spec["strategies"]["metamorphic"] == [
            "property-" + property_id
        ]


def test_backward_candidate_is_persisted_in_review_gated_queue(
    tmp_path: Path, monkeypatch: Any
) -> None:
    monkeypatch.setenv("CONTEXT_GIT_ASSERTION_CANDIDATE_DIR", str(tmp_path))
    case = MutationCase(
        property_id="elevated-authority-rejected",
        definition="#GitCommittedSnapshotProjection",
        document_kind="projection",
        document=_valid_projection(),
    )
    queue_path = _write_assertion_candidate(case)
    queue = json.loads(queue_path.read_text(encoding="utf-8"))
    assert queue["authority"] == "none"
    assert queue["review"] == {
        "status": "pending",
        "reviewedBy": None,
        "promotion": None,
    }
    candidate = queue["candidates"][0]
    assert candidate["originalFixture"]
    assert candidate["minimizedFixture"]
    assert candidate["toolIdentities"]
    assert candidate["affectedOracleSurfaces"]


@settings(max_examples=24, deadline=None, derandomize=True)
@given(observation=valid_observations())
def test_generated_valid_observations_are_admitted(observation: dict[str, Any]) -> None:
    cue_accepted, cue_diagnostics = _cue_accepts(
        "#GitCommittedSnapshotObservation", observation
    )
    typed_accepted, normalized, typed_diagnostics = _typed_adapter_accepts(observation)
    assert cue_accepted == typed_accepted, (cue_diagnostics, typed_diagnostics)
    assert cue_accepted, cue_diagnostics
    assert _canonical_json(json.loads(normalized)) == _canonical_json(observation)


@settings(max_examples=16, deadline=None, derandomize=True)
@given(observation=boundary_observations())
def test_schema_boundary_values_are_admitted_by_both_oracles(
    observation: dict[str, Any],
) -> None:
    cue_accepted, cue_diagnostics = _cue_accepts(
        "#GitCommittedSnapshotObservation", observation
    )
    typed_accepted, _, typed_diagnostics = _typed_adapter_accepts(observation)
    assert cue_accepted == typed_accepted, (cue_diagnostics, typed_diagnostics)
    assert cue_accepted, cue_diagnostics


def test_hydrator_projection_and_serialization_oracles_agree() -> None:
    observation, hydrated_bytes = _hydrated_fixture_observation()
    cue_accepted, cue_diagnostics = _cue_accepts(
        "#GitCommittedSnapshotObservation", observation
    )
    typed_accepted, typed_bytes, typed_diagnostics = _typed_adapter_accepts(observation)
    assert cue_accepted == typed_accepted, (cue_diagnostics, typed_diagnostics)
    assert cue_accepted, cue_diagnostics
    assert hydrated_bytes == typed_bytes

    projection = _cue_projection(observation)
    projection_accepted, projection_diagnostics = _typed_projection_accepts(projection)
    assert projection_accepted, projection_diagnostics
    assert json.loads(_canonical_json(projection)) == projection


@settings(max_examples=12, deadline=None, derandomize=True)
@given(observation=valid_observations())
def test_missing_required_fields_are_rejected_by_both_oracles(
    observation: dict[str, Any],
) -> None:
    del observation["resolvedRevision"]
    cue_accepted, cue_diagnostics = _cue_accepts(
        "#GitCommittedSnapshotObservation", observation
    )
    typed_accepted, _, typed_diagnostics = _typed_adapter_accepts(observation)
    assert cue_accepted == typed_accepted, (cue_diagnostics, typed_diagnostics)
    assert not cue_accepted


def test_broken_projection_references_are_rejected_by_both_oracles() -> None:
    observation, _ = _hydrated_fixture_observation()
    projection = _cue_projection(observation)
    relationship = next(iter(projection["graph"]["relationships"].values()))
    relationship["object"]["id"] = "sha256:" + "0" * 64
    cue_accepted, cue_diagnostics = _cue_accepts(
        "#GitCommittedSnapshotProjection", projection
    )
    typed_accepted, typed_diagnostics = _typed_projection_accepts(projection)
    assert cue_accepted == typed_accepted, (cue_diagnostics, typed_diagnostics)
    assert not cue_accepted


@settings(
    max_examples=96,
    deadline=None,
    derandomize=True,
    suppress_health_check=[HealthCheck.filter_too_much],
)
@given(case=invalid_snapshot_mutations())
def test_backward_fuzzer_rejects_invariant_mutations(case: MutationCase) -> None:
    cue_accepted, cue_diagnostics = _cue_accepts(case.definition, case.document)
    if case.document_kind == "observation":
        typed_accepted, _, typed_diagnostics = _typed_adapter_accepts(case.document)
    else:
        typed_accepted, typed_diagnostics = _typed_projection_accepts(case.document)
    if cue_accepted != typed_accepted:
        raise AssertionError(
            f"oracle disagreement for {case.property_id}: "
            f"CUE={cue_accepted} ({cue_diagnostics}); "
            f"typed={typed_accepted} ({typed_diagnostics})"
        )
    if cue_accepted:
        candidate_path = _write_assertion_candidate(case)
        raise AssertionError(
            f"CUE accepted {case.property_id}; minimized assertion candidate: {candidate_path}"
        )
    assert cue_diagnostics


@settings(max_examples=40, deadline=None, derandomize=True)
@given(case=primary_invariant_cases())
def test_primary_invariants_have_metamorphic_hypothesis_cases(
    case: tuple[str, dict[str, Any]],
) -> None:
    property_id, before = case
    after = copy.deepcopy(before)
    before_terms = _identity_terms(before)
    after_identity_index = -1

    if property_id == "determinism":
        previous = os.environ.get("TZ")
        os.environ["TZ"] = "Pacific/Kiritimati"
        try:
            assert _canonical_json(before) == _canonical_json(after)
        finally:
            if previous is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = previous
        return
    if property_id == "rename-content-preserved":
        after["occurrences"][-1]["path"] += ".renamed"
    elif property_id == "content-edit-content-changed":
        current = after["occurrences"][-1]["objectID"]["hex"]
        after["occurrences"][-1]["objectID"]["hex"] = (
            "0" * len(current) if current != "0" * len(current) else "1" * len(current)
        )
    elif property_id == "unrelated-entry-preserved":
        after["occurrences"].append(
            {
                "path": "zz-unrelated",
                "mode": "100644",
                "kind": "blob",
                "objectID": {"format": "sha1", "hex": "f" * 40},
                "size": 0,
            }
        )
        after_identity_index = -2
    elif property_id == "mode-change-content-preserved":
        after["occurrences"][-1]["mode"] = "100755"
    elif property_id in {"symlink-not-traversed", "submodule-not-traversed"}:
        kind = "symlink" if property_id.startswith("symlink") else "submodule"
        mode = "120000" if kind == "symlink" else "160000"
        opaque = {
            "path": "opaque",
            "mode": mode,
            "kind": kind,
            "objectID": {"format": "sha1", "hex": "d" * 40},
        }
        if kind == "symlink":
            opaque["size"] = 0
        after["occurrences"] = [opaque]
        accepted, diagnostics = _cue_accepts("#GitCommittedSnapshotObservation", after)
        assert accepted, diagnostics
        after["occurrences"].append(
            {
                "path": "opaque/child",
                "mode": "100644",
                "kind": "blob",
                "objectID": {"format": "sha1", "hex": "e" * 40},
                "size": 0,
            }
        )
        accepted, _ = _cue_accepts("#GitCommittedSnapshotObservation", after)
        assert not accepted
        return
    elif property_id == "revision-bound":
        after["requestedRevision"] = "main"
        accepted, _ = _cue_accepts("#GitCommittedSnapshotObservation", after)
        assert not accepted
        return
    else:  # pragma: no cover
        raise AssertionError(property_id)

    after["resolvedRevision"]["hex"] = (
        "e" * 40
        if after["resolvedRevision"]["hex"] != "e" * 40
        else "f" * 40
    )
    after["requestedRevision"] = after["resolvedRevision"]["hex"]
    after_terms = _identity_terms(after, after_identity_index)
    property_spec = _property_catalog()["properties"][property_id]
    for term in property_spec["preserves"]:
        assert before_terms[term] == after_terms[term]
    for term in property_spec["changes"]:
        assert before_terms[term] != after_terms[term]
    accepted, diagnostics = _cue_accepts("#GitCommittedSnapshotObservation", after)
    assert accepted, diagnostics
