from __future__ import annotations

import hashlib
import json
import os
import signal
import sys
import tracemalloc
from pathlib import Path

import pytest

from codex_profile import runner
from codex_profile.contracts import ContractViolation, canonical_bytes
from codex_profile.runner import CommandQuarantined, run_projected


def test_separate_binary_streams_and_hashes(tmp_path: Path) -> None:
    code = "import os,sys;os.write(1,b'good\\x00\\xff\\n');os.write(2,b'ERROR bad\\n');sys.exit(7)"
    result, status = run_projected([sys.executable, "-c", code], state_root=tmp_path)
    assert status == result.exit_code == 7
    assert result.truncated
    assert "ERROR bad" in result.relevant_lines
    artifact = Path(result.artifact)
    manifest = json.loads(artifact.read_text())
    assert (artifact.parent / "stdout.bin").read_bytes() == b"good\x00\xff\n"
    assert (artifact.parent / "stderr.bin").read_bytes() == b"ERROR bad\n"
    assert result.sha256 == hashlib.sha256(artifact.read_bytes()).hexdigest()
    assert manifest["stdoutBytes"] == 7
    assert len(canonical_bytes(result)) <= 4096


def test_command_not_found_is_retained(tmp_path: Path) -> None:
    result, status = run_projected(["codex-profile-no-such-command"], state_root=tmp_path)
    assert status == result.exit_code == 127
    assert Path(result.artifact).exists()


def test_signal_normalization(tmp_path: Path) -> None:
    result, status = run_projected(
        [sys.executable, "-c", "import os,signal;os.kill(os.getpid(), signal.SIGTERM)"],
        state_root=tmp_path,
    )
    assert result.signal == signal.SIGTERM
    assert status == 128 + signal.SIGTERM


def test_large_output_and_twenty_line_bound(tmp_path: Path) -> None:
    code = "import sys\nfor i in range(10000): print(f'line {i}')\nprint('fatal final', file=sys.stderr)"
    result, _ = run_projected([sys.executable, "-c", code], state_root=tmp_path)
    assert result.truncated
    assert len(result.relevant_lines) <= 20
    assert "fatal final" in result.relevant_lines
    assert Path(result.artifact).parent.joinpath("stdout.bin").stat().st_size > 80000


def test_multimegabyte_newline_free_output_has_bounded_projection_memory(
    tmp_path: Path,
) -> None:
    code = "import sys;sys.stdout.write('x' * (3 * 1024 * 1024))"
    tracemalloc.start()
    result, _ = run_projected([sys.executable, "-c", code], state_root=tmp_path)
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert result.truncated
    assert len(result.relevant_lines) == 1
    assert len(canonical_bytes(result)) <= 4096
    assert peak < 2 * 1024 * 1024


def test_artifact_admission_failure_quarantines_completed_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def reject(*args, **kwargs):
        raise ContractViolation("command.output-discarded", "forced")

    monkeypatch.setattr(runner, "admit_command_artifact", reject)
    with pytest.raises(CommandQuarantined) as raised:
        run_projected([sys.executable, "-c", "print('retained')"], state_root=tmp_path)
    error = raised.value
    assert error.code == "command.output-discarded"
    assert error.failure_phase == "artifact-admission"
    quarantine = json.loads(error.artifact_path.read_text())
    directory = error.artifact_path.parent
    assert quarantine["failureCode"] == error.code
    assert quarantine["manifestAvailable"]
    assert hashlib.sha256((directory / "stdout.bin").read_bytes()).hexdigest() == (
        quarantine["stdoutSha256"]
    )
    assert (directory / "manifest.json").is_file()


def test_preflight_failure_prevents_child_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CODEX_PROFILE_CUE", str(tmp_path / "missing-cue"))
    monkeypatch.setattr(
        runner.subprocess,
        "Popen",
        lambda *args, **kwargs: pytest.fail("child launched before preflight"),
    )
    with pytest.raises(ContractViolation, match="contract.unavailable"):
        run_projected(["tool"], state_root=tmp_path)
