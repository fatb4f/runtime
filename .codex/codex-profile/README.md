# Session handoff generator

`handoff` creates one private continuation artifact from the staged Git index
and the current Codex rollout:

```bash
uv run handoff create
```

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
qualification commands. Validation currently recognizes direct pytest,
handoff help, uv lock-check, build, and installation commands; compound shell
commands remain ordinary operations.

Rollout call admission is intentionally handwritten and pinned to function
calls, function outputs, custom-tool calls, and custom-tool outputs. Function
and custom families must pair exactly. Custom input is truncated at a UTF-8
boundary to 32 KiB with a diagnostic, and shell identity comes only from the
recognized standalone function tools `exec_command`, `shell`, and
`shell_command`. Other exact pinned response variants are ignored when they do
not affect this projection; unknown call-like variants and the deferred
`local_shell_call` variant fail admission.

Validate this subtree with:

```bash
uv run pytest .codex/codex-profile/tests -q
uv run handoff --help
```
