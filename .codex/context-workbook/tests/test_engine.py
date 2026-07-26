from __future__ import annotations

import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from context_workbook.dspy_program import RecordedContextProgram
from context_workbook.engine import (
    ContextEngine,
    EngineError,
    build_request,
    cue_validate_state,
    load_workbook_config,
    production_reasoner_or_fail_closed,
)
from context_workbook.models import ContextDecision, ContextRequest, ContextState


REPO_ROOT = Path(__file__).resolve().parents[3]
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sufficient-decision.json"


class CapturingProgram:
    def __init__(self, decision: ContextDecision) -> None:
        self.decision = decision
        self.inputs: dict[str, object] = {}

    def establish(self, **inputs: object) -> ContextDecision:
        self.inputs = inputs
        return self.decision


class UnavailableProgram:
    def establish(self, **_: object) -> ContextDecision:
        from context_workbook.dspy_program import DspyUnavailable

        raise DspyUnavailable("ChatGPT session unavailable")


class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ["CONTEXT_WORKBOOK_TEST_MODE"] = "1"
        cls.config, cls.snapshot = load_workbook_config(REPO_ROOT)
        cls.decision = ContextDecision.model_validate_json(FIXTURE.read_text(encoding="utf-8"))
        cls.empty_decision = ContextDecision.model_validate(
            {
                "hypotheses": {},
                "fragments": {
                    "ids": [],
                    "reason": "No fragments are needed for this boundary test.",
                    "evidenceIDs": ["evidence.prompt"],
                },
                "files": {
                    "ids": [],
                    "reason": "No files are needed for this boundary test.",
                    "evidenceIDs": ["evidence.prompt"],
                },
                "providers": {
                    "ids": [],
                    "reason": "No providers are needed for this boundary test.",
                    "evidenceIDs": ["evidence.prompt"],
                },
                "workflows": {
                    "ids": [],
                    "reason": "No workflows are needed for this boundary test.",
                    "evidenceIDs": ["evidence.prompt"],
                },
                "gaps": {},
                "conflicts": {},
                "sufficiencyState": "sufficient",
                "sufficiencyReasons": ["The boundary inputs are directly inspectable."],
            }
        )

    def request(
        self,
        prompt: str = "Implement Issue 54",
        projection_ids: list[str] | None = None,
    ):
        return build_request(
            prompt=prompt,
            config=self.config,
            snapshot=self.snapshot,
            requested_projection_ids=projection_ids,
        )

    def test_establishes_cue_valid_context_and_packet(self) -> None:
        result = ContextEngine(root=REPO_ROOT).run(
            request=self.request(projection_ids=["agent-context-resolver", "code-intel"]),
            reasoner=RecordedContextProgram(self.decision),
        )
        self.assertEqual(result.state.sufficiency.state, "sufficient")
        self.assertIsNotNone(result.state.projection)
        assert result.state.projection is not None
        self.assertIn("resolver.context-workbook", result.state.projection.selected.fragment_ids)
        self.assertEqual(result.code_intel_projection["authority"], False)
        self.assertEqual(
            json.loads(result.hook_projection["hookSpecificOutput"]["additionalContext"])["schema"],
            "agent.resolver-prompt-surface.v2",
        )

    def test_requested_projection_ids_gate_projection_creation(self) -> None:
        resolver = ContextEngine(root=REPO_ROOT).run(
            request=self.request(), reasoner=RecordedContextProgram(self.decision)
        )
        self.assertIsNotNone(resolver.hook_projection)
        self.assertIsNone(resolver.code_intel_projection)

        code_intel = ContextEngine(root=REPO_ROOT).run(
            request=self.request(projection_ids=["code-intel"]),
            reasoner=RecordedContextProgram(self.decision),
        )
        self.assertIsNone(code_intel.hook_projection)
        self.assertIsNotNone(code_intel.code_intel_projection)

    def test_request_boundary_scopes_all_reasoner_inputs(self) -> None:
        payload = self.request().model_dump(by_alias=True)
        payload["allowedPaths"] = [".codex/context-model"]
        request = ContextRequest.model_validate(payload)
        reasoner = CapturingProgram(self.empty_decision)

        result = ContextEngine(root=REPO_ROOT).run(request=request, reasoner=reasoner)

        inventory = reasoner.inputs["inventory"]
        self.assertEqual(inventory.fragments, {})
        self.assertEqual(inventory.providers, {})
        self.assertNotIn("lua-first", inventory.workflows)
        self.assertEqual(reasoner.inputs["code_intel"], {})
        observations = reasoner.inputs["observations"]
        self.assertNotIn("provider.registry", observations)
        self.assertEqual(
            observations["repository.current"].facts["selectedPaths"], []
        )
        self.assertNotIn("evidence.code-intel", reasoner.inputs["evidence"])
        self.assertEqual(result.state.inventory, inventory)

    def test_request_boundary_retains_fragment_prerequisite_closure(self) -> None:
        payload = self.request().model_dump(by_alias=True)
        payload["allowedPaths"] = [".codex/context-workbook"]
        request = ContextRequest.model_validate(payload)
        reasoner = CapturingProgram(self.empty_decision)

        ContextEngine(root=REPO_ROOT).run(request=request, reasoner=reasoner)

        inventory = reasoner.inputs["inventory"]
        self.assertEqual(
            set(inventory.fragments),
            {"resolver.context-workbook", "resolver.lifecycle"},
        )
        self.assertEqual(
            inventory.fragments["resolver.context-workbook"].prerequisites,
            ["resolver.lifecycle"],
        )
        selected_paths = reasoner.inputs["observations"]["repository.current"].facts[
            "selectedPaths"
        ]
        self.assertIn(".codex/context-workbook/context-workbook.py", selected_paths)
        self.assertNotIn(
            ".codex/plugins/agent-context-resolver/SKILL.md", selected_paths
        )

    def test_fragment_selection_requires_prerequisite_closure(self) -> None:
        payload = self.request().model_dump(by_alias=True)
        payload["allowedPaths"] = [".codex/context-workbook"]
        request = ContextRequest.model_validate(payload)
        value = self.empty_decision.model_dump(by_alias=True)
        value["fragments"]["ids"] = ["resolver.context-workbook"]
        decision = ContextDecision.model_validate(value)

        with self.assertRaisesRegex(
            EngineError, "selected fragments without prerequisites"
        ):
            ContextEngine(root=REPO_ROOT).run(
                request=request, reasoner=RecordedContextProgram(decision)
            )

    def test_cue_state_requires_fragment_prerequisite_closure(self) -> None:
        result = ContextEngine(root=REPO_ROOT).run(
            request=self.request(), reasoner=RecordedContextProgram(self.decision)
        )
        value = result.state.model_dump(by_alias=True, exclude_none=True)
        value["selected"]["fragments"] = [
            item
            for item in value["selected"]["fragments"]
            if item["fragmentID"] != "resolver.lifecycle"
        ]
        value["projection"]["selected"]["fragmentIDs"].remove(
            "resolver.lifecycle"
        )
        state = ContextState.model_validate(value)

        with self.assertRaisesRegex(EngineError, "selectedFragmentPrerequisites"):
            cue_validate_state(REPO_ROOT / ".codex/context-model", state)

    def test_request_boundary_filters_workflow_entries_and_provider_routes(self) -> None:
        payload = self.request().model_dump(by_alias=True)
        payload["allowedPaths"] = [
            ".codex/plugins/code-intel",
            "chezmoi/private_dot_config/nvim",
        ]
        request = ContextRequest.model_validate(payload)
        reasoner = CapturingProgram(self.empty_decision)

        ContextEngine(root=REPO_ROOT).run(request=request, reasoner=reasoner)

        code_intel = reasoner.inputs["code_intel"]
        workflow = code_intel[
            ".codex/plugins/code-intel/reference/workflows/lua-first/workflow.json"
        ]
        self.assertTrue(workflow["entrypoints"])
        self.assertTrue(
            all(
                item["path"].startswith("chezmoi/private_dot_config/nvim/")
                for item in workflow["entrypoints"]
            )
        )
        routing = code_intel[
            ".codex/plugins/code-intel/reference/lsp/provider-routing.json"
        ]
        self.assertNotIn("wezterm-lua", {route["id"] for route in routing["routes"]})
        inventory = reasoner.inputs["inventory"]
        self.assertTrue(
            all(
                "wezterm" not in pattern
                for pattern in inventory.providers["lua-language-server"].path_globs
            )
        )
        selected_paths = reasoner.inputs["observations"]["repository.current"].facts[
            "selectedPaths"
        ]
        self.assertFalse(any("wezterm" in path for path in selected_paths))

    def test_prompt_change_invalidates_dependent_nodes_only(self) -> None:
        first = ContextEngine(root=REPO_ROOT).run(
            request=self.request("Implement Issue 54"), reasoner=RecordedContextProgram(self.decision)
        )
        second = ContextEngine(root=REPO_ROOT).run(
            request=self.request("Inspect Issue 54"), reasoner=RecordedContextProgram(self.decision)
        )
        self.assertEqual(first.trace["inventory"], second.trace["inventory"])
        self.assertEqual(first.trace["code-intel"], second.trace["code-intel"])
        self.assertNotEqual(first.trace["prompt"], second.trace["prompt"])
        self.assertNotEqual(first.trace["projection"], second.trace["projection"])

    def test_unknown_provider_fails_closed(self) -> None:
        value = self.decision.model_dump(by_alias=True)
        value["providers"]["ids"] = ["unknown-provider"]
        decision = ContextDecision.model_validate(value)
        with self.assertRaises(EngineError):
            ContextEngine(root=REPO_ROOT).run(
                request=self.request(), reasoner=RecordedContextProgram(decision)
            )

    def test_outside_file_fails_closed(self) -> None:
        value = self.decision.model_dump(by_alias=True)
        value["files"]["ids"] = [".github/workflows/cue-contracts.yml"]
        decision = ContextDecision.model_validate(value)
        with self.assertRaises(EngineError):
            ContextEngine(root=REPO_ROOT).run(
                request=self.request(), reasoner=RecordedContextProgram(decision)
            )

    def test_request_file_cannot_widen_configured_paths(self) -> None:
        payload = self.request().model_dump(by_alias=True)
        payload["allowedPaths"] = ["."]
        request = ContextRequest.model_validate(payload)
        with self.assertRaisesRegex(EngineError, "widens configured path boundary"):
            ContextEngine(root=REPO_ROOT).run(
                request=request, reasoner=RecordedContextProgram(self.decision)
            )

    def test_requested_revision_controls_inventory_materialization(self) -> None:
        with tempfile.TemporaryDirectory(prefix="context-workbook-revision-") as temporary:
            repository = Path(temporary) / "repository"
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--quiet",
                    "--depth",
                    "1",
                    "--no-local",
                    str(REPO_ROOT),
                    str(repository),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            seed = repository / ".codex/context-model/seed.cue"
            current_seed = seed.read_text(encoding="utf-8")
            historical_seed = current_seed.replace(
                '"code-intel.provider-routing": {',
                '"code-intel.provider-routing-at-revision": {',
                1,
            )
            self.assertNotEqual(historical_seed, current_seed)
            seed.write_text(historical_seed, encoding="utf-8")
            subprocess.run(
                ["git", "add", ".codex/context-model/seed.cue"],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Context Workbook Tests",
                    "-c",
                    "user.email=context-workbook@example.invalid",
                    "-c",
                    "commit.gpgSign=false",
                    "commit",
                    "--quiet",
                    "-m",
                    "historical inventory",
                ],
                cwd=repository,
                check=True,
            )
            historical_revision = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                cwd=repository,
                check=True,
                capture_output=True,
                text=True,
            ).stdout.strip()
            seed.write_text(current_seed, encoding="utf-8")
            subprocess.run(
                ["git", "add", ".codex/context-model/seed.cue"],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Context Workbook Tests",
                    "-c",
                    "user.email=context-workbook@example.invalid",
                    "-c",
                    "commit.gpgSign=false",
                    "commit",
                    "--quiet",
                    "-m",
                    "current inventory",
                ],
                cwd=repository,
                check=True,
            )
            historical_config, historical_snapshot = load_workbook_config(
                repository, revision=historical_revision
            )
            request = build_request(
                prompt="Inspect the local historical revision",
                config=historical_config,
                snapshot=historical_snapshot,
            )
            with self.assertRaisesRegex(EngineError, "unknown fragments"):
                ContextEngine(root=repository).run(
                    request=request, reasoner=RecordedContextProgram(self.decision)
                )

    def test_resolved_revision_keeps_config_and_state_on_same_snapshot(self) -> None:
        with tempfile.TemporaryDirectory(prefix="context-workbook-authority-") as temporary:
            repository = Path(temporary) / "repository"
            subprocess.run(
                [
                    "git",
                    "clone",
                    "--quiet",
                    "--depth",
                    "1",
                    "--no-local",
                    str(REPO_ROOT),
                    str(repository),
                ],
                check=True,
                capture_output=True,
                text=True,
            )
            historical_config, historical_snapshot = load_workbook_config(repository)
            historical_revision = historical_snapshot.resolved_revision

            workbook = repository / ".codex/context-model/workbook.cue"
            current_workbook = workbook.read_text(encoding="utf-8").replace(
                "maxSelectedFiles: 32", "maxSelectedFiles: 1", 1
            )
            workbook.write_text(current_workbook, encoding="utf-8")
            model = repository / ".codex/context-model/model.cue"
            current_model = model.read_text(encoding="utf-8").replace(
                'schema:              "dotfiles.context-state.v0"',
                'schema:              "dotfiles.context-state.current"',
                1,
            )
            model.write_text(current_model, encoding="utf-8")
            subprocess.run(
                ["git", "add", ".codex/context-model"],
                cwd=repository,
                check=True,
            )
            subprocess.run(
                [
                    "git",
                    "-c",
                    "user.name=Context Workbook Tests",
                    "-c",
                    "user.email=context-workbook@example.invalid",
                    "-c",
                    "commit.gpgSign=false",
                    "commit",
                    "--quiet",
                    "-m",
                    "current authority drift",
                ],
                cwd=repository,
                check=True,
            )

            self.assertEqual(historical_config.max_selected_files, 32)
            current_config, current_snapshot = load_workbook_config(repository)
            self.assertEqual(current_config.max_selected_files, 1)
            self.assertNotEqual(current_snapshot.resolved_revision, historical_revision)
            request = build_request(
                prompt="Inspect one coherent historical authority snapshot",
                config=historical_config,
                snapshot=historical_snapshot,
            )
            self.assertEqual(request.repository.revision, historical_revision)

            result = ContextEngine(root=repository).run(
                request=request, reasoner=RecordedContextProgram(self.decision)
            )
            self.assertEqual(result.state.sufficiency.state, "sufficient")

    def test_repository_observation_records_resolved_commit(self) -> None:
        result = ContextEngine(root=REPO_ROOT).run(
            request=self.request(), reasoner=RecordedContextProgram(self.decision)
        )
        facts = result.state.observations["repository.current"].facts
        self.assertEqual(facts["requestedRevision"], self.snapshot.resolved_revision)
        self.assertRegex(facts["resolvedRevision"], r"^[0-9a-f]{40}$")

    def test_missing_model_uses_chatgpt_authenticated_codex_default(self) -> None:
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CONTEXT_WORKBOOK_DSPY_MODEL", None)
            reasoner = production_reasoner_or_fail_closed()
        self.assertEqual(type(reasoner).__name__, "DspyContextProgram")

    def test_runtime_auth_failure_uses_shared_fail_closed_decision(self) -> None:
        result = ContextEngine(root=REPO_ROOT).run(
            request=self.request(), reasoner=UnavailableProgram()
        )
        self.assertIn("gap.dspy-unavailable", result.state.gaps)
        self.assertEqual(result.state.sufficiency.state, "insufficient")

    def test_complete_gap_map_overrides_sufficiency_claim(self) -> None:
        value = self.decision.model_dump(by_alias=True)
        value["gaps"] = {
            "gap.missing-input": {
                "kind": "missing-input",
                "description": "A required input is absent.",
                "blocksSufficiency": True,
                "requiredEvidenceIDs": [],
            }
        }
        decision = ContextDecision.model_validate(value)
        result = ContextEngine(root=REPO_ROOT).run(
            request=self.request(), reasoner=RecordedContextProgram(decision)
        )
        self.assertEqual(result.state.sufficiency.state, "insufficient")
        self.assertIsNone(result.state.projection)
        self.assertEqual(result.state.sufficiency.blocking_gap_ids, ["gap.missing-input"])


if __name__ == "__main__":
    unittest.main()
