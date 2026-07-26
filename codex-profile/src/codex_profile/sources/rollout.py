from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, Iterator


ANCHOR_BYTE_WINDOW = 4096


class SourceIncarnationMismatch(RuntimeError):
    pass


@dataclass(frozen=True)
class RolloutRecord:
    path: Path
    source_id: str
    source_generation: int
    source_offset: int
    raw: bytes
    obj: Any | None
    json_error: str | None
    source_identity: str
    source_size: int
    checkpoint_anchor_start: int
    checkpoint_anchor_end: int
    checkpoint_anchor_digest: str

    @property
    def raw_byte_count(self) -> int:
        return len(self.raw)

    @property
    def payload_digest(self) -> str:
        return "sha256:" + hashlib.sha256(self.raw).hexdigest()

    @property
    def next_offset(self) -> int:
        return self.checkpoint_anchor_end


@dataclass(frozen=True)
class SourceIncarnation:
    identity: str
    size: int


def stable_source_id(path: Path) -> str:
    resolved = str(path.expanduser().resolve(strict=False))
    return "sha256:" + hashlib.sha256(f"rollout:{resolved}".encode("utf-8")).hexdigest()


def source_incarnation(path: Path) -> SourceIncarnation:
    stat = path.stat()
    identity = _incarnation_identity(stat)
    return SourceIncarnation(identity=identity, size=stat.st_size)


def source_generation(path: Path) -> int:
    return 0


def iter_complete_records(
    path: Path,
    *,
    start_offset: int = 0,
    source_id: str | None = None,
    generation: int | None = None,
    expected_identity: str | None = None,
) -> Iterator[RolloutRecord]:
    resolved_source_id = stable_source_id(path) if source_id is None else source_id
    resolved_generation = source_generation(path) if generation is None else generation
    with path.open("rb") as handle:
        opened = os.fstat(handle.fileno())
        source_identity = _incarnation_identity(opened)
        if expected_identity is not None and source_identity != expected_identity:
            raise SourceIncarnationMismatch(str(path))
        handle.seek(start_offset)
        offset = start_offset
        while True:
            line = handle.readline()
            if not line:
                return
            if not line.endswith(b"\n"):
                return
            raw = line[:-1]
            if line.endswith(b"\r\n"):
                raw = line[:-2]
            if not raw:
                offset += len(line)
                continue
            obj: Any | None
            error: str | None = None
            try:
                obj = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                obj = None
                error = str(exc)
            next_offset = offset + len(line)
            anchor_start = max(0, next_offset - ANCHOR_BYTE_WINDOW)
            current = os.fstat(handle.fileno())
            yield RolloutRecord(
                path=path,
                source_id=resolved_source_id,
                source_generation=resolved_generation,
                source_offset=offset,
                raw=raw,
                obj=obj,
                json_error=error,
                source_identity=source_identity,
                source_size=current.st_size,
                checkpoint_anchor_start=anchor_start,
                checkpoint_anchor_end=next_offset,
                checkpoint_anchor_digest=_digest_handle_range(handle, anchor_start, next_offset),
            )
            offset += len(line)


def _incarnation_identity(stat: os.stat_result) -> str:
    return f"dev:{stat.st_dev}:ino:{stat.st_ino}"


def _digest_handle_range(handle: BinaryIO, start: int, end: int) -> str:
    position = handle.tell()
    try:
        handle.seek(start)
        data = handle.read(end - start)
    finally:
        handle.seek(position)
    if len(data) != end - start:
        raise OSError(f"incomplete anchor range: {start}:{end}")
    return "sha256:" + hashlib.sha256(data).hexdigest()


def candidate_rollout_files(root: Path) -> list[Path]:
    if root.is_file():
        return [root] if root.suffix == ".jsonl" else []
    sessions = root / "sessions"
    base = sessions if sessions.exists() else root
    return sorted(path for path in base.rglob("*.jsonl") if path.is_file())
