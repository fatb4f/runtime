from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings, strategies as st

from repo_bom.bom import BomError, assemble, canonical_bytes, validate
from repo_intel import DiscoveryError, discover


def run(args: list[str], cwd: Path) -> None:
    environment = {
        **os.environ,
        "GIT_AUTHOR_NAME": "Repository BOM Test",
        "GIT_AUTHOR_EMAIL": "repo-bom@example.invalid",
        "GIT_COMMITTER_NAME": "Repository BOM Test",
        "GIT_COMMITTER_EMAIL": "repo-bom@example.invalid",
        "GIT_AUTHOR_DATE": "2026-01-01T00:00:00Z",
        "GIT_COMMITTER_DATE": "2026-01-01T00:00:00Z",
    }
    subprocess.run(args, cwd=cwd, env=environment, check=True, capture_output=True)


def project(root: Path, *, workspace: bool = False) -> Path:
    root.mkdir()
    if workspace:
        (root / "packages" / "member").mkdir(parents=True)
        (root / "pyproject.toml").write_text(
            """[project]
name = "generic-root"
version = "1.0.0"
requires-python = ">=3.12"
dependencies = ["generic-member"]

[tool.uv.sources]
generic-member = { workspace = true }

[tool.uv.workspace]
members = ["packages/*"]
"""
        )
        (root / "packages" / "member" / "pyproject.toml").write_text(
            """[project]
name = "generic-member"
version = "2.0.0"
requires-python = ">=3.12"
"""
        )
    else:
        (root / "pyproject.toml").write_text(
            """[project]
name = "generic-project"
version = "1.0.0"
requires-python = ">=3.12"
"""
        )
    run(["uv", "lock", "--project", os.fspath(root)], root)
    run(["git", "init", "-q"], root)
    run(["git", "remote", "add", "origin", "https://example.invalid/generic/project.git"], root)
    run(["git", "add", "."], root)
    run(["git", "commit", "-qm", "fixture"], root)
    return root


def non_registry_project(root: Path) -> Path:
    external = root.parent / "external-lib"
    external.mkdir()
    (external / "pyproject.toml").write_text(
        """[project]
name = "external-lib"
version = "3.0.0"
requires-python = ">=3.12"
"""
    )
    root.mkdir()
    (root / "pyproject.toml").write_text(
        """[project]
name = "generic-project"
version = "1.0.0"
requires-python = ">=3.12"
dependencies = ["external-lib"]

[tool.uv.sources]
external-lib = { path = "../external-lib" }
"""
    )
    run(["uv", "lock", "--project", os.fspath(root)], root)
    run(["git", "init", "-q"], root)
    run(["git", "remote", "add", "origin", "https://example.invalid/generic/project.git"], root)
    run(["git", "add", "."], root)
    run(["git", "commit", "-qm", "fixture"], root)
    return root


@pytest.mark.parametrize("workspace", [False, True])
def test_generic_uv_projects_generate_schema_valid_boms(tmp_path: Path, workspace: bool) -> None:
    root = project(tmp_path / "repository", workspace=workspace)
    document = assemble(discover(root))
    validate(document)
    classifications = {
        property["value"]
        for component in document["components"]
        for property in component.get("properties", [])
        if property["name"] == "repo-bom:classification"
    }
    assert "first-party" in classifications
    assert json.loads(canonical_bytes(document)) == document


def test_relocated_checkout_is_byte_equivalent(tmp_path: Path) -> None:
    first = project(tmp_path / "first", workspace=True)
    second = tmp_path / "second"
    shutil.copytree(first, second)
    assert canonical_bytes(assemble(discover(first))) == canonical_bytes(assemble(discover(second)))


def test_non_registry_dependency_is_normalized_without_public_path(tmp_path: Path) -> None:
    document = assemble(discover(non_registry_project(tmp_path / "repository")))
    external = next(component for component in document["components"] if component["name"] == "external-lib")
    assert {
        property["name"]: property["value"] for property in external["properties"]
    }["repo-bom:classification"] == "external"
    assert str(tmp_path) not in canonical_bytes(document).decode()


def test_state_and_input_changes_change_generation(tmp_path: Path) -> None:
    root = project(tmp_path / "repository")
    original = assemble(discover(root))
    (root / "unclassified.txt").write_text("state change")
    changed = assemble(discover(root))
    assert generation(original) != generation(changed)
    assert [component["bom-ref"] for component in original["components"]] == [
        component["bom-ref"] for component in changed["components"]
    ]


def test_project_and_lock_change_generation_inputs(tmp_path: Path) -> None:
    root = project(tmp_path / "repository")
    original = assemble(discover(root))
    project_file = root / "pyproject.toml"
    project_file.write_text(project_file.read_text().replace('version = "1.0.0"', 'version = "1.0.1"'))
    run(["uv", "lock", "--project", os.fspath(root)], root)
    changed = assemble(discover(root))
    original_properties = {
        item["name"]: item["value"] for item in original["metadata"]["component"]["properties"]
    }
    changed_properties = {
        item["name"]: item["value"] for item in changed["metadata"]["component"]["properties"]
    }
    assert changed_properties["repo-bom:project-digest"] != original_properties["repo-bom:project-digest"]
    assert changed_properties["repo-bom:lock-digest"] != original_properties["repo-bom:lock-digest"]
    assert generation(changed) != generation(original)


@given(reverse_resolution=st.booleans(), reverse_members=st.booleans())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_uv_observation_order_does_not_change_bytes(
    tmp_path: Path, reverse_resolution: bool, reverse_members: bool
) -> None:
    root = tmp_path / "repository"
    if not root.exists():
        project(root, workspace=True)
    observation = discover(root)
    changed_tree = copy.deepcopy(observation.uv.tree)
    if reverse_resolution:
        changed_tree["resolution"] = dict(reversed(list(changed_tree["resolution"].items())))
    if reverse_members:
        changed_tree["members"].reverse()
    changed = replace(observation, uv=replace(observation.uv, tree=changed_tree))
    assert canonical_bytes(assemble(observation)) == canonical_bytes(assemble(changed))


def test_profile_and_producer_change_generation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import repo_bom.bom as bom_module

    observation = discover(project(tmp_path / "repository"))
    original = generation(assemble(observation))
    monkeypatch.setattr(
        bom_module, "PRODUCER", {"name": "repository-bom-runtime", "version": "0.2.0"}
    )
    assert generation(assemble(observation)) != original
    monkeypatch.undo()
    monkeypatch.setattr(bom_module, "PROFILE", "repository-bom.cyclonedx-1.7.v1")
    assert generation(assemble(observation)) != original


def generation(document: dict[str, object]) -> str:
    properties = document["metadata"]["component"]["properties"]  # type: ignore[index]
    return next(
        item["value"] for item in properties if item["name"] == "repo-bom:generation-digest"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "duplicate",
        "dangling",
        "absolute-path",
        "invalid-profile",
        "secret",
    ],
)
def test_invalid_public_boms_fail_closed(tmp_path: Path, mutation: str) -> None:
    document = assemble(discover(project(tmp_path / "repository")))
    invalid = copy.deepcopy(document)
    if mutation == "duplicate":
        invalid["components"].append(copy.deepcopy(invalid["components"][0]))
    elif mutation == "dangling":
        invalid["dependencies"][0]["dependsOn"].append("urn:repo-bom:module:" + "f" * 64)
        invalid["dependencies"][0]["dependsOn"].sort()
    elif mutation == "absolute-path":
        properties = invalid["components"][0]["properties"]
        properties.append({"name": "repo-bom:realization-path", "value": "/private/repository"})
        properties.sort(key=lambda item: item["name"])
    elif mutation == "invalid-profile":
        properties = invalid["metadata"]["component"]["properties"]
        next(item for item in properties if item["name"] == "repo-bom:profile")["value"] = "other"
    else:
        invalid["rawEnvironment"] = {"SECRET_TOKEN": "not-published"}
    with pytest.raises(BomError):
        validate(invalid)


def test_stale_lock_fails_closed(tmp_path: Path) -> None:
    root = project(tmp_path / "repository")
    (root / "pyproject.toml").write_text(
        (root / "pyproject.toml").read_text().replace('dependencies = []', 'dependencies = ["idna"]')
        if "dependencies = []" in (root / "pyproject.toml").read_text()
        else (root / "pyproject.toml").read_text() + '\ndependencies = ["idna"]\n'
    )
    with pytest.raises(DiscoveryError):
        discover(root)


def test_portable_source_has_no_repository_specific_vocabulary() -> None:
    text = "\n".join(
        path.read_text()
        for path in (Path(__file__).parents[1] / "src").rglob("*.py")
    ).lower()
    for forbidden in ("fatb4f/dotfiles", "chezmoi", "neovim", "wezterm"):
        assert forbidden not in text
