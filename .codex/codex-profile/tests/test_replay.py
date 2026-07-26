#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from datetime import timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PACKAGE_SRC = REPO_ROOT / ".codex/codex-profile/src"
FIXTURE_ROOT = REPO_ROOT / ".codex/codex-profile/fixtures"
if str(PACKAGE_SRC) not in sys.path:
    sys.path.insert(0, str(PACKAGE_SRC))

from codex_profile import reporting as profile_module


class ReplayFixtureTests(unittest.TestCase):
    def test_current_profiler_matches_replay_golden(self) -> None:
        replay = json.loads((FIXTURE_ROOT / "replay/profiler-v0.json").read_text())
        golden = json.loads((FIXTURE_ROOT / "golden/profiler-v0-summary.json").read_text())
        window = profile_module.Window(
            profile_module.parse_datetime_value(replay["window"]["since"], timezone.utc),
            profile_module.parse_datetime_value(replay["window"]["until"], timezone.utc),
        )
        totals = {
            "cases": 0,
            "selected_lines": 0,
            "token_counter_resets": 0,
            "token_discrepancies": 0,
            "token_events_counted": 0,
            "tokens_total": 0,
        }
        case_ids: list[str] = []
        with tempfile.TemporaryDirectory() as tmp:
            for case in replay["cases"]:
                path = Path(tmp) / f"{case['id']}.jsonl"
                path.write_text(
                    "".join(json.dumps(event, sort_keys=True) + "\n" for event in case["events"]),
                    encoding="utf-8",
                )
                events, readable = profile_module.read_events(path, timezone.utc)
                self.assertTrue(readable, case["id"])
                result, _ = profile_module.profile_session(path, events, window, timezone.utc)
                actual = {
                    "selected_lines": result.selected_lines,
                    "tokens_total": result.tokens.total,
                    "token_events_counted": result.token_events_counted,
                    "token_discrepancies": result.token_discrepancies,
                    "token_counter_resets": result.token_counter_resets,
                    "token_missing_baseline": result.token_missing_baseline,
                }
                self.assertEqual(actual, case["expected"], case["id"])
                if repository := case.get("repository"):
                    self.assertTrue(profile_module.session_matches_repo(path, events, repository["matches"]))
                    self.assertFalse(profile_module.session_matches_repo(path, events, repository["rejects"]))
                case_ids.append(case["id"])
                totals["cases"] += 1
                for field in totals.keys() - {"cases"}:
                    totals[field] += actual[field]
        self.assertEqual(case_ids, golden["case_ids"])
        self.assertEqual(totals, golden["totals"])


if __name__ == "__main__":
    unittest.main()
