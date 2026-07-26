# Codex profile contracts

This subtree is the contract-first foundation for issue #72. It now contains the
read-only rollout collector and DuckDB ingestion path. Checkpoint writers,
hooks, wrappers, Marimo analysis, and policy runtime remain deferred.

The dependency order is:

```text
pinned upstream shapes and replay evidence
  -> CUE schemas
  -> named assertion catalog
  -> positive and negative CUE probes
  -> typed adapters and read-only collector runtime
```

Validate the current slice with:

```bash
cue fmt --check --files .codex/codex-profile/contracts/*.cue \
  .codex/codex-profile/contracts/fixtures/*/*.cue \
  .codex/codex-profile/contracts/fixtures/negative/*/*.cue
cue vet ./.codex/codex-profile/contracts
cue vet -c ./.codex/codex-profile/contracts
(cd .codex/codex-profile/contracts && cue vet ./fixtures/positive)
python .codex/codex-profile/tests/test_replay.py -v
uv run -- python .codex/codex-profile/tests/test_ingestion.py -v
python .codex/codex-profile/scripts/verify_upstream.py --source-root /path/to/openai-codex-tag
```

Each immediate child of `contracts/fixtures/negative` must fail `cue vet`.

MVP CLI:

```bash
uv run -- codex-profile ingest \
  --root ~/.local/share/codex \
  --repo /home/_404/src/dotfiles \
  --database ~/.local/state/codex-profile/profile.duckdb \
  --strict
uv run -- codex-profile analyze \
  --database ~/.local/state/codex-profile/profile.duckdb
uv run -- codex-profile export \
  --database ~/.local/state/codex-profile/profile.duckdb \
  --out /tmp/codex-profile
```

## Manual handoffs

Create an explicit packet before resetting a long-running session:

```bash
uv run -- codex-profile handoff create \
  --objective "finish the requested change" \
  --current-operation "implementing the adapter" \
  --next-operation "run qualification" \
  --invariant "preserve existing CLI behavior" \
  --completion-criterion "the qualification script passes"
```

The command records the canonical Git root, revision, branch, dirty paths, and
staged paths. It atomically writes `handoff.json` and the derived `handoff.md`
under `~/.local/state/codex-profile/handoffs/<id>/`, then prints the manual
continuation instruction. Both projections are limited to 16 KiB.

To reset manually, finish or interrupt the current operation, run the command,
start a new Codex session at the printed repository root, and tell it to read
the printed authoritative JSON path and continue `nextOperation`.

## Bounded command projection

```bash
uv run -- \
  codex-profile run-projected -- pytest -q
```

The literal `--` is required. The child receives no stdin and is executed
directly without a shell. Complete byte-exact output is retained atomically as
`stdout.bin`, `stderr.bin`, and `manifest.json` under
`~/.local/state/codex-profile/command-results/<id>/`. The one JSON result
printed to stdout is limited to 4 KiB and 20 relevant lines; its artifact path
and hash address the complete manifest.

These state directories can contain source paths, command arguments, and
unredacted command output. Treat them as private local data, do not publish
them, and remove obsolete packets deliberately when they are no longer needed.
