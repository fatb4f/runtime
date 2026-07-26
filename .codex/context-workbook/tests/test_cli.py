from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from context_workbook.engine import build_request, load_workbook_config

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKBOOK_ROOT = REPO_ROOT / ".codex/context-workbook"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sufficient-decision.json"


class CliTests(unittest.TestCase):
    def test_browserless_adapter_runs_canonical_workbook(self) -> None:
        environment = dict(os.environ)
        environment["CONTEXT_WORKBOOK_TEST_MODE"] = "1"
        environment["PYTHONPATH"] = str(WORKBOOK_ROOT / "src")
        process = subprocess.run(
            [
                sys.executable,
                str(WORKBOOK_ROOT / "workbook_cli.py"),
                "--repo-root",
                str(REPO_ROOT),
                "--prompt",
                "Implement Issue 54",
                "--revision",
                "HEAD",
                "--recorded-decision",
                str(FIXTURE),
                "--output",
                "all",
            ],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
            timeout=60,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("prompt-only selection fails closed", process.stderr)

    def test_projection_output_must_be_requested(self) -> None:
        environment = dict(os.environ)
        environment["CONTEXT_WORKBOOK_TEST_MODE"] = "1"
        environment["PYTHONPATH"] = str(WORKBOOK_ROOT / "src")
        resolver_only = subprocess.run(
            [
                sys.executable,
                str(WORKBOOK_ROOT / "workbook_cli.py"),
                "--repo-root",
                str(REPO_ROOT),
                "--prompt",
                "Resolver projection only",
                "--recorded-decision",
                str(FIXTURE),
                "--output",
                "code-intel",
            ],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
            timeout=60,
        )
        self.assertEqual(resolver_only.returncode, 2)
        self.assertIn("prompt-only selection fails closed", resolver_only.stderr)

        config, snapshot = load_workbook_config(REPO_ROOT)
        request = build_request(
            prompt="Code-intel projection only",
            config=config,
            snapshot=snapshot,
            requested_projection_ids=["code-intel"],
        )
        with tempfile.TemporaryDirectory(prefix="context-workbook-request-") as temporary:
            request_path = Path(temporary) / "request.json"
            request_path.write_text(request.model_dump_json(by_alias=True), encoding="utf-8")
            code_intel_only = subprocess.run(
                [
                    sys.executable,
                    str(WORKBOOK_ROOT / "workbook_cli.py"),
                    "--repo-root",
                    str(REPO_ROOT),
                    "--request-file",
                    str(request_path),
                    "--recorded-decision",
                    str(FIXTURE),
                    "--output",
                    "hook",
                ],
                capture_output=True,
                text=True,
                env=environment,
                check=False,
                timeout=60,
            )
        self.assertEqual(code_intel_only.returncode, 2)
        failure = json.loads(code_intel_only.stdout)
        self.assertEqual(failure["status"], "failure")

    def test_recorded_decision_requires_explicit_test_mode(self) -> None:
        environment = dict(os.environ)
        environment.pop("CONTEXT_WORKBOOK_TEST_MODE", None)
        environment.pop("CONTEXT_WORKBOOK_RECORDED_DECISION", None)
        environment["PYTHONPATH"] = str(WORKBOOK_ROOT / "src")
        process = subprocess.run(
            [
                sys.executable,
                str(WORKBOOK_ROOT / "workbook_cli.py"),
                "--repo-root",
                str(REPO_ROOT),
                "--prompt",
                "Recorded decisions must be test-only",
                "--recorded-decision",
                str(FIXTURE),
                "--output",
                "state",
            ],
            capture_output=True,
            text=True,
            env=environment,
            check=False,
            timeout=60,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("prompt-only selection fails closed", process.stderr)

    def test_installed_adapters_discover_workbook_from_git_worktree(self) -> None:
        environment = dict(os.environ)
        environment["CONTEXT_WORKBOOK_TEST_MODE"] = "1"
        environment["CONTEXT_WORKBOOK_RECORDED_DECISION"] = str(FIXTURE)
        environment["CONTEXT_WORKBOOK_PYTHON"] = sys.executable
        environment.pop("CONTEXT_WORKBOOK_REPO_ROOT", None)
        with tempfile.TemporaryDirectory(prefix="resolver-install-") as temporary:
            scripts = (
                Path(temporary)
                / "cache/dotfiles/agent-context-resolver/0.2.0+context-workbook/scripts"
            )
            scripts.mkdir(parents=True)
            installed_hook = scripts / "agent-context-resolver-hook"
            installed_cli = scripts / "resolve-agent-context"
            shutil.copy2(
                REPO_ROOT
                / ".codex/plugins/agent-context-resolver/scripts/agent-context-resolver-hook",
                installed_hook,
            )
            shutil.copy2(
                REPO_ROOT
                / ".codex/plugins/agent-context-resolver/scripts/resolve-agent-context",
                installed_cli,
            )
            process = subprocess.run(
                ["sh", str(installed_hook)],
                cwd=REPO_ROOT,
                input='{"hook_event_name":"UserPromptSubmit","prompt":"Installed hook"}\n',
                capture_output=True,
                text=True,
                env=environment,
                check=False,
                timeout=60,
            )
            cli_process = subprocess.run(
                [
                    "sh",
                    str(installed_cli),
                    "--cwd",
                    str(REPO_ROOT),
                    "--prompt",
                    "Installed CLI",
                ],
                cwd=Path(temporary),
                capture_output=True,
                text=True,
                env=environment,
                check=False,
                timeout=60,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        result = json.loads(process.stdout)
        context = json.loads(result["hookSpecificOutput"]["additionalContext"])
        self.assertEqual(context["sufficiency"]["state"], "insufficient")
        self.assertIsNone(context["context"])
        self.assertEqual(cli_process.returncode, 2)


if __name__ == "__main__":
    unittest.main()
