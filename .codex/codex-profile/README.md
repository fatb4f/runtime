# Session handoff generator

`handoff` creates one private continuation artifact from the staged Git index
and the current Codex rollout:

```bash
uv run handoff create
```

Parser authority is pinned in `codex-source-lock.json`. The normative wire
contract comes from stable Codex `0.145.0` at revision
`25af12f7e61572b0bc18ddb1008be543b91519b0`; the private
`0.146.0-alpha.12` corpus is a forward-compatibility gate. Current upstream
`main` is observational only and cannot widen admission.

The command admits and projects the complete rollout before running `git add -A`
and collecting the stable index projection. Malformed or unsupported rollout
records therefore fail without changing the index. Publication is atomic, but
staging is not rolled back if a later repository, model, or publication gate
fails.

By default the artifact is written to:

```text
$XDG_STATE_HOME/handoff/<session-id>/handoff.json
```

Use `--rollout` to select an explicit rollout and `--output-root` to replace
the state root for tests or controlled tooling. Overrides do not waive
repository identity checks.

Without `--rollout` or `CODEX_ROLLOUT_PATH`, discovery searches
`$CODEX_HOME/sessions` and defaults `CODEX_HOME` to `~/.codex`.

The closed `codex.handoff.v0` document contains the stable staged repository
projection, continuation cues, the newest bounded chronological operation
window, explicit failures, and validation results for recognized runtime
qualification commands. Shell operations may be pending, running, succeeded,
or failed. A running operation has `sessionId` evidence and no `exitCode`;
terminal operations have `exitCode` evidence and no `sessionId`. Optional
operation fields are serialized as `null` when absent. Validation currently
recognizes direct pytest, handoff help, uv lock-check, build, and installation
commands; compound shell commands remain ordinary operations.

Stable unified execution can also fail before an exit code or resumable
session exists. The exact stable `exec_command failed for \`…\`: …` and
`write_stdin failed: …` families project as failed shell operations with
bounded terminal-error evidence and no fabricated exit code. Other non-JSON
shell output still requires the legacy terminal marker.

Rollout call admission is intentionally handwritten and pinned to function
calls, function outputs, custom-tool calls, and custom-tool outputs. Function
and custom families must pair exactly. Custom input is truncated at a UTF-8
boundary to 32 KiB with a diagnostic, and shell identity comes only from the
recognized standalone function tools `exec_command`, `write_stdin`, and
`shell_command`. Structured result arrays admit only the pinned text, image,
audio, and encrypted-content discriminators. Other exact pinned response
variants are ignored when they do not affect this projection; unknown
call-like variants and the deferred `local_shell_call` variant fail admission.

Validate this subtree with:

```bash
uv run --group test pytest .codex/codex-profile/tests -q
uv run handoff --help
```

Build a clean, directly installable tool wheel:

```bash
just bundle
uv tool install dist/codex_handoff-0.1.0-py3-none-any.whl
```

Digest-pin four private compatibility rollouts in the ignored
`.tmp/codex-rollout-compat.json` manifest, then scan them without committing
their paths or contents. Each rollout is checked against the repository
recorded in its own `session_meta`, so one corpus may cover multiple
repositories. Its producer version must be allowed by the source lock:

```bash
uv run python scripts/check-rollout-compat
```
