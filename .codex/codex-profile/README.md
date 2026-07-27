# Session handoff generator

`handoff` creates one private continuation artifact from the staged Git index
and the current Codex rollout:

```bash
uv run handoff create
```

The command intentionally runs `git add -A` before collecting the stable index
projection. Publication is atomic, but staging is not rolled back if a later
rollout, model, or publication gate fails.

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

Validate this subtree with:

```bash
uv run pytest .codex/codex-profile/tests -q
uv run handoff --help
```
