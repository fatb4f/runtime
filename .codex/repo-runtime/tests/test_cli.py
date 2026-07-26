from __future__ import annotations

from pathlib import Path

from repo_bom.cli import main

from test_bom import project


def test_generate_validate_check_and_stale_exit(tmp_path: Path) -> None:
    repository = project(tmp_path / "repository")
    output = tmp_path / "repository.cdx.json"
    assert main(["generate", "--repository", str(repository), "--output", str(output)]) == 0
    assert main(["validate", str(output)]) == 0
    assert main(["check", "--repository", str(repository), "--expected", str(output)]) == 0
    (repository / "new.txt").write_text("changed")
    assert main(["check", "--repository", str(repository), "--expected", str(output)]) == 1

