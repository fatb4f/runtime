from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

import handoff.git as git_module
from handoff.git import GitError, begin_snapshot, finish_snapshot

from conftest import git


def test_stages_and_projects_rename_and_numstat(repository: Path) -> None:
    (repository / "tracked.txt").rename(repository / "renamed.txt")
    capture = begin_snapshot(repository)
    projection = finish_snapshot(capture)
    assert projection.root == str(repository.resolve())
    assert projection.staged[0].status == "R"
    assert projection.staged[0].source_path == "tracked.txt"
    assert projection.staged[0].path == "renamed.txt"
    assert projection.numstat[0].source_path == "tracked.txt"
    assert projection.numstat[0].path == "renamed.txt"
    assert git(repository, "diff", "--cached", "--name-status").startswith("R")


def test_add_modify_delete_are_stable(repository: Path) -> None:
    (repository / "tracked.txt").write_text("two\n", encoding="utf-8")
    (repository / "added.txt").write_text("new\n", encoding="utf-8")
    capture = begin_snapshot(repository)
    projection = finish_snapshot(capture)
    assert [(entry.status, entry.path) for entry in projection.staged] == [
        ("A", "added.txt"),
        ("M", "tracked.txt"),
    ]
    assert [(entry.added_lines, entry.deleted_lines) for entry in projection.numstat] == [
        (1, 0),
        (1, 1),
    ]


def test_post_capture_worktree_change_is_rejected(repository: Path) -> None:
    (repository / "tracked.txt").write_text("two\n", encoding="utf-8")
    capture = begin_snapshot(repository)
    (repository / "tracked.txt").write_text("three\n", encoding="utf-8")
    with pytest.raises(GitError, match="unstaged worktree"):
        finish_snapshot(capture)


def test_index_change_is_rejected(repository: Path) -> None:
    (repository / "tracked.txt").write_text("two\n", encoding="utf-8")
    capture = begin_snapshot(repository)
    (repository / "other.txt").write_text("other\n", encoding="utf-8")
    git(repository, "add", "other.txt")
    with pytest.raises(GitError, match="index changed"):
        finish_snapshot(capture)


def test_detached_head_is_null(repository: Path) -> None:
    git(repository, "checkout", "--detach", "-q")
    capture = begin_snapshot(repository)
    assert finish_snapshot(capture).branch is None


def test_binary_numstat_uses_null_counts(repository: Path) -> None:
    (repository / "binary.dat").write_bytes(b"\x00\x01\x02")
    projection = finish_snapshot(begin_snapshot(repository))
    binary = next(item for item in projection.numstat if item.path == "binary.dat")
    assert binary.binary is True
    assert binary.added_lines is None
    assert binary.deleted_lines is None


def test_rename_projection_ignores_user_disabled_detection(repository: Path) -> None:
    git(repository, "config", "diff.renames", "false")
    (repository / "tracked.txt").rename(repository / "renamed.txt")
    projection = finish_snapshot(begin_snapshot(repository))
    assert [(item.status, item.source_path, item.path) for item in projection.staged] == [
        ("R", "tracked.txt", "renamed.txt")
    ]
    assert [(item.source_path, item.path) for item in projection.numstat] == [
        ("tracked.txt", "renamed.txt")
    ]


def test_upstream_ahead_and_behind_are_projected(
    repository: Path, tmp_path: Path
) -> None:
    remote = tmp_path / "remote.git"
    remote.mkdir()
    git(remote, "init", "--bare", "-q")
    git(repository, "remote", "add", "origin", str(remote))
    branch = git(repository, "branch", "--show-current")
    git(repository, "push", "-qu", "origin", branch)

    (repository / "local.txt").write_text("local\n", encoding="utf-8")
    git(repository, "add", "local.txt")
    git(repository, "commit", "-qm", "local")

    peer = tmp_path / "peer"
    git(tmp_path, "clone", "-q", str(remote), str(peer))
    git(peer, "config", "user.email", "peer@example.invalid")
    git(peer, "config", "user.name", "Peer")
    (peer / "remote.txt").write_text("remote\n", encoding="utf-8")
    git(peer, "add", "remote.txt")
    git(peer, "commit", "-qm", "remote")
    git(peer, "push", "-q")
    git(repository, "fetch", "-q", "origin")

    capture = begin_snapshot(repository)
    assert capture.upstream == f"origin/{branch}"
    assert capture.ahead == 1
    assert capture.behind == 1


def test_merge_conflict_is_rejected_before_staging(repository: Path) -> None:
    branch = git(repository, "branch", "--show-current")
    git(repository, "checkout", "-qb", "side")
    (repository / "tracked.txt").write_text("side\n", encoding="utf-8")
    git(repository, "commit", "-qam", "side")
    git(repository, "checkout", "-q", branch)
    (repository / "tracked.txt").write_text("main\n", encoding="utf-8")
    git(repository, "commit", "-qam", "main")
    result = subprocess.run(
        ["git", "merge", "side"],
        cwd=repository,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    assert result.returncode != 0
    with pytest.raises(GitError, match="unmerged"):
        begin_snapshot(repository)


def test_unborn_head_is_rejected(tmp_path: Path) -> None:
    repository = tmp_path / "unborn"
    repository.mkdir()
    git(repository, "init", "-q")
    (repository / "new.txt").write_text("new\n", encoding="utf-8")
    with pytest.raises(GitError, match="HEAD"):
        begin_snapshot(repository)


def test_staging_failure_is_reported(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = git_module._run

    def fail_add(args: list[str], *, cwd: Path) -> bytes:
        if args == ["add", "-A"]:
            raise GitError("staging failed")
        return original(args, cwd=cwd)

    monkeypatch.setattr(git_module, "_run", fail_add)
    with pytest.raises(GitError, match="staging failed"):
        begin_snapshot(repository)
