#!/usr/bin/env python3
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
VERIFY_PATH = REPO_ROOT / ".codex/codex-profile/scripts/verify_upstream.py"
spec = importlib.util.spec_from_file_location("codex_profile_verify_upstream", VERIFY_PATH)
assert spec and spec.loader
verify_module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = verify_module
spec.loader.exec_module(verify_module)


class VerifyUpstreamTests(unittest.TestCase):
    def test_accepts_matching_offline_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source/codex-rs/protocol/src/protocol.rs"
            source.parent.mkdir(parents=True)
            content = b"pub last_token_usage: TokenUsage\n"
            source.write_bytes(content)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({
                    "files": {
                        "codex-rs/protocol/src/protocol.rs": {
                            "sha256": hashlib.sha256(content).hexdigest(),
                            "required_fragments": ["last_token_usage"],
                        }
                    }
                }),
                encoding="utf-8",
            )

            self.assertEqual(verify_module.verify(manifest, root / "source", True), [])

    def test_rejects_shape_drift_without_live_network(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "source/codex-rs/protocol/src/protocol.rs"
            source.parent.mkdir(parents=True)
            source.write_text("pub legacy_last_usage: TokenUsage\n", encoding="utf-8")
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps({
                    "files": {
                        "codex-rs/protocol/src/protocol.rs": {
                            "sha256": "0" * 64,
                            "required_fragments": ["last_token_usage"],
                        }
                    }
                }),
                encoding="utf-8",
            )

            errors = verify_module.verify(manifest, root / "source", False)
            self.assertEqual(len(errors), 1)
            self.assertIn("unsupported shape drift", errors[0])


if __name__ == "__main__":
    unittest.main()
