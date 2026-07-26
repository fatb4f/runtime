"""Deterministic plugin projection descriptors generated from CUE authority."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any

from .models import digest_value


def _cue_export(root: Path, expression: str, cue_binary: str = "cue") -> object:
    process = subprocess.run(
        [cue_binary, "export", ".", "-e", expression, "--out", "json"],
        cwd=root / ".codex/context-model",
        capture_output=True,
        text=True,
        check=False,
        timeout=30,
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip())
    return json.loads(process.stdout)


def projection_documents(root: Path, cue_binary: str = "cue") -> dict[str, dict[str, Any]]:
    model = _cue_export(root, "rootSeed", cue_binary)
    config = _cue_export(root, "workbookConfig", cue_binary)
    if not isinstance(model, dict):
        raise RuntimeError("rootSeed must export an object")
    config_digest = digest_value(config)
    common = {
        "schema": "dotfiles.context-workbook-plugin-projection.v0",
        "authority": False,
        "generated": True,
        "modelSchema": model["schema"],
        "modelStatus": model["status"],
        "modelScope": model["scope"],
        "configDigest": config_digest,
        "workbook": ".codex/context-workbook/context-workbook.py",
        "browserlessAdapter": ".codex/context-workbook/workbook_cli.py",
    }
    return {
        ".codex/plugins/agent-context-resolver/generated/context-workbook-projection.json": {
            **common,
            "plugin": "agent-context-resolver",
            "role": "control-adapter",
            "outputSchema": "agent.resolver-prompt-surface.v2",
        },
        ".codex/plugins/code-intel/reference/context-workbook-projection.json": {
            **common,
            "plugin": "code-intel",
            "role": "evidence-adapter",
            "outputSchema": "dotfiles.code-intel-context.v0",
        },
    }


def write_projections(root: Path, cue_binary: str = "cue", check: bool = False) -> int:
    mismatches: list[str] = []
    for relative, document in projection_documents(root, cue_binary).items():
        path = root / relative
        expected = json.dumps(document, sort_keys=True, indent=2) + "\n"
        if check:
            if not path.is_file() or path.read_text(encoding="utf-8") != expected:
                mismatches.append(relative)
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(expected, encoding="utf-8")
    if mismatches:
        raise RuntimeError(f"stale context-workbook projections: {', '.join(mismatches)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--cue", default="cue")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    return write_projections(args.repo_root.resolve(strict=True), args.cue, args.check)


if __name__ == "__main__":
    raise SystemExit(main())
