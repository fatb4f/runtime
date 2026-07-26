# `codex-profile` agent workflow

## Scope and authority

These instructions govern work under `.codex/codex-profile/`.

The parent `.codex/AGENTS.md` remains authoritative for the contract-extension DAG, assertion catalogs, equality gates, Hypothesis strategies, fuzzing, and qualification. This file narrows the operational workflow for collecting, analyzing, and exporting Codex rollout evidence and for creating manual handoffs.

The authority order is:

```text
pinned upstream rollout shapes and replay evidence
  -> CUE schemas and named properties
  -> positive and negative contract probes
  -> typed adapters
  -> read-only collection and normalization
  -> DuckDB ingestion
  -> analysis
  -> exported evidence
```

No downstream report, handoff, fixture, or observed quota percentage may redefine an upstream schema or assertion.

## Operating invariants

All changes and executions must preserve these invariants:

1. Collection is read-only with respect to Codex rollout sources and target repositories.
2. Event timestamps define the analysis window; file modification time is not evidence time.
3. Windows are half-open: `since <= event_timestamp < until`.
4. Structured token observations are authoritative when recognized; textual token reports are not counted as usage evidence.
5. Cumulative counters contribute only validated positive deltas, with explicit handling of baselines, resets, and discrepancies.
6. Repository filtering must be explicit. A missing repository filter means all admitted sessions in the window.
7. Normalization, ordering, serialization, and exports must be deterministic.
8. Generated summaries never manufacture missing observations or silently upgrade partial coverage to complete coverage.
9. Local state may contain private paths, arguments, and unredacted output. Do not publish it.
10. Handoffs are control-boundary artifacts, not routine progress logs.

## Standard profile workflow

Use one bounded pipeline:

```text
select source and time window
  -> ingest once
  -> inspect diagnostics
  -> analyze from DuckDB
  -> export bounded evidence
  -> interpret coverage before drawing conclusions
```

### 1. Establish the observation contract

Before running the profiler, record:

- Codex source root;
- repository filter, or an explicit decision to analyze all repositories;
- timezone;
- half-open `since` and `until` timestamps;
- destination DuckDB path;
- export destination;
- the question the analysis is intended to answer.

Do not change these parameters mid-analysis. A changed window, filter, or evidence rule defines a new run.

### 2. Ingest once

From the repository root:

```bash
uv run -- codex-profile ingest \
  --root ~/.local/share/codex \
  --repo /absolute/path/to/repository \
  --database ~/.local/state/codex-profile/profile.duckdb \
  --strict
```

Omit `--repo` only when cross-repository analysis is intentional.

Prefer one complete ingest over repeated scans during the same investigation. Re-ingest only when:

- new rollout evidence must be admitted;
- the observation contract changed;
- the ingestion implementation changed;
- a failed or partial run must be reproduced.

### 3. Inspect diagnostics before conclusions

Treat diagnostics as a gate. Check at least:

- candidate and selected files;
- scanned, timestamped, selected, malformed, unreadable, and untimestamped rows;
- recognized token observations and counted events;
- missing baselines, counter resets, and discrepancies;
- complete, partial, or absent structured-usage status;
- repository-filter match counts.

A report with token discrepancies, missing baselines, unreadable sources, malformed rows, or partial token status may still be useful, but conclusions must state the limitation. Never present a partial observation as an exact total.

### 4. Analyze the admitted database

```bash
uv run -- codex-profile analyze \
  --database ~/.local/state/codex-profile/profile.duckdb
```

Analyze the existing DuckDB database rather than repeatedly reparsing rollouts. Distinguish:

- raw structured tokens from quota-weighted usage;
- cached input from uncached input;
- output from reasoning tokens;
- model-visible tool calls from shell commands inside a tool call;
- sessions from turns;
- event time from file layout and file modification time;
- observed correlation from a proven quota-accounting rule.

Quota percentages are observations emitted by Codex, not a declared billing formula. Any conversion such as `1% ~= N raw tokens` is an empirical estimate scoped to the observed model and workload shape.

### 5. Export bounded evidence

```bash
uv run -- codex-profile export \
  --database ~/.local/state/codex-profile/profile.duckdb \
  --out /tmp/codex-profile
```

Exports must remain reproducible from the admitted database. Keep raw private state local. Share only the minimum artifacts required for analysis, and remove obsolete local packets deliberately.

## Rollout-bundle workflow for external analysis

When a reviewer needs the source rollouts, bundle the exact event-date window without modifying source files:

```bash
cd ~/.local/share/codex/sessions
find 2026/07/{22..26} -type f -name 'rollout-*.jsonl' -print \
  | sort \
  | zip -@ ~/codex-rollouts-2026-07-22_2026-07-26.zip
```

Adapt the date range and output name to the declared observation contract. Preserve relative paths and deterministic lexical ordering. Record the archive hash when it will serve as evidence.

A directory-date selection is only a transport convenience. The profiler must still apply event-timestamp filtering inside the archive or extracted source tree.

## Bounded command projection

Use the projection wrapper when command output may be large:

```bash
uv run -- codex-profile run-projected -- pytest -q
```

The literal `--` is required. The child command receives no stdin and is executed without a shell. Use the bounded JSON projection for agent context; use the retained manifest and byte artifacts as the complete evidence.

Do not paste full repetitive logs into the model when a bounded projection, artifact path, digest, and relevant lines are sufficient.

## Quota-aware execution control

The observed July 26, 2026 workload showed that cached input still consumed the weekly quota materially. A high cache ratio is not permission to restart or fan out sessions.

Use this control loop:

```text
one active implementation session
  -> batch local inspection
  -> define one bounded mutation
  -> apply the mutation
  -> run the narrowest relevant check
  -> run the complete qualification gate once
  -> continue in the same session when context remains valid
```

Required controls:

- Keep one active implementation session per objective and repository state.
- Batch related reads and inspections before editing.
- Avoid repeated full-tree scans and repeated unchanged validation commands.
- Prefer deterministic local tools over model-mediated inspection.
- Apply a coherent patch rather than many speculative micro-patches.
- Run narrow tests while iterating; run the complete gate at the qualification boundary.
- Do not run overlapping sessions against the same dirty worktree.
- Do not infer exact quota state from a stale percentage emitted by a concurrent session.
- Stop fan-out when two sessions are reproducing the same evidence or validation loop.

The following loop is prohibited:

```text
handoff
  -> fresh full-context session
  -> repeated tool and validation cycles
  -> non-terminal failure
  -> another handoff
  -> another fresh full-context session
```

## Manual handoff gate

Create a handoff only at a genuine context boundary, such as:

- the current session can no longer safely retain the necessary context;
- model or tool availability requires a new session;
- ownership changes to another agent or person;
- execution must pause for an external dependency;
- a clean checkpoint is required before a risky transition.

Do not create a handoff merely because:

- one command failed;
- a test needs another iteration;
- a patch is incomplete;
- the next operation is already obvious in the current session;
- quota conservation would be better served by continuing with the existing context.

Before creating a handoff:

1. Finish or explicitly interrupt the current operation.
2. Capture the canonical Git root, revision, branch, dirty paths, and staged paths.
3. Record only validated decisions and invariants.
4. Separate passing, failing, and not-run checks.
5. Name exactly one current operation and one next operation.
6. Give observable completion criteria.
7. Point to existing evidence rather than embedding large logs.
8. Record open questions without resolving them speculatively.

Create the packet with:

```bash
uv run -- codex-profile handoff create \
  --objective "finish the requested change" \
  --current-operation "implementing the adapter" \
  --next-operation "run qualification" \
  --invariant "preserve existing CLI behavior" \
  --completion-criterion "the qualification script passes"
```

The authoritative continuation input is `handoff.json`; `handoff.md` is a derived human projection. Both are bounded to 16 KiB and are written atomically under `~/.local/state/codex-profile/handoffs/<id>/`.

The receiving session must:

1. start at the recorded repository root;
2. read the authoritative JSON packet once;
3. verify that repository revision, branch, dirty paths, and staged paths still match;
4. stop and report drift rather than silently adapting the packet;
5. continue `nextOperation` directly;
6. avoid re-discovering facts already admitted by the packet;
7. create another handoff only if a new genuine boundary is reached.

## Change workflow for this subtree

Every code change follows the parent contract DAG:

```text
upstream evidence
  -> CUE schema extension
  -> named assertion invariants
  -> positive, negative, boundary, and metamorphic probes
  -> typed model or adapter
  -> runtime implementation
  -> deterministic qualification
  -> persisted report
```

Do not begin with implementation and retrofit the contract afterward. A runtime change is incomplete until its schema, named property, fixtures or generated cases, executable assertion, and persisted equality-gate evidence agree.

## Qualification

Use the repository's pinned environment and commands. At minimum, validate the current subtree with the commands documented in `README.md`, including:

```bash
cue fmt --check --files .codex/codex-profile/contracts/*.cue \
  .codex/codex-profile/contracts/fixtures/*/*.cue \
  .codex/codex-profile/contracts/fixtures/negative/*/*.cue
cue vet ./.codex/codex-profile/contracts
cue vet -c ./.codex/codex-profile/contracts
(cd .codex/codex-profile/contracts && cue vet ./fixtures/positive)
python .codex/codex-profile/tests/test_replay.py -v
uv run -- python .codex/codex-profile/tests/test_ingestion.py -v
```

Each immediate child under `contracts/fixtures/negative/` must fail `cue vet` for the intended property. A negative fixture that passes, or fails for an unrelated reason, does not qualify the property.

Run additional focused tests for changed modules and the repository's complete codex-profile qualification workflow when available. Do not repeatedly run the complete gate after every edit; run focused checks during iteration and the complete gate once the candidate change is coherent.

## Completion report

A completion report must state:

- the observation or change contract;
- files changed;
- database and export paths when applicable;
- exact commands run;
- passing, failing, and not-run checks;
- diagnostic limitations;
- whether structured token coverage was complete or partial;
- whether quota conclusions are direct observations or estimates;
- whether a handoff was created and why the boundary was genuine;
- remaining risks or open questions.

Do not claim completion from generated output alone. Completion requires the applicable contract, runtime, and qualification surfaces to agree.