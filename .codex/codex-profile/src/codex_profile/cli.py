from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path
from typing import Sequence

from codex_profile import reporting
from codex_profile.collector import ingest_rollouts
from codex_profile.contracts import canonical_bytes
from codex_profile.handoff import create_handoff
from codex_profile.runner import run_projected
from codex_profile.storage import ProfileStorage


COMMANDS = {"ingest", "analyze", "export", "handoff", "run-projected"}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Codex rollout profile collector")
    subcommands = parser.add_subparsers(dest="command", required=True)

    ingest = subcommands.add_parser("ingest", help="admit rollout JSONL records into DuckDB")
    ingest.add_argument("--root", required=True, help="Codex root, sessions directory, or one JSONL file")
    ingest.add_argument("--repo", default="", help="repository path or substring used for rollout filtering")
    ingest.add_argument("--database", required=True, help="DuckDB database path")
    ingest.add_argument("--strict", action="store_true", help="return 3 when strict diagnostics are emitted")

    analyze = subcommands.add_parser("analyze", help="print a deterministic usage summary from DuckDB")
    analyze.add_argument("--database", required=True, help="DuckDB database path")

    export = subcommands.add_parser("export", help="export deterministic summary files from DuckDB")
    export.add_argument("--database", required=True, help="DuckDB database path")
    export.add_argument("--out", required=True, help="output directory")

    handoff = subcommands.add_parser("handoff", help="create a manual continuation handoff")
    handoff_commands = handoff.add_subparsers(dest="handoff_command", required=True)
    create = handoff_commands.add_parser("create")
    create.add_argument("--objective", required=True)
    create.add_argument("--current-operation", required=True)
    create.add_argument("--next-operation", required=True)
    create.add_argument("--completion-criterion", action="append", required=True)
    for option in ("invariant", "decision", "passing", "failing", "not-run", "evidence-pointer", "open-question"):
        create.add_argument(f"--{option}", action="append", default=[])

    projected = subcommands.add_parser(
        "run-projected", help="run a command and print a bounded structured result"
    )
    projected.add_argument("argv", nargs=argparse.REMAINDER)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args_list = list(sys.argv[1:] if argv is None else argv)
    if not args_list or args_list[0] not in COMMANDS:
        return reporting.main(args_list)

    parser = build_parser()
    args = parser.parse_args(args_list)
    if args.command == "ingest":
        return _ingest(args)
    if args.command == "analyze":
        return _analyze(args)
    if args.command == "export":
        return _export(args)
    if args.command == "handoff":
        try:
            json_path, md_path, packet = create_handoff(args)
        except (OSError, RuntimeError, ValueError) as error:
            print(f"handoff creation failed: {error}", file=sys.stderr)
            return 2
        print(json_path)
        print(md_path)
        print(
            "Start a new Codex session at "
            f"{packet.repository.root}; read {json_path} as authoritative, continue "
            "nextOperation, preserve invariants, and stop on completion or a blocking gap."
        )
        return 0
    if args.command == "run-projected":
        if len(args_list) < 2 or args_list[1] != "--":
            print("run-projected requires -- immediately before the command", file=sys.stderr)
            return 2
        command = args_list[2:]
        try:
            result, exit_code = run_projected(command)
        except (OSError, RuntimeError, ValueError) as error:
            print(f"run-projected failed: {error}", file=sys.stderr)
            return 2
        sys.stdout.buffer.write(canonical_bytes(result))
        return exit_code
    parser.error(f"unknown command: {args.command}")
    return 2


def _ingest(args: argparse.Namespace) -> int:
    root = Path(args.root).expanduser()
    if not root.exists():
        print(f"missing root: {root}", file=sys.stderr)
        return 2
    storage = ProfileStorage(Path(args.database))
    try:
        result = ingest_rollouts(root=root, repo=args.repo, storage=storage)
        summary = storage.summary()
        strict_diagnostics = storage.strict_diagnostic_count(result.active_sources)
    finally:
        storage.close()

    print(f"files_seen: {result.files_seen}")
    print(f"files_ingested: {result.files_ingested}")
    print(f"raw_inserted: {result.counts.raw_inserted}")
    print(f"normalized_inserted: {result.counts.normalized_inserted}")
    print(f"diagnostics_inserted: {result.counts.diagnostics_inserted}")
    print(f"raw_total: {summary['raw_observations']}")
    print(f"normalized_total: {summary['normalized_usage_observations']}")
    if args.strict and strict_diagnostics:
        print(f"strict_diagnostics: {strict_diagnostics}", file=sys.stderr)
        return 3
    return 0


def _analyze(args: argparse.Namespace) -> int:
    storage = ProfileStorage(Path(args.database), readonly=True)
    try:
        summary = storage.summary()
    finally:
        storage.close()
    print(_summary_markdown(summary), end="")
    return 0


def _export(args: argparse.Namespace) -> int:
    storage = ProfileStorage(Path(args.database), readonly=True)
    try:
        summary = storage.summary()
    finally:
        storage.close()

    out = Path(args.out).expanduser()
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    (out / "summary.md").write_text(_summary_markdown(summary), encoding="utf-8")
    with (out / "summary.csv").open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["metric", "value"])
        writer.writerow(["raw_observations", summary["raw_observations"]])
        writer.writerow(["normalized_usage_observations", summary["normalized_usage_observations"]])
        for key, value in summary["tokens"].items():
            writer.writerow([f"tokens_{key}", value])
        for key, value in summary["diagnostics"].items():
            writer.writerow([f"diagnostic_{key}", value])
    print(f"exported: {out}")
    return 0


def _summary_markdown(summary: dict) -> str:
    lines = [
        "# Codex rollout profile",
        "",
        "## Coverage",
        "",
        f"- raw observations: `{summary['raw_observations']}`",
        f"- normalized usage observations: `{summary['normalized_usage_observations']}`",
        "",
        "## Token usage",
        "",
    ]
    for key in (
        "total",
        "reported_input",
        "cached_input",
        "fresh_input",
        "output",
        "reasoning_output",
    ):
        lines.append(f"- {key.replace('_', ' ')}: `{summary['tokens'][key]}`")
    lines.extend(["", "## Diagnostics", ""])
    if summary["diagnostics"]:
        for code, count in sorted(summary["diagnostics"].items()):
            lines.append(f"- `{code}`: {count}")
    else:
        lines.append("- none")
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
