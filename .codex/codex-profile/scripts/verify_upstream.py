#!/usr/bin/env python3
"""Verify issue #72's pinned Codex source and supported shape fragments."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = ROOT / "fixtures/upstream/rust-v0.146.0-alpha.2/manifest.json"


def verify(manifest_path: Path, source_root: Path, strict_digest: bool) -> list[str]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    errors: list[str] = []
    for relative, contract in sorted(manifest["files"].items()):
        path = source_root / relative
        if not path.is_file():
            errors.append(f"missing upstream source: {relative}")
            continue
        content = path.read_bytes()
        if strict_digest:
            actual = hashlib.sha256(content).hexdigest()
            if actual != contract["sha256"]:
                errors.append(
                    f"digest drift: {relative}: expected {contract['sha256']}, got {actual}"
                )
        text = content.decode("utf-8")
        for fragment in contract["required_fragments"]:
            if fragment not in text:
                errors.append(f"unsupported shape drift: {relative}: missing {fragment!r}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument(
        "--allow-content-drift",
        action="store_true",
        help="check supported fragments without requiring the pinned full-file digests",
    )
    args = parser.parse_args()
    errors = verify(args.manifest, args.source_root, not args.allow_content_drift)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("upstream contract verified: rust-v0.146.0-alpha.2")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
