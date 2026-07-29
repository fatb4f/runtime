from __future__ import annotations

import json
from pathlib import Path


def test_codex_source_lock_pins_stable_authority_and_alpha_corpus() -> None:
    lock_path = Path(__file__).parents[1] / "codex-source-lock.json"
    assert json.loads(lock_path.read_text(encoding="utf-8")) == {
        "schema": "runtime.codex-source-lock.v1",
        "upstream": {
            "repository": "openai/codex",
            "channel": "stable",
            "version": "0.145.0",
            "tag": "rust-v0.145.0",
            "revision": "25af12f7e61572b0bc18ddb1008be543b91519b0",
        },
        "compatibilityProducers": [
            {
                "version": "0.146.0-alpha.12",
                "purpose": "forward compatibility corpus",
            }
        ],
    }
