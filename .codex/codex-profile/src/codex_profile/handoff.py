from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from codex_profile.contracts import (
    ContractViolation,
    Handoff,
    Repository,
    admit_handoff,
    canonical_bytes,
)

HANDOFF_LIMIT = 16 * 1024


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _git(*args: str, cwd: Path, binary: bool = False) -> str | bytes:
    result = subprocess.run(
        ["git", *args], cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False
    )
    if result.returncode:
        raise RuntimeError(result.stderr.decode("utf-8", "replace").strip() or "Git inspection failed")
    if binary:
        return result.stdout
    return result.stdout.decode("utf-8", "strict").strip()


def _paths(data: bytes) -> list[str]:
    values = data.rstrip(b"\0").split(b"\0") if data else []
    decoded = [value.decode("utf-8", "strict") for value in values if value]
    return sorted(decoded, key=lambda value: value.encode("utf-8"))


def repository_state(cwd: Path) -> Repository:
    root = Path(str(_git("rev-parse", "--show-toplevel", cwd=cwd))).resolve()
    revision = str(_git("rev-parse", "--verify", "HEAD", cwd=root))
    branch_result = subprocess.run(
        ["git", "symbolic-ref", "--quiet", "--short", "HEAD"],
        cwd=root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False,
    )
    branch = (
        branch_result.stdout.decode("utf-8", "strict").strip()
        if branch_result.returncode == 0
        else None
    )
    unstaged = _paths(bytes(_git("diff", "--name-only", "-z", cwd=root, binary=True)))
    untracked = _paths(bytes(_git("ls-files", "--others", "--exclude-standard", "-z", cwd=root, binary=True)))
    staged = _paths(bytes(_git("diff", "--cached", "--name-only", "-z", cwd=root, binary=True)))
    return Repository.model_validate({
        "root": str(root), "revision": revision, "branch": branch,
        "dirtyPaths": sorted(set(unstaged + untracked), key=lambda value: value.encode()),
        "stagedPaths": staged,
    })


def markdown(packet: Handoff) -> str:
    def esc(value: str) -> str:
        return value.replace("\\", "\\\\").replace("`", "\\`").replace("\n", "  \n")
    def section(title: str, values: list[str]) -> list[str]:
        return [f"## {title}", "", *([f"- {esc(v)}" for v in values] or ["- None"]), ""]
    lines = ["# Codex handoff", "", f"Created: `{packet.created_at.isoformat().replace('+00:00', 'Z')}`", "",
             "## Objective", "", esc(packet.objective), "",
             "## Repository", "", f"- Root: `{esc(packet.repository.root)}`",
             f"- Revision: `{packet.repository.revision}`",
             f"- Branch: `{esc(packet.repository.branch)}`" if packet.repository.branch else "- Branch: detached HEAD", ""]
    lines += section("Invariants", packet.invariants) + section("Decisions", packet.decisions)
    lines += section("Dirty paths", packet.repository.dirty_paths) + section("Staged paths", packet.repository.staged_paths)
    lines += ["## Validation", "", *[f"- Passing: {esc(v)}" for v in packet.validation.passing],
              *[f"- Failing: {esc(v)}" for v in packet.validation.failing],
              *[f"- Not run: {esc(v)}" for v in packet.validation.not_run]]
    if not any((packet.validation.passing, packet.validation.failing, packet.validation.not_run)):
        lines.append("- None")
    lines += ["", "## Current operation", "", esc(packet.current_operation), "",
              "## Next operation", "", esc(packet.next_operation), ""]
    lines += section("Completion criteria", packet.completion_criteria)
    lines += section("Evidence pointers", packet.evidence_pointers) + section("Open questions", packet.open_questions)
    return "\n".join(lines).rstrip() + "\n"


def create_handoff(args, *, now: datetime | None = None, state_root: Path | None = None) -> tuple[Path, Path, Handoff]:
    created = now or datetime.now(timezone.utc)
    authority = repository_state(Path.cwd())
    packet = admit_handoff({
        "schema": "codex.handoff.v0", "createdAt": created,
        "objective": args.objective, "invariants": args.invariant, "decisions": args.decision,
        "repository": authority,
        "validation": {"passing": args.passing, "failing": args.failing, "notRun": args.not_run},
        "currentOperation": args.current_operation, "nextOperation": args.next_operation,
        "completionCriteria": args.completion_criterion,
        "evidencePointers": args.evidence_pointer, "openQuestions": args.open_question,
    }, repository_authority=authority)
    json_data = canonical_bytes(packet)
    md_data = markdown(packet).encode()
    if len(json_data) > HANDOFF_LIMIT or len(md_data) > HANDOFF_LIMIT:
        raise ContractViolation(
            "handoff.size-exceeded", "handoff exceeds the 16 KiB JSON or Markdown limit"
        )
    stamp = created.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    ident = f"{stamp}-{hashlib.sha256(json_data).hexdigest()[:12]}"
    parent = state_root or Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "codex-profile/handoffs"
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    final = parent / ident
    if final.exists():
        raise FileExistsError(f"handoff already exists: {final}")
    temp = Path(tempfile.mkdtemp(prefix=f".{ident}.", dir=parent))
    os.chmod(temp, 0o700)
    try:
        for name, data in (("handoff.json", json_data), ("handoff.md", md_data)):
            path = temp / name
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as handle:
                handle.write(data); handle.flush(); os.fsync(handle.fileno())
        _fsync_directory(temp)
        os.rename(temp, final)
        _fsync_directory(parent)
    except BaseException:
        shutil.rmtree(temp, ignore_errors=True)
        raise
    return final / "handoff.json", final / "handoff.md", packet
