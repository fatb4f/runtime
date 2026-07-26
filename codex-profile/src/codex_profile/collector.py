from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from pathlib import Path

from codex_profile.adapters.usage import adapt_rollout_record
from codex_profile.reporting import parse_event
from codex_profile.sources.rollout import (
    SourceIncarnationMismatch,
    candidate_rollout_files,
    iter_complete_records,
)
from codex_profile.storage import IngestCounts, ProfileStorage


@dataclass(frozen=True)
class CollectorResult:
    files_seen: int
    files_ingested: int
    counts: IngestCounts
    strict_diagnostics: int
    active_sources: tuple[tuple[str, int], ...]


def ingest_rollouts(
    *,
    root: Path,
    repo: str,
    storage: ProfileStorage,
    fail_after_raw_at: tuple[str, int, int] | None = None,
) -> CollectorResult:
    files = candidate_rollout_files(root)
    total = IngestCounts()
    strict_diagnostics = 0
    files_ingested = 0
    active_sources: list[tuple[str, int]] = []

    for path in files:
        if not _matches_repo(path, repo):
            continue
        files_ingested += 1
        while True:
            resolved = storage.resolve_source(path)
            source_id = resolved.source_id
            generation = resolved.source_generation
            active_sources.append((source_id, generation))
            state = resolved.state
            incarnation_changed = False
            try:
                for record in iter_complete_records(
                    path,
                    start_offset=resolved.start_offset,
                    source_id=source_id,
                    generation=generation,
                    expected_identity=resolved.source_identity,
                ):
                    adapted = adapt_rollout_record(record, state)
                    fail_after_raw = fail_after_raw_at == (
                        record.source_id,
                        record.source_generation,
                        record.source_offset,
                    )
                    counts = storage.admit(adapted, fail_after_raw=fail_after_raw)
                    state = adapted.state
                    strict_diagnostics += sum(1 for item in adapted.diagnostics if item.strict)
                    total = total.plus(counts)
            except SourceIncarnationMismatch:
                incarnation_changed = True
            if not incarnation_changed:
                break

    return CollectorResult(
        files_seen=len(files),
        files_ingested=files_ingested,
        counts=total,
        strict_diagnostics=strict_diagnostics,
        active_sources=tuple(active_sources),
    )


def _matches_repo(path: Path, repo: str) -> bool:
    if not repo:
        return True
    needle = str(Path(repo).expanduser()).casefold() if "/" in repo else repo.casefold()
    if needle in str(path).casefold():
        return True

    for record in iter_complete_records(path):
        if record.obj is None:
            continue
        raw_text = record.raw.decode("utf-8", errors="replace")
        event = parse_event(path, 0, raw_text, timezone.utc)
        if any(needle in hint.casefold() for hint in event.repo_hints):
            return True
        if any(needle in path_value.casefold() for path_value in event.paths):
            return True
        if "session_meta" in event.event_kind.lower() and needle in raw_text.casefold():
            return True
    return False
