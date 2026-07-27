from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from .model import NumstatEntry, RepositoryProjection, StagedEntry

_OID = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
_ALLOWED_MODES = {"000000", "100644", "100755", "120000"}


class GitError(RuntimeError):
    pass


@dataclass(frozen=True)
class _RawEntry:
    status: str
    path: str
    source_path: str | None


@dataclass(frozen=True)
class GitCapture:
    root: Path
    head: str
    branch: str | None
    upstream: str | None
    ahead: int | None
    behind: int | None
    index_tree_before: str
    staged: tuple[StagedEntry, ...]
    raw: tuple[_RawEntry, ...]
    numstat: tuple[NumstatEntry, ...]


def _run(args: list[str], *, cwd: Path) -> bytes:
    env = os.environ.copy()
    env["LC_ALL"] = "C"
    result = subprocess.run(
        ["git", *args],
        cwd=cwd,
        env=env,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        detail = result.stderr.decode("utf-8", "replace").strip() or "Git command failed"
        raise GitError(f"{' '.join(['git', *args])}: {detail}")
    return result.stdout


def resolve_repository(path: Path) -> Path:
    value = _run(["rev-parse", "--show-toplevel"], cwd=path).decode("utf-8", "strict").strip()
    root = Path(value).resolve()
    if not root.is_dir():
        raise GitError(f"resolved repository root is not a directory: {root}")
    return root


def resolve_metadata_repository(path: Path) -> Path:
    return resolve_repository(path.resolve())


def begin_snapshot(repository: Path) -> GitCapture:
    root = resolve_repository(repository)
    _run(["add", "-A"], cwd=root)
    tree_before = _oid_text(_run(["write-tree"], cwd=root), "index tree")
    status_data = _run(
        [
            "-c",
            "status.renames=true",
            "status",
            "--porcelain=v2",
            "-z",
            "--branch",
            "--ahead-behind",
        ],
        cwd=root,
    )
    headers, staged = _parse_status(status_data, require_headers=True)
    head = headers.get("branch.oid")
    if head is None or head == "(initial)" or not _OID.fullmatch(head):
        raise GitError("HEAD cannot be resolved from porcelain")
    head_verified = _oid_text(_run(["rev-parse", "--verify", "HEAD"], cwd=root), "HEAD")
    if head != head_verified:
        raise GitError("porcelain HEAD disagrees with rev-parse")
    branch_header = headers.get("branch.head")
    if branch_header is None:
        raise GitError("porcelain omitted branch.head")
    branch = None if branch_header == "(detached)" else branch_header
    upstream = headers.get("branch.upstream")
    ahead: int | None = None
    behind: int | None = None
    if "branch.ab" in headers:
        match = re.fullmatch(r"\+([0-9]+) -([0-9]+)", headers["branch.ab"])
        if not match:
            raise GitError("malformed branch.ab header")
        ahead, behind = int(match.group(1)), int(match.group(2))
    elif upstream is not None:
        raise GitError("upstream exists without ahead/behind data")

    raw_data = _run(
        [
            "-c",
            "diff.renames=true",
            "-c",
            "diff.external=",
            "diff",
            "--cached",
            "--raw",
            "-z",
            "--find-renames",
            "--no-abbrev",
            "--no-ext-diff",
            "--no-textconv",
        ],
        cwd=root,
    )
    numstat_data = _run(
        [
            "-c",
            "core.quotePath=false",
            "-c",
            "diff.external=",
            "diff",
            "--cached",
            "--numstat",
            "-z",
            "--no-ext-diff",
            "--no-textconv",
        ],
        cwd=root,
    )
    raw = _parse_raw(raw_data)
    numstat = _parse_numstat(numstat_data)
    _cross_check(staged, raw, numstat)
    return GitCapture(
        root=root,
        head=head,
        branch=branch,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        index_tree_before=tree_before,
        staged=tuple(staged),
        raw=tuple(raw),
        numstat=tuple(numstat),
    )


def finish_snapshot(capture: GitCapture) -> RepositoryProjection:
    tree_after = _oid_text(_run(["write-tree"], cwd=capture.root), "index tree")
    if tree_after != capture.index_tree_before:
        raise GitError("index changed while handoff evidence was collected")
    head_after = _oid_text(
        _run(["rev-parse", "--verify", "HEAD"], cwd=capture.root),
        "HEAD",
    )
    if head_after != capture.head:
        raise GitError("HEAD changed while handoff evidence was collected")
    final_data = _run(
        ["-c", "status.renames=true", "status", "--porcelain=v2", "-z"],
        cwd=capture.root,
    )
    _, final_entries = _parse_status(final_data, require_headers=False)
    if _entry_keys(final_entries) != _entry_keys(list(capture.staged)):
        raise GitError("staged projection changed during handoff collection")
    return RepositoryProjection(
        root=str(capture.root),
        head=capture.head,
        branch=capture.branch,
        upstream=capture.upstream,
        ahead=capture.ahead,
        behind=capture.behind,
        indexTree=tree_after,
        staged=list(capture.staged),
        numstat=list(capture.numstat),
    )


def _oid_text(data: bytes, label: str) -> str:
    value = data.decode("ascii", "strict").strip()
    if not _OID.fullmatch(value):
        raise GitError(f"invalid {label}: {value!r}")
    return value


def _decode_path(value: bytes) -> str:
    path = value.decode("utf-8", "strict")
    if not path or "\x00" in path:
        raise GitError("empty or invalid Git path")
    return path


def _parse_status(data: bytes, *, require_headers: bool) -> tuple[dict[str, str], list[StagedEntry]]:
    records = data.split(b"\0")
    if records and records[-1] == b"":
        records.pop()
    headers: dict[str, str] = {}
    entries: list[StagedEntry] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if record.startswith(b"# "):
            text = record[2:].decode("utf-8", "strict")
            key, separator, value = text.partition(" ")
            if not separator or key in headers:
                raise GitError("malformed or duplicate porcelain header")
            headers[key] = value
            continue
        if record.startswith(b"u "):
            raise GitError("unmerged entry remains after staging")
        if record.startswith(b"? "):
            raise GitError("untracked entry remains after staging")
        if record.startswith(b"! "):
            raise GitError("unexpected ignored entry in porcelain")
        if record.startswith(b"1 "):
            fields = record.split(b" ", 8)
            if len(fields) != 9:
                raise GitError("malformed ordinary porcelain record")
            _validate_submodule(fields[2])
            status = _validate_xy(fields[1])
            entries.append(StagedEntry(status=status, path=_decode_path(fields[8])))
            continue
        if record.startswith(b"2 "):
            fields = record.split(b" ", 9)
            if len(fields) != 10 or index >= len(records):
                raise GitError("malformed rename porcelain record")
            _validate_submodule(fields[2])
            status = _validate_xy(fields[1])
            if status != "R":
                raise GitError("copy and non-rename type-2 records are unsupported")
            _validate_rename_score(fields[8])
            destination = _decode_path(fields[9])
            source = _decode_path(records[index])
            index += 1
            entries.append(StagedEntry(status="R", path=destination, sourcePath=source))
            continue
        raise GitError(f"unsupported porcelain record kind: {record[:1]!r}")
    if require_headers and not {"branch.oid", "branch.head"}.issubset(headers):
        raise GitError("porcelain branch headers are incomplete")
    return headers, sorted(entries, key=_staged_sort_key)


def _validate_submodule(value: bytes) -> None:
    if value != b"N...":
        raise GitError("submodule state is unsupported")


def _validate_xy(value: bytes) -> str:
    if len(value) != 2:
        raise GitError("malformed porcelain XY status")
    staged, worktree = chr(value[0]), chr(value[1])
    if worktree != ".":
        raise GitError("unstaged worktree state remains after staging")
    if staged not in {"A", "M", "D", "R"}:
        if staged == "T":
            raise GitError("type changes are unsupported")
        raise GitError(f"unsupported staged status: {staged}")
    return staged


def _validate_rename_score(value: bytes) -> None:
    match = re.fullmatch(rb"R([0-9]{1,3})", value)
    if match is None or int(match.group(1)) > 100:
        raise GitError("malformed or unsupported rename score")


def _parse_raw(data: bytes) -> list[_RawEntry]:
    records = data.split(b"\0")
    if records and records[-1] == b"":
        records.pop()
    entries: list[_RawEntry] = []
    index = 0
    while index < len(records):
        header = records[index]
        index += 1
        if not header.startswith(b":"):
            raise GitError("malformed cached raw-diff record")
        fields = header[1:].decode("ascii", "strict").split(" ")
        if len(fields) != 5:
            raise GitError("malformed cached raw-diff metadata")
        old_mode, new_mode, old_oid, new_oid, raw_status = fields
        if old_mode not in _ALLOWED_MODES or new_mode not in _ALLOWED_MODES:
            raise GitError("submodule or unsupported Git mode in cached diff")
        if old_mode != "000000" and new_mode != "000000":
            old_class = "symlink" if old_mode == "120000" else "file"
            new_class = "symlink" if new_mode == "120000" else "file"
            if old_class != new_class:
                raise GitError("type changes are unsupported")
        status = raw_status[0]
        if status not in {"A", "M", "D", "R"}:
            raise GitError(f"unsupported cached raw status: {raw_status}")
        if status == "R":
            _validate_rename_score(raw_status.encode("ascii"))
        elif len(raw_status) != 1:
            raise GitError("unexpected score on non-rename raw record")
        if len(old_oid) not in {40, 64} or len(new_oid) != len(old_oid):
            raise GitError("cached raw diff contains non-full object IDs")
        if old_oid.strip("0") and not re.fullmatch(r"[0-9a-f]+", old_oid):
            raise GitError("cached raw diff contains invalid old object ID")
        if new_oid.strip("0") and not re.fullmatch(r"[0-9a-f]+", new_oid):
            raise GitError("cached raw diff contains invalid new object ID")
        if index >= len(records):
            raise GitError("cached raw diff omitted path")
        first_path = _decode_path(records[index])
        index += 1
        if status == "R":
            if index >= len(records):
                raise GitError("cached rename omitted destination")
            destination = _decode_path(records[index])
            index += 1
            entries.append(_RawEntry("R", destination, first_path))
        else:
            entries.append(_RawEntry(status, first_path, None))
    return sorted(entries, key=lambda item: (item.path.encode(), (item.source_path or "").encode()))


def _parse_numstat(data: bytes) -> list[NumstatEntry]:
    records = data.split(b"\0")
    if records and records[-1] == b"":
        records.pop()
    entries: list[NumstatEntry] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        fields = record.split(b"\t", 2)
        if len(fields) != 3:
            raise GitError("malformed cached numstat record")
        added, deleted, path_data = fields
        binary = added == b"-" and deleted == b"-"
        if not binary and (not added.isdigit() or not deleted.isdigit()):
            raise GitError("invalid numstat line counts")
        source_path: str | None = None
        if path_data == b"":
            if index + 1 >= len(records):
                raise GitError("numstat rename omitted paths")
            source_path = _decode_path(records[index])
            path = _decode_path(records[index + 1])
            index += 2
        else:
            path = _decode_path(path_data)
        entries.append(
            NumstatEntry(
                path=path,
                sourcePath=source_path,
                addedLines=None if binary else int(added),
                deletedLines=None if binary else int(deleted),
                binary=binary,
            )
        )
    return sorted(entries, key=lambda item: (item.path.encode(), (item.source_path or "").encode()))


def _entry_keys(entries: list[StagedEntry]) -> list[tuple[str, str, str | None]]:
    return [(entry.status, entry.path, entry.source_path) for entry in entries]


def _cross_check(
    staged: list[StagedEntry], raw: list[_RawEntry], numstat: list[NumstatEntry]
) -> None:
    staged_keys = _entry_keys(staged)
    raw_keys = [(entry.status, entry.path, entry.source_path) for entry in raw]
    if staged_keys != raw_keys:
        raise GitError("porcelain and cached raw diff disagree")
    staged_paths = [(entry.path, entry.source_path) for entry in staged]
    numstat_paths = [(entry.path, entry.source_path) for entry in numstat]
    if staged_paths != numstat_paths:
        raise GitError("porcelain and cached numstat disagree")


def _staged_sort_key(entry: StagedEntry) -> tuple[bytes, bytes]:
    return entry.path.encode("utf-8"), (entry.source_path or "").encode("utf-8")
