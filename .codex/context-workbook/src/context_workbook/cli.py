"""Transport adapters for the authoritative context graph service."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .graph_service import main as graph_main


def _hook_failure() -> dict[str, object]:
    surface = {
        "schema": "agent.resolver-prompt-surface.v2",
        "requestID": None,
        "sufficiency": {
            "state": "insufficient",
            "reasons": [
                "Prompt-only graph requests have no explicit roots; the bounded proposal adapter is not available."
            ],
            "blockingGapIDs": ["gap.context-root-proposal-required"],
            "unresolvedConflictIDs": [],
        },
        "context": None,
        "diagnostics": [],
        "execution": {
            "mode": "prompt-only",
            "routeExecution": False,
            "sourceAuthority": False,
            "rawTranscriptForwarding": False,
        },
    }
    return {
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": json.dumps(surface, sort_keys=True, separators=(",", ":")),
        }
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo-root", type=Path, default=Path.cwd())
    parser.add_argument("--request-file", type=Path)
    parser.add_argument("--proposal-file", type=Path)
    parser.add_argument("--hook", action="store_true")
    parser.add_argument("--prompt")
    args, _ = parser.parse_known_args()

    if args.hook:
        envelope = json.load(sys.stdin)
        if envelope.get("hook_event_name") == "UserPromptSubmit":
            print(json.dumps(_hook_failure(), sort_keys=True, separators=(",", ":")))
        return 0
    if args.request_file is None:
        parser.error("--request-file is required; prompt-only selection fails closed")
    arguments = [
        "--repo-root",
        str(args.repo_root),
        "--request-file",
        str(args.request_file),
    ]
    if args.proposal_file is not None:
        arguments.extend(["--proposal-file", str(args.proposal_file)])
    return graph_main(arguments)


if __name__ == "__main__":
    raise SystemExit(main())
