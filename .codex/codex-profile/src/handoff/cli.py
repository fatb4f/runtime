from __future__ import annotations

import argparse
import os
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from pydantic import ValidationError

from .git import GitError, begin_snapshot, finish_snapshot, resolve_repository
from .model import DerivedValue, Handoff, canonical_bytes
from .rollout import RolloutError, project_rollout, resolve_rollout


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Create a deterministic Git-and-rollout handoff")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="stage the repository and publish handoff.json")
    create.add_argument("--rollout", type=Path, help="explicit rollout JSONL path")
    create.add_argument(
        "--output-root",
        type=Path,
        help="state root override; output remains <root>/<session-id>/handoff.json",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.command != "create":
        parser.error(f"unknown command: {args.command}")
    try:
        path = create_handoff(
            rollout_path=args.rollout,
            output_root=args.output_root,
        )
    except (GitError, RolloutError, ValidationError, OSError, ValueError) as error:
        print(f"handoff creation failed: {error}", file=sys.stderr)
        return 2
    print(path)
    return 0


def create_handoff(
    *,
    repository: Path | None = None,
    rollout_path: Path | None = None,
    output_root: Path | None = None,
    now: datetime | None = None,
    codex_home: Path | None = None,
) -> Path:
    root = resolve_repository(repository or Path.cwd())
    explicit = rollout_path
    if explicit is None:
        from_environment = os.environ.get("CODEX_ROLLOUT_PATH")
        explicit = Path(from_environment) if from_environment else None
    admitted = resolve_rollout(root, explicit=explicit, codex_home=codex_home)
    state_root = _state_root(output_root)
    if _is_within(state_root, root):
        raise ValueError("output root must be outside the repository")

    capture = begin_snapshot(root)
    rollout = project_rollout(admitted)
    repository_projection = finish_snapshot(capture)
    completed = list(rollout.completed)
    for entry in repository_projection.staged:
        detail = f"Staged {entry.status} {entry.path}"
        if entry.source_path is not None:
            detail = f"Staged R {entry.source_path} -> {entry.path}"
        completed.append(
            DerivedValue(value=detail, sourceEvents=[], derivation="git-staged-change")
        )

    packet = Handoff(
        schema="codex.handoff.v0",
        createdAt=now or datetime.now(timezone.utc),
        repository=repository_projection,
        session=rollout.session,
        objective=rollout.objective,
        completed=completed,
        currentOperation=rollout.current_operation,
        nextOperation=rollout.next_operation,
        completionCriteria=rollout.completion_criteria,
        operations=rollout.operations,
        failures=rollout.failures,
        openQuestions=rollout.open_questions,
        diagnostics=rollout.diagnostics,
    )
    data = canonical_bytes(packet)
    return _publish(
        state_root=state_root,
        session_id=rollout.session.session_id,
        data=data,
    )


def _state_root(override: Path | None) -> Path:
    if override is not None:
        return override.expanduser().resolve()
    xdg = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state"))
    return (xdg.expanduser().resolve() / "handoff")


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _publish(*, state_root: Path, session_id: str, data: bytes) -> Path:
    state_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    if state_root.is_symlink():
        raise ValueError("output root cannot be a symlink")
    os.chmod(state_root, 0o700)
    directory = state_root / session_id
    if directory.is_symlink():
        raise ValueError("session output directory cannot be a symlink")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    if directory.resolve() != state_root / session_id:
        raise ValueError("session output directory escaped the output root")
    os.chmod(directory, 0o700)
    final = directory / "handoff.json"
    descriptor, temporary_name = tempfile.mkstemp(prefix=".handoff.", dir=directory)
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, final)
        os.chmod(final, 0o600)
        directory_fd = os.open(directory, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except BaseException:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)
        raise
    return final


if __name__ == "__main__":
    raise SystemExit(main())
