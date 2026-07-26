from __future__ import annotations

import json
import unittest
from pathlib import Path

from context_workbook.models import ContextDecision, ContextRequest, SourceObservation


FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sufficient-decision.json"


class ModelTests(unittest.TestCase):
    def test_request_rejects_path_escape(self) -> None:
        with self.assertRaises(ValueError):
            ContextRequest.model_validate(
                {
                    "schema": "dotfiles.context-request.v0",
                    "requestID": "request-test",
                    "prompt": "test",
                    "repository": {"repository": "fatb4f/dotfiles", "root": ".", "revision": "HEAD"},
                    "allowedPaths": ["../outside"],
                    "requestedProjectionIDs": ["agent-context-resolver"],
                }
            )

    def test_observation_rejects_nested_claimant_field(self) -> None:
        with self.assertRaises(ValueError):
            SourceObservation.model_validate(
                {
                    "kind": "tool",
                    "subject": "cue",
                    "facts": {"nested": {"passed": True}},
                    "diagnostics": [],
                    "provenance": {
                        "semanticRole": "evidence",
                        "artifactClass": "runtime_observation",
                        "claimAuthority": "none",
                    },
                }
            )

    def test_decision_rejects_prose_derived_by(self) -> None:
        value = json.loads(FIXTURE.read_text(encoding="utf-8"))
        value["hypotheses"]["hypothesis.issue-54"]["derivedBy"] = "prose is not an ID"
        with self.assertRaises(ValueError):
            ContextDecision.model_validate(value)

    def test_decision_canonicalizes_gap_map_order(self) -> None:
        value = json.loads(FIXTURE.read_text(encoding="utf-8"))
        value["gaps"] = {
            "gap.z-last": {
                "kind": "missing-input",
                "description": "Last gap",
                "blocksSufficiency": True,
                "requiredEvidenceIDs": [],
            },
            "gap.a-first": {
                "kind": "missing-input",
                "description": "First gap",
                "blocksSufficiency": True,
                "requiredEvidenceIDs": [],
            },
        }
        decision = ContextDecision.model_validate(value)
        self.assertEqual(list(decision.gaps), ["gap.a-first", "gap.z-last"])


if __name__ == "__main__":
    unittest.main()
