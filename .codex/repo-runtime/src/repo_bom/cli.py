from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from repo_intel import DiscoveryError, discover

from .bom import BomError, assemble, canonical_bytes, validate


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="repo-bom")
    commands = root.add_subparsers(dest="command", required=True)
    generate_command = commands.add_parser("generate")
    generate_command.add_argument("--repository", type=Path, required=True)
    generate_command.add_argument("--output", type=Path, required=True)
    validate_command = commands.add_parser("validate")
    validate_command.add_argument("file", type=Path)
    check_command = commands.add_parser("check")
    check_command.add_argument("--repository", type=Path, required=True)
    check_command.add_argument("--expected", type=Path, required=True)
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "generate":
            result = _generate(args.repository)
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_name(f".{args.output.name}.tmp")
            temporary.write_bytes(result)
            temporary.replace(args.output)
            return 0
        if args.command == "validate":
            validate(json.loads(args.file.read_text()))
            return 0
        expected = args.expected.read_bytes()
        actual = _generate(args.repository)
        if actual != expected:
            print("Repository BOM is stale or non-canonical", file=sys.stderr)
            return 1
        return 0
    except (BomError, DiscoveryError, OSError, json.JSONDecodeError) as error:
        print(str(error), file=sys.stderr)
        return 2


def _generate(repository: Path) -> bytes:
    return canonical_bytes(assemble(discover(repository)))


if __name__ == "__main__":
    raise SystemExit(main())
