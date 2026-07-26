from __future__ import annotations

import sys
from pathlib import Path

import pytest

from codex_profile import cli


def test_misplaced_separator_never_launches(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(
        cli,
        "run_projected",
        lambda argv: pytest.fail(f"launched unexpectedly: {argv}"),
    )
    assert cli.main(["run-projected", "tool", "--", "argument"]) == 2
    assert "requires -- immediately" in capsys.readouterr().err


def test_valid_separator_preserves_empty_and_later_separator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[str] = []

    def fake(argv: list[str]):
        observed.extend(argv)
        return type(
            "Result",
            (),
            {
                "model_dump": lambda self, **kwargs: {
                    "schema": "codex.command-result.v0",
                    "exitCode": 0,
                    "signal": None,
                    "truncated": False,
                    "relevantLines": [],
                    "artifact": "/tmp/a",
                    "sha256": "0" * 64,
                }
            },
        )(), 0

    monkeypatch.setattr(cli, "run_projected", fake)
    assert cli.main(["run-projected", "--", "tool", "", "--", "tail"]) == 0
    assert observed == ["tool", "", "--", "tail"]
