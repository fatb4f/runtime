from __future__ import annotations

import subprocess
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from context_workbook.dspy_program import (
    CodexChatGPTLM,
    DspyContextProgram,
    DspyUnavailable,
)


class CodexChatGPTLMTests(unittest.TestCase):
    def test_invokes_isolated_codex_with_chatgpt_compatible_auth(self) -> None:
        completed = subprocess.CompletedProcess(
            args=["codex", "exec"],
            returncode=0,
            stdout="[[ ## decision_json ## ]]\n{}\n[[ ## completed ## ]]\n",
            stderr="",
        )
        with (
            patch.dict(
                "os.environ",
                {"CODEX_API_KEY": "api-secret", "OPENAI_API_KEY": "api-secret"},
                clear=False,
            ),
            patch("context_workbook.dspy_program.shutil.which", return_value="/usr/bin/codex"),
            patch("context_workbook.dspy_program.subprocess.run", return_value=completed) as run,
        ):
            response = CodexChatGPTLM("gpt-5.6-sol").forward(
                messages=[{"role": "user", "content": "Establish context"}]
            )

        command = run.call_args.args[0]
        self.assertEqual(command[0], "/usr/bin/codex")
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn("--ephemeral", command)
        self.assertNotIn("CODEX_API_KEY", run.call_args.kwargs["env"])
        self.assertNotIn("OPENAI_API_KEY", run.call_args.kwargs["env"])
        self.assertEqual(
            response.choices[0].message.content,
            "[[ ## decision_json ## ]]\n{}\n[[ ## completed ## ]]",
        )

    def test_missing_codex_cli_fails_closed_at_execution(self) -> None:
        lm = CodexChatGPTLM("gpt-5.6-sol")
        with patch("context_workbook.dspy_program.shutil.which", return_value=None):
            with self.assertRaisesRegex(DspyUnavailable, "Codex CLI is required"):
                lm.forward(messages=[{"role": "user", "content": "Establish context"}])

    def test_decision_schema_is_supplied_to_dspy(self) -> None:
        fixture = (
            Path(__file__).resolve().parent / "fixtures" / "sufficient-decision.json"
        ).read_text(encoding="utf-8")
        program = object.__new__(DspyContextProgram)
        program._predict = Mock(return_value=Mock(decision_json=fixture))
        serializable = Mock()
        serializable.model_dump_json.return_value = "{}"

        program.establish(
            request=serializable,
            inventory=serializable,
            observations={},
            evidence={},
            code_intel={},
        )

        schema = program._predict.call_args.kwargs["decision_schema_json"]
        self.assertIn('"derivedBy"', schema)


if __name__ == "__main__":
    unittest.main()
