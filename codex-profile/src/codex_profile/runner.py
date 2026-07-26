from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile
import time
from collections import deque
from datetime import datetime, timezone
from pathlib import Path

from codex_profile.contracts import (
    ContractViolation,
    CommandManifest,
    CommandQuarantine,
    CommandResult,
    admit_command_artifact,
    admit_command_result,
    canonical_bytes,
    validate_command_manifest,
)

RESULT_LIMIT = 4096
LINE_LIMIT = 512
TERMS = ("error", "fail", "fatal", "panic", "traceback", "expected", "got")


class CommandQuarantined(ContractViolation):
    def __init__(self, code: str, detail: str, *, failure_phase: str, artifact_path: Path):
        self.failure_phase = failure_phase
        self.artifact_path = artifact_path
        super().__init__(code, detail)


def _digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(64 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def _fsync_directory(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _projection_lines(paths: tuple[Path, Path]) -> tuple[list[str], bool]:
    overall: deque[tuple[int, str]] = deque(maxlen=20)
    matching: deque[tuple[int, str]] = deque(maxlen=20)
    count = 0
    truncated = False
    def admit(raw: bytes, shortened: bool) -> None:
        nonlocal count, truncated
        try:
            line = raw.decode("utf-8", "strict")
        except UnicodeDecodeError:
            line = raw.decode("utf-8", "replace"); truncated = True
        if not line.strip():
            return
        if shortened or len(line.encode()) > LINE_LIMIT:
            line = line.encode()[:LINE_LIMIT].decode("utf-8", "ignore") + "…"; truncated = True
        entry = (count, line)
        count += 1
        overall.append(entry)
        if any(term in line.lower() for term in TERMS):
            matching.append(entry)
    for path in paths:
        pending = bytearray()
        shortened = False
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(64 * 1024), b""):
                chunks = block.split(b"\n")
                for index, chunk in enumerate(chunks):
                    if index:
                        admit(bytes(pending), shortened)
                        pending.clear()
                        shortened = False
                    remaining = LINE_LIMIT * 2 - len(pending)
                    pending.extend(chunk[:max(0, remaining)])
                    shortened = shortened or len(chunk) > max(0, remaining)
        if pending or shortened:
            admit(bytes(pending), shortened)
    chosen = {entry[0]: entry for entry in matching}
    for entry in reversed(overall):
        if len(chosen) >= 20: break
        chosen.setdefault(entry[0], entry)
    if len(chosen) < count:
        truncated = True
    return [chosen[index][1] for index in sorted(chosen)], truncated


def _preflight() -> None:
    cue_setting = os.environ.get("CODEX_PROFILE_CUE", "cue")
    cue = shutil.which(cue_setting)
    root = Path(
        os.environ.get(
            "CODEX_PROFILE_CONTRACT_ROOT",
            Path(__file__).resolve().parents[2] / "contracts",
        )
    )
    if cue is None or not root.is_dir() or not os.access(root, os.R_OK | os.X_OK):
        raise ContractViolation("contract.unavailable", "CUE or contract root is unavailable")
    for definition in ("#CommandArtifactManifest", "#CommandResult", "#CommandQuarantine"):
        result = subprocess.run(
            [cue, "eval", ".", "-e", definition],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            check=False,
        )
        if result.returncode:
            raise ContractViolation(
                "contract.unavailable",
                result.stderr.decode("utf-8", "replace").strip(),
            )


def _write_fsynced(path: Path, data: bytes) -> None:
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def _quarantine(
    *,
    temp: Path,
    parent: Path,
    ident: str,
    manifest_value: dict,
    phase: str,
    error: BaseException,
) -> CommandQuarantined:
    code = error.code if isinstance(error, ContractViolation) else "command.publication-failed"
    detail = str(error)[:2048]
    value = {
        "schema": "codex.command-quarantine.v0",
        **{key: manifest_value[key] for key in (
            "argv", "workingDirectory", "startedAt", "durationSeconds", "exitCode",
            "signal", "stdoutBytes", "stderrBytes", "stdoutSha256", "stderrSha256",
        )},
        "manifestAvailable": (temp / "manifest.json").is_file(),
        "failurePhase": phase,
        "failureCode": code,
        "failureDetail": detail,
    }
    quarantine = CommandQuarantine.model_validate(value)
    quarantine_path = temp / "quarantine.json"
    if not quarantine_path.exists():
        _write_fsynced(quarantine_path, canonical_bytes(quarantine))
    _fsync_directory(temp)
    final = parent / f"{ident}-quarantine"
    try:
        os.rename(temp, final)
        _fsync_directory(parent)
        retained = final
    except OSError:
        retained = final if final.exists() else temp
    return CommandQuarantined(
        code, detail, failure_phase=phase, artifact_path=retained / "quarantine.json"
    )


def run_projected(argv: list[str], *, state_root: Path | None = None) -> tuple[CommandResult, int]:
    if not argv:
        raise ValueError("no command follows --")
    _preflight()
    started = datetime.now(timezone.utc)
    parent = state_root or Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "codex-profile/command-results"
    parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    ident = started.strftime("%Y%m%dT%H%M%S%fZ") + f"-{os.getpid()}"
    final = parent / ident
    temp = Path(tempfile.mkdtemp(prefix=f".{ident}.", dir=parent)); os.chmod(temp, 0o700)
    stdout_path, stderr_path = temp / "stdout.bin", temp / "stderr.bin"
    began = time.monotonic()
    try:
        with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
            os.chmod(stdout_path, 0o600); os.chmod(stderr_path, 0o600)
            try:
                process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, shell=False)
                raw_exit = process.wait()
                signal = -raw_exit if raw_exit < 0 else None
                exit_code = 128 + signal if signal else raw_exit
            except FileNotFoundError:
                stderr.write(f"{argv[0]}: command not found\n".encode()); signal, exit_code = None, 127
            except PermissionError:
                stderr.write(f"{argv[0]}: permission denied\n".encode()); signal, exit_code = None, 126
            stdout.flush(); os.fsync(stdout.fileno()); stderr.flush(); os.fsync(stderr.fileno())
        manifest_value = {
            "schema": "codex.command-artifact.v0", "argv": argv,
            "workingDirectory": str(Path.cwd().resolve()), "startedAt": started,
            "durationSeconds": time.monotonic() - began, "exitCode": exit_code, "signal": signal,
            "stdoutBytes": stdout_path.stat().st_size, "stderrBytes": stderr_path.stat().st_size,
            "stdoutSha256": _digest(stdout_path), "stderrSha256": _digest(stderr_path),
        }
        manifest = validate_command_manifest(manifest_value)
        manifest_data = canonical_bytes(manifest)
        manifest_path = temp / "manifest.json"
        _write_fsynced(manifest_path, manifest_data)
        _fsync_directory(temp)
        try:
            admit_command_artifact(manifest_value, artifact_directory=temp)
        except BaseException as error:
            raise _quarantine(
                temp=temp, parent=parent, ident=ident, manifest_value=manifest_value,
                phase="artifact-admission", error=error,
            ) from error
        try:
            lines, truncated = _projection_lines((temp / "stdout.bin", temp / "stderr.bin"))
        except BaseException as error:
            raise _quarantine(
                temp=temp, parent=parent, ident=ident, manifest_value=manifest_value,
                phase="projection", error=error,
            ) from error
        digest = hashlib.sha256(manifest_data).hexdigest()
        while True:
            result_value = {
                "schema": "codex.command-result.v0", "exitCode": exit_code, "signal": signal,
                "truncated": truncated, "relevantLines": lines,
                "artifact": str(final / "manifest.json"), "sha256": digest,
            }
            try:
                try:
                    result = admit_command_result(
                        result_value, limit=RESULT_LIMIT, artifact_path=manifest_path
                    )
                except ContractViolation as error:
                    if error.code == "command.projection-exceeded" and lines:
                        lines.pop(0)
                        truncated = True
                        continue
                    raise
            except ContractViolation as error:
                raise _quarantine(
                    temp=temp, parent=parent, ident=ident, manifest_value=manifest_value,
                    phase="result-admission", error=error,
                ) from error
            except BaseException as error:
                raise _quarantine(
                    temp=temp, parent=parent, ident=ident, manifest_value=manifest_value,
                    phase="result-admission", error=error,
                ) from error
            try:
                _fsync_directory(temp)
                os.rename(temp, final)
                _fsync_directory(parent)
            except BaseException as error:
                location = final if final.exists() else temp
                raise _quarantine(
                    temp=location, parent=parent, ident=ident, manifest_value=manifest_value,
                    phase="publication", error=error,
                ) from error
            return result, exit_code
    except CommandQuarantined:
        raise
    except BaseException:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)
        raise
