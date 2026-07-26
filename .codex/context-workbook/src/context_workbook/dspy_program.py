"""DSPy context-establishment program and explicit test-only recorded adapter."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Protocol

from .models import ContextDecision, ContextInventory, ContextRequest, Evidence, SourceObservation

try:
    from dspy import BaseLM as _DspyBaseLM  # type: ignore
except ImportError:
    _DspyBaseLM = object  # type: ignore[assignment,misc]


class ContextReasoner(Protocol):
    def establish(
        self,
        *,
        request: ContextRequest,
        inventory: ContextInventory,
        observations: dict[str, SourceObservation],
        evidence: dict[str, Evidence],
        code_intel: dict[str, object],
    ) -> ContextDecision: ...


class DspyUnavailable(RuntimeError):
    pass


class CodexChatGPTLM(_DspyBaseLM):  # type: ignore[misc]
    """DSPy LM adapter backed by Codex's cached ChatGPT authentication."""

    def __init__(self, model: str) -> None:
        if _DspyBaseLM is object:
            raise DspyUnavailable(
                "DSPy is required for production context establishment; install the locked workbook project"
            )
        self.codex_command = os.environ.get("CONTEXT_WORKBOOK_CODEX", "codex")
        self.codex_model = model
        super().__init__(model=f"codex/{model}", cache=False, max_tokens=8000)

    @staticmethod
    def _render_prompt(
        prompt: str | None, messages: list[dict[str, object]] | None
    ) -> str:
        conversation = messages or [{"role": "user", "content": prompt or ""}]
        return (
            "You are the language-model backend for a DSPy program. "
            "Do not inspect files, execute commands, call tools, or add commentary. "
            "Return only the assistant response requested by these messages, preserving "
            "their required output format exactly.\n\n"
            f"MESSAGES_JSON={json.dumps(conversation, sort_keys=True)}"
        )

    def forward(
        self,
        prompt: str | None = None,
        messages: list[dict[str, object]] | None = None,
        **_: object,
    ):
        from litellm import ModelResponse  # type: ignore

        codex_binary = shutil.which(self.codex_command)
        if codex_binary is None:
            raise DspyUnavailable(
                "Codex CLI is required for ChatGPT-authenticated context establishment"
            )

        environment = dict(os.environ)
        environment.pop("CODEX_API_KEY", None)
        environment.pop("OPENAI_API_KEY", None)
        with tempfile.TemporaryDirectory(prefix="context-workbook-codex-") as temporary:
            process = subprocess.run(
                [
                    codex_binary,
                    "exec",
                    "--ephemeral",
                    "--ignore-user-config",
                    "--ignore-rules",
                    "--skip-git-repo-check",
                    "--sandbox",
                    "read-only",
                    "--color",
                    "never",
                    "--disable",
                    "shell_tool",
                    "--disable",
                    "apps",
                    "--disable",
                    "multi_agent",
                    "-c",
                    'model_reasoning_effort="low"',
                    "--model",
                    self.codex_model,
                    "--cd",
                    temporary,
                    "-",
                ],
                input=self._render_prompt(prompt, messages),
                capture_output=True,
                text=True,
                check=False,
                env=environment,
                timeout=120,
            )
        if process.returncode != 0:
            detail = process.stderr.strip().splitlines()
            message = detail[-1] if detail else "Codex exited without an error message"
            raise DspyUnavailable(f"ChatGPT-authenticated Codex execution failed: {message}")
        output = process.stdout.strip()
        if not output:
            raise DspyUnavailable("ChatGPT-authenticated Codex execution returned no output")
        return ModelResponse(
            model=self.model,
            choices=[{"message": {"role": "assistant", "content": output}}],
        )


def _dspy_module():
    try:
        import dspy  # type: ignore
    except ImportError as error:
        raise DspyUnavailable(
            "DSPy is required for production context establishment; install the locked workbook project"
        ) from error
    return dspy


class DspyContextProgram:
    """LM-backed DSPy program. It produces typed inference deltas only."""

    def __init__(self, *, model: str | None = None) -> None:
        dspy = _dspy_module()

        class EstablishContext(dspy.Signature):
            """Establish bounded high-fidelity context from typed evidence.

            Never invent source facts. Select only IDs and paths present in the inputs.
            Report every unresolved gap and conflict. Context sufficiency is not task success.
            """

            request_json = dspy.InputField(desc="Closed context request JSON")
            inventory_json = dspy.InputField(desc="Available fragments, providers, and workflows")
            observations_json = dspy.InputField(desc="Bounded source observations")
            evidence_json = dspy.InputField(desc="Evidence derived from observations")
            code_intel_json = dspy.InputField(desc="Read-only code-intel declarations")
            decision_schema_json = dspy.InputField(
                desc="Exact JSON Schema that decision_json must satisfy"
            )
            decision_json = dspy.OutputField(desc="One JSON object matching ContextDecision")

        if model:
            if model.startswith("codex/"):
                dspy.configure(lm=CodexChatGPTLM(model.removeprefix("codex/")))
            else:
                dspy.configure(lm=dspy.LM(model))
        self._predict = dspy.ChainOfThought(EstablishContext)

    def establish(
        self,
        *,
        request: ContextRequest,
        inventory: ContextInventory,
        observations: dict[str, SourceObservation],
        evidence: dict[str, Evidence],
        code_intel: dict[str, object],
    ) -> ContextDecision:
        try:
            result = self._predict(
                request_json=request.model_dump_json(by_alias=True),
                inventory_json=inventory.model_dump_json(by_alias=True),
                observations_json=json.dumps(
                    {key: value.model_dump(by_alias=True) for key, value in observations.items()},
                    sort_keys=True,
                ),
                evidence_json=json.dumps(
                    {key: value.model_dump(by_alias=True) for key, value in evidence.items()},
                    sort_keys=True,
                ),
                code_intel_json=json.dumps(code_intel, sort_keys=True),
                decision_schema_json=json.dumps(
                    ContextDecision.model_json_schema(by_alias=True), sort_keys=True
                ),
            )
            raw = getattr(result, "decision_json", None)
            if not isinstance(raw, str):
                raise DspyUnavailable("DSPy did not return decision_json")
            return ContextDecision.model_validate_json(raw)
        except DspyUnavailable:
            raise
        except Exception as error:
            raise DspyUnavailable(f"DSPy context establishment failed: {error}") from error


class RecordedContextProgram:
    """Test-only deterministic adapter; never selected implicitly in production."""

    def __init__(self, decision: ContextDecision) -> None:
        self._decision = decision

    @classmethod
    def from_path(cls, path: Path) -> "RecordedContextProgram":
        if os.environ.get("CONTEXT_WORKBOOK_TEST_MODE") != "1":
            raise DspyUnavailable("recorded predictions are restricted to explicit test mode")
        return cls(ContextDecision.model_validate_json(path.read_text(encoding="utf-8")))

    def establish(self, **_: object) -> ContextDecision:
        return self._decision


def production_reasoner() -> DspyContextProgram:
    model = os.environ.get("CONTEXT_WORKBOOK_DSPY_MODEL", "codex/gpt-5.6-sol")
    return DspyContextProgram(model=model)
