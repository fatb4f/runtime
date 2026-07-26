from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


class DiscoveryError(RuntimeError):
    pass


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def canonical_bytes(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n").encode()


def _run(args: list[str], cwd: Path, *, text: bool = True) -> str | bytes:
    completed = subprocess.run(
        args, cwd=cwd, check=False, capture_output=True, text=text, stdin=subprocess.DEVNULL
    )
    if completed.returncode:
        stderr = completed.stderr if text else completed.stderr.decode(errors="replace")
        raise DiscoveryError(f"{' '.join(args)} failed: {stderr.strip()}")
    return completed.stdout


def _safe_locator(value: str) -> str:
    value = value.strip()
    if "://" not in value and ":" in value and not value.startswith("/"):
        host, path = value.split(":", 1)
        value = f"ssh://{host}/{path}"
    parts = urlsplit(value)
    if parts.scheme:
        host = parts.hostname or ""
        if parts.port:
            host += f":{parts.port}"
        path = parts.path.removesuffix(".git").rstrip("/")
        return urlunsplit((parts.scheme.lower(), host.lower(), path, "", ""))
    return value.removesuffix(".git").rstrip("/")


@dataclass(frozen=True)
class RepositoryObservation:
    root: Path
    repository_id: str
    locator: str | None
    revision: str
    tree: str
    clean: bool
    worktree_digest: str


@dataclass(frozen=True)
class UvObservation:
    project_path: str
    project_digest: str
    lock_digest: str
    tree: dict[str, Any]


@dataclass(frozen=True)
class Discovery:
    repository: RepositoryObservation
    uv: UvObservation


def discover(repository: Path) -> Discovery:
    requested = repository.resolve()
    root = Path(str(_run(["git", "rev-parse", "--show-toplevel"], requested)).strip()).resolve()
    locator_raw = subprocess.run(
        ["git", "config", "--get", "remote.origin.url"],
        cwd=root,
        check=False,
        capture_output=True,
        text=True,
        stdin=subprocess.DEVNULL,
    ).stdout.strip()
    locator = _safe_locator(locator_raw) if locator_raw else None
    identity_seed = locator or "content:" + str(_run(["git", "rev-parse", "HEAD^{tree}"], root)).strip()
    repository_id = "repository:" + hashlib.sha256(identity_seed.encode()).hexdigest()
    revision = str(_run(["git", "rev-parse", "HEAD"], root)).strip()
    tree = str(_run(["git", "rev-parse", "HEAD^{tree}"], root)).strip()
    status = bytes(_run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], root, text=False))

    project = root / "pyproject.toml"
    lock = root / "uv.lock"
    if not project.is_file() or not lock.is_file():
        raise DiscoveryError("a pyproject.toml and uv.lock are required at the Git root")
    with project.open("rb") as stream:
        tomllib.load(stream)

    _run(["uv", "lock", "--check", "--project", os.fspath(root)], root)
    tree_output = str(
        _run(
            [
                "uv",
                "tree",
                "--format",
                "json",
                "--locked",
                "--preview-features",
                "json-output",
                "--project",
                os.fspath(root),
            ],
            root,
        )
    )
    try:
        uv_tree = json.loads(tree_output[tree_output.index("{") :])
    except (ValueError, json.JSONDecodeError) as error:
        raise DiscoveryError(f"uv returned invalid JSON: {error}") from error

    return Discovery(
        repository=RepositoryObservation(
            root=root,
            repository_id=repository_id,
            locator=locator,
            revision=revision,
            tree=tree,
            clean=not status,
            worktree_digest=digest_bytes(status),
        ),
        uv=UvObservation(
            project_path="pyproject.toml",
            project_digest=digest_bytes(project.read_bytes()),
            lock_digest=digest_bytes(lock.read_bytes()),
            tree=uv_tree,
        ),
    )
