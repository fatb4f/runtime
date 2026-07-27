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

Validate this subtree with:

```bash
uv run pytest .codex/codex-profile/tests -q
uv run handoff --help
```
