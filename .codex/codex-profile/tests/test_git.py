from __future__ import annotations

from pathlib import Path

import pytest

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
