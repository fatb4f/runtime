"""Bounded, immutable repository snapshots for workbook materialization."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from .models import validate_path


class RepositoryError(RuntimeError):
    pass


def _git(root: Path, arguments: list[str], *, text: bool = False) -> subprocess.CompletedProcess:
    process = subprocess.run(
        ["git", *arguments],
        cwd=root,
        capture_output=True,
        check=False,
        text=text,
        timeout=30,
    )
    if process.returncode != 0:
        stderr = process.stderr if text else process.stderr.decode(errors="replace")
        raise RepositoryError(stderr.strip() or "git repository snapshot command failed")
    return process


@dataclass(frozen=True)
class RepositorySnapshot:
    root: Path
    requested_revision: str
    resolved_revision: str

    @classmethod
    def resolve(cls, root: Path, revision: str) -> "RepositorySnapshot":
        repository_root = root.resolve(strict=True)
        process = _git(
            repository_root,
            ["rev-parse", "--verify", "--end-of-options", f"{revision}^{{commit}}"],
            text=True,
        )
        resolved = process.stdout.strip()
        if len(resolved) != 40 or any(character not in "0123456789abcdef" for character in resolved):
            raise RepositoryError("git did not resolve the requested revision to a commit SHA")
        return cls(
            root=repository_root,
            requested_revision=revision,
            resolved_revision=resolved,
        )

    def read_bytes(self, relative: str, *, max_bytes: int = 1_048_576) -> bytes:
        validate_path(relative)
        process = _git(self.root, ["show", f"{self.resolved_revision}:{relative}"])
        if len(process.stdout) > max_bytes:
            raise RepositoryError(f"repository file exceeds materialization limit: {relative}")
        return process.stdout

    def read_text(self, relative: str, *, max_bytes: int = 1_048_576) -> str:
        return self.read_bytes(relative, max_bytes=max_bytes).decode("utf-8")

    def is_file(self, relative: str) -> bool:
        validate_path(relative)
        process = subprocess.run(
            ["git", "cat-file", "-t", f"{self.resolved_revision}:{relative}"],
            cwd=self.root,
            capture_output=True,
            check=False,
            text=True,
            timeout=30,
        )
        return process.returncode == 0 and process.stdout.strip() == "blob"

    def list_files(self, prefix: str, *, max_files: int = 128) -> list[str]:
        validate_path(prefix)
        process = _git(
            self.root,
            ["ls-tree", "-r", "-z", "--name-only", self.resolved_revision, "--", prefix],
        )
        paths = [item.decode("utf-8") for item in process.stdout.split(b"\0") if item]
        if len(paths) > max_files:
            raise RepositoryError(f"repository snapshot contains too many files under {prefix}")
        for path in paths:
            validate_path(path)
        return paths

    def materialize_cue_package(self, prefix: str, destination: Path) -> Path:
        paths = [path for path in self.list_files(prefix) if path.endswith(".cue")]
        if not paths:
            raise RepositoryError(f"repository snapshot contains no CUE package at {prefix}")
        total_bytes = 0
        for relative in paths:
            content = self.read_bytes(relative)
            total_bytes += len(content)
            if total_bytes > 1_048_576:
                raise RepositoryError("CUE package exceeds materialization limit")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(content)
        return destination / prefix
