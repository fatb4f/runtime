from __future__ import annotations

import copy
import json
import subprocess
from pathlib import Path

import pytest

from repo_bom.bom import assemble
from repo_intel import discover

from test_bom import project


CONTRACTS = Path(__file__).parents[1] / "contracts"


def cue_accepts(document: dict[str, object], destination: Path) -> tuple[bool, str]:
    destination.write_text(json.dumps(document))
    completed = subprocess.run(
        ["cue", "vet", "model.cue", str(destination), "-d", "#RepositoryBOM"],
        cwd=CONTRACTS,
        check=False,
        capture_output=True,
        text=True,
    )
    return completed.returncode == 0, completed.stderr


def test_generated_bom_is_admitted_by_cue(tmp_path: Path) -> None:
    document = assemble(discover(project(tmp_path / "repository", workspace=True)))
    accepted, diagnostics = cue_accepts(document, tmp_path / "positive.json")
    assert accepted, diagnostics


@pytest.mark.parametrize("mutation", ["duplicate", "dangling", "path", "profile", "raw-environment"])
def test_cue_rejects_contract_mutations(tmp_path: Path, mutation: str) -> None:
    document = assemble(discover(project(tmp_path / "repository")))
    invalid = copy.deepcopy(document)
    if mutation == "duplicate":
        invalid["components"].append(copy.deepcopy(invalid["components"][0]))
    elif mutation == "dangling":
        invalid["dependencies"][0]["dependsOn"].append("urn:repo-bom:module:" + "f" * 64)
    elif mutation == "path":
        invalid["components"][0]["properties"].append(
            {"name": "repo-bom:realization-path", "value": "/private/repository"}
        )
    elif mutation == "profile":
        properties = invalid["metadata"]["component"]["properties"]
        next(item for item in properties if item["name"] == "repo-bom:profile")["value"] = "other"
    else:
        invalid["rawEnvironment"] = {"TOKEN": "forbidden"}
    accepted, _ = cue_accepts(invalid, tmp_path / "negative.json")
    assert not accepted
